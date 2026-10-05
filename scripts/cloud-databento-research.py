#!/usr/bin/env python3
"""Bounded September SIC/MBT screening via the existing keyless GCP operator."""
from __future__ import annotations
import argparse
import base64
import contextlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SOURCE_COMMIT = "a48da25628a211194b73bbc09026a9f152627d84"
PROJECT = "keep-and-lease"
BUCKET = "keep-and-lease-market-data"
PREFIX = "research/databento/september-2026-v1"
PRESETS = ("sic", "mbt")
SENSITIVE_VALUES = []  # Process memory only; never serialized.
MAX_COST = 1.0  # Combined cumulative estimate, including restored paid caches.


def validate_request(value):
    required = {"schema_version", "request_id", "action", "result_public_key_pem"}
    if set(value) != required | ({"references"} if value.get("action") == "screen" else set()):
        raise ValueError("Unexpected request fields")
    if value["schema_version"] != 1 or value["action"] not in ("estimate", "screen"):
        raise ValueError("Unsupported request")
    if not re.fullmatch(r"[a-z0-9-]{1,64}", value["request_id"]):
        raise ValueError("Invalid request ID")
    key = serialization.load_pem_public_key(value["result_public_key_pem"].encode())
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise ValueError("Require RSA public key of at least 3072 bits")
    if value["action"] == "screen":
        if set(value["references"]) != set(PRESETS):
            raise ValueError("Require both reference scenarios")
        for ref in value["references"].values():
            if set(ref) != {"units_per_share", "source", "as_of"}:
                raise ValueError("Unexpected reference fields")
            if not math.isfinite(ref["units_per_share"]) or not 0 < ref["units_per_share"] < 1:
                raise ValueError("Invalid units per share")
            if not isinstance(ref["source"], str) or not 1 <= len(ref["source"]) <= 1000:
                raise ValueError("Require source description")
            if not re.fullmatch(r"2026-\d{2}-\d{2}", ref["as_of"]):
                raise ValueError("Require reference as-of date")
    return key


def encrypt_result(payload, public_key, path):
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    cipher = AESGCM(data_key).encrypt(nonce, json.dumps(payload, allow_nan=False, default=str).encode(), b"databento-research-v1")
    wrapped = public_key.encrypt(data_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    encoded = {"version": 1, "algorithm": "RSA-OAEP-SHA256+AES-256-GCM",
               **{k: base64.b64encode(v).decode() for k, v in {"wrapped_key": wrapped, "nonce": nonce, "ciphertext": cipher}.items()}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(encoded) + "\n")


def load_research(root):
    spec = importlib.util.spec_from_file_location("databento_gold", root / "scripts/databento_gold.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Cache:
    """Append-only states; immutable content-addressed raw files, no IAM deletes."""
    def __init__(self, bucket, preset, output, research):
        self.bucket, self.output, self.research = bucket, output, research
        self.prefix = f"{PREFIX}/cache/{preset}/"

    def restore(self, config):
        records = list(self.bucket.list_blobs(prefix=self.prefix + "states/"))
        self.output.mkdir(parents=True, exist_ok=True)
        if not records:
            return self.research.state_at(self.output, config)
        latest = max(records, key=lambda x: x.name)
        state = json.loads(latest.download_as_bytes())
        if state["config"] != config:
            raise ValueError("Stored cache config differs; review before acquisition")
        self.research.save_json(self.output / "state.json", state)
        for name, row in state["streams"].items():
            if row["status"] == "done":
                path = self.output / "raw" / f"{name}.dbn.zst"
                path.parent.mkdir(parents=True, exist_ok=True)
                self.bucket.blob(self.prefix + f"raw/{row['sha256']}.dbn.zst").download_to_filename(path)
                if self.research.digest(path) != row["sha256"]:
                    raise ValueError("Stored raw cache checksum mismatch")
        return state

    def checkpoint(self, path, state):
        from google.api_core.exceptions import PreconditionFailed
        for name, row in state["streams"].items():
            if row["status"] == "done":
                blob = self.bucket.blob(self.prefix + f"raw/{row['sha256']}.dbn.zst")
                if not blob.exists():
                    try:
                        blob.upload_from_filename(self.output / "raw" / f"{name}.dbn.zst", if_generation_match=0)
                    except PreconditionFailed:
                        pass  # Another identical content-addressed object already exists.
        # Called before every charged streaming request and after raw upload.
        self.bucket.blob(self.prefix + f"states/{time.time_ns()}.json").upload_from_string(
            json.dumps(state), content_type="application/json", if_generation_match=0)


def metadata_cost(client, **request):
    from databento.common.error import BentoServerError
    for attempt in range(3):
        try:
            return client.metadata.get_cost(**request)
        except BentoServerError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def run(request, root, work, report):
    import databento as db
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    from google.cloud import storage
    import pandas as pd

    gold = load_research(root)
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = AuthorizedSession(credentials)
    response = session.get(f"https://secretmanager.googleapis.com/v1/projects/{PROJECT}/secrets/databento-api-key/versions/latest:access", timeout=30)
    response.raise_for_status()
    api_key = base64.b64decode(response.json()["payload"]["data"]).decode().strip()
    if not api_key:
        raise ValueError("Secret is empty")
    SENSITIVE_VALUES.append(api_key)
    report["secret_access"] = "verified"
    client = db.Historical(api_key)
    cost_client = SimpleNamespace(metadata=SimpleNamespace(get_cost=lambda **kw: metadata_cost(client, **kw)))
    bucket = storage.Client(project=PROJECT, credentials=credentials).bucket(BUCKET)
    contexts = []
    for preset in PRESETS:
        c = gold.config_at(gold.PRESETS[preset])
        output = work / preset
        cache = Cache(bucket, preset, output, gold)
        state = cache.restore(c)
        report["stage"] = f"estimate_{preset}"
        plan = gold.estimate(cost_client, gold.requests_for(c, "preview"), state, "preview")
        contexts.append((preset, c, output, cache, state, plan))
    report["estimates"] = {row[0]: row[5] for row in contexts}
    total = sum(row[5]["new_estimated_usd"] + row[5]["previous_reserved_estimated_usd"] for row in contexts)
    report["combined_cumulative_estimated_usd"] = total
    report["combined_max_cost_usd"] = MAX_COST
    if request["action"] == "estimate":
        return
    gold.check_budget({"new_estimated_usd": total, "previous_reserved_estimated_usd": 0}, MAX_COST)
    report["stage"] = "cash_reference"
    # Latest available daily 3-month Treasury benchmark, with next-day use.
    import requests
    cash_url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO&cosd=2026-08-27&coed=2026-09-30"
    cash_response = requests.get(cash_url, timeout=30)
    cash_response.raise_for_status()
    cash = pd.read_csv(io.StringIO(cash_response.text)).dropna(subset=["DGS3MO"])
    cash["available_at"] = pd.to_datetime(cash["observation_date"], utc=True) + pd.Timedelta(days=1)
    cash["usd_rate"] = pd.to_numeric(cash["DGS3MO"]) / 100
    if cash.empty or cash["available_at"].min() > pd.Timestamp("2026-09-01", tz="UTC") or cash["available_at"].max() < pd.Timestamp("2026-09-30", tz="UTC"):
        raise ValueError("Incomplete September cash benchmark")
    report["cash_reference"] = {"source": cash_url, "convention": "DGS3MO percent converted to decimal; latest prior observation available next UTC day; simple ACT/365 cash-yield proxy"}
    report["screens"] = {}
    outputs = []
    for preset, c, output, cache, state, plan in contexts:
        refs = request["references"][preset]
        reference = cash[["available_at", "usd_rate"]].copy()
        reference["units_per_share"] = refs["units_per_share"]
        reference["source"] = refs["source"] + "; " + cash_url
        provenance = {"mode": "snapshot_units_with_dated_cash", "units_per_share": refs["units_per_share"],
                      "source": refs["source"], "snapshot_as_of": refs["as_of"],
                      "warning": "ETF units use a constant snapshot from after the observation window; this is an indicative sensitivity screen, not a causal historical return.",
                      "cash": report["cash_reference"]}
        original_save = gold.save_json
        def durable_save(path, value):
            original_save(path, value)
            if Path(path) == output / "state.json":
                cache.checkpoint(path, value)
        gold.save_json = durable_save
        try:
            report["stage"] = f"acquire_{preset}"
            frames = gold.acquire_preview(client, plan, output, state)
        finally:
            gold.save_json = original_save
        try:
            report["stage"] = f"analyze_{preset}"
            samples, summary = gold.analyze(frames, reference, provenance, c)
        except ValueError as exc:
            # Preserve successful acquisitions and let the other market complete.
            report["screens"][preset] = {"status": "analysis_failed", "error": str(exc).replace(api_key, "[REDACTED]")}
            continue
        summary["sensitivity"] = {}
        for cash_scenario in (0, 3, 4, 5):
            adjusted = samples.copy()
            delta = cash_scenario - 100 * samples["usd_rate"]
            for column in ("long_lease_gross_pct", "long_lease_after_entry_cost_pct", "reverse_lease_boundary_pct"):
                adjusted[column] += delta
            adjusted["long_gain_to_expiry_after_entry_cost_bps"] = adjusted["long_lease_after_entry_cost_pct"] * adjusted["maturity_years"] * 100
            summary["sensitivity"][f"cash_{cash_scenario}pct"] = gold.summarize(adjusted)
        summary["break_even_cash_rate_pct"] = {
            "median": float(samples["annualized_forward_premium_pct"].median()),
            "p05": float(samples["annualized_forward_premium_pct"].quantile(.05)),
            "p95": float(samples["annualized_forward_premium_pct"].quantile(.95))}
        gold.save_json(output / "lease-summary.json", summary)
        reference.to_csv(output / "references-used.csv", index=False)
        samples.to_csv(output / "lease-samples.csv.gz", index=False)
        pd.json_normalize(summary["daily"]).to_csv(output / "lease-daily.csv", index=False)
        for name in ("lease-summary.json", "references-used.csv", "lease-samples.csv.gz", "lease-daily.csv"):
            bucket.blob(f"{PREFIX}/runs/{request['request_id']}/{preset}/{name}").upload_from_filename(output / name, if_generation_match=0)
        report["screens"][preset] = summary
        outputs.append(output)
    if len(outputs) == 2:
        try:
            report["comparison"] = gold.compare_outputs(outputs)
        except ValueError as exc:
            report["comparison_error"] = str(exc).replace(api_key, "[REDACTED]")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--research-root", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=Path("work/databento"))
    parser.add_argument("--evidence", type=Path, default=Path("databento-evidence"))
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    public_key = validate_request(request)
    report = {"request_id": request["request_id"], "action": request["action"], "source_commit": SOURCE_COMMIT}
    status = 0
    # Vendor and SDK diagnostics stay in memory; public logs contain only status.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            run(request, args.research_root, args.work, report)
            report["status"] = "completed"
        except Exception as exc:
            report["status"] = "failed"
            report["error_type"] = type(exc).__name__
            if type(exc).__name__.startswith("Bento") or isinstance(exc, ValueError):
                message = str(exc)
                for sensitive in SENSITIVE_VALUES:
                    message = message.replace(sensitive, "[REDACTED]")
                report["error_message"] = message[:1200]
            if hasattr(exc, "http_status"):
                report["http_status"] = exc.http_status
            response = getattr(exc, "response", None)
            if response is not None:
                report["http_status"] = getattr(response, "status_code", None)
            report["error_stage"] = "after_secret_access" if report.get("secret_access") else "secret_access_or_auth"
            status = 1
    encrypt_result(report, public_key, args.evidence / "result.encrypted.json")
    print(f"Bounded Databento request {request['request_id']}: {report['status']}; encrypted evidence only.")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
