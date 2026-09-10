"""Read-only, explicitly published research benchmarks; never user job discovery."""
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from backtest_audit import load_manifest, read_chunk
from replay_checkpoints import decode

BUCKET = "keep-and-lease-market-data"
MANIFEST = "52ef7ab51def1e37fc774f96bd94697ed90ad286d6885c72f69de84c285c9912"
RUNS = {"sequence": "d7afa21dd9da7d3b1b4ab15efe639ed4",
        "timestamp": "e2e5ea42cb21f82926deb6d0ef9a3877"}
FIELDS = ["date", "nav", "direct_nav", "cash_usd", "spot_value_usd",
          "futures_notional_usd", "fees_usd", "max_mark_age_seconds"]


def parameters(policy):
    payload = json.loads(Path(__file__).with_name("benchmark_parameters.json").read_text())["parameters"]
    payload.update(trade_ordering=policy, backtest_start="2026-06-06T00:00:00.000000",
                   backtest_end="2026-09-04T00:00:00.000000", execution_interval_seconds=0.5)
    return payload


def catalog():
    return [dict(job_id="benchmark-" + policy, title="90-day BTC benchmark · " + policy,
                 status="completed", is_benchmark=True, created_at=1788979260,
                 parameters=parameters(policy), detail="Completed research benchmark · zero-cost baseline",
                 result_url=f"/api/v1/benchmarks/{policy}/result") for policy in RUNS]


class BenchmarkService:
    def __init__(self, bucket):
        self.bucket = bucket

    def read(self, name, limit=32 * 1024 * 1024):
        blob = self.bucket.blob(name)
        blob.reload()
        if blob.size > limit:
            raise ValueError("Benchmark object exceeds its read limit")
        return blob.download_as_bytes(if_generation_match=blob.generation, checksum="crc32c")

    def audit_store(self, policy):
        from .cloud import GcsResultStore
        if policy not in RUNS:
            raise KeyError(policy)
        results = GcsResultStore.__new__(GcsResultStore)
        results.bucket = self.bucket
        return results.audit_store(RUNS[policy])

    @lru_cache(maxsize=2)
    def load(self, policy):
        if policy not in RUNS:
            raise KeyError(policy)
        prefix = f"jobs/{RUNS[policy]}"
        report = json.loads(self.read(prefix + "/benchmark-report.json"))
        payload = parameters(policy)
        digest = hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != "trade_ordering"}, sort_keys=True).encode()).hexdigest()
        if (report["manifest_sha256"] != MANIFEST or report["ordering"] != policy or
                report["days"] != 90 or report["interval_seconds"] != .5 or
                report["strategy_parameters_sha256"] != digest):
            raise ValueError("Benchmark report does not match the published dataset and parameters")
        store = self.audit_store(policy)
        manifest = load_manifest(store)
        if manifest["provenance"]["trade_data"]["manifest_sha256"] != MANIFEST:
            raise ValueError("Benchmark audit dataset differs from its report")
        # Completed replay checkpoints intentionally stop before the final hour.
        # Restore chart samples only, then read the handful of remaining audit chunks.
        end = datetime.fromisoformat(report["summary"]["end"])
        last_hour = end.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        tick = int((last_hour - datetime(1970, 1, 1)).total_seconds() * 1e6)
        checkpoint = decode(self.read(prefix + f"/checkpoints/{tick:020d}.json.gz", 16 * 1024 * 1024))
        if checkpoint["identity"] != report["fingerprint"] or checkpoint["source_cursor_exclusive_us"] != tick:
            raise ValueError("Benchmark chart checkpoint differs from its completed report")
        series = deepcopy(checkpoint["state"]["series"])
        every = report["replay"]["plot_sample_every"]
        capital = report["replay"]["capital_usd"]
        entries = manifest["datasets"]["btc_trade_valuations"]["chunks"]
        if manifest["datasets"]["btc_trade_valuations"]["rows"] != report["summary"]["observations"]:
            raise ValueError("Benchmark valuation count differs from its report")
        for entry in entries:
            if entry["end"] <= last_hour.isoformat(timespec="microseconds"):
                continue
            # Exhaust the chunk to validate its checksum before using its rows.
            for offset, row in enumerate(list(read_chunk(store, entry))):
                if row["us"] <= tick:
                    continue
                if (entry["first_row"] + offset + 1) % every and row["date"] != report["summary"]["end"]:
                    continue
                ages = [(row["us"] - row["mark_us"][s]) / 1e6 for s, q in row["units"].items() if q > 0]
                series.append([row["date"], row["nav_usd"] / capital, row["direct_nav"], row["cash_usd"],
                               row["nav_usd"] - row["cash_usd"], row["futures_notional_usd"],
                               row["fees_usd"], max(ages, default=0)])
        if not series or series[-1][0] != report["summary"]["end"] or abs(series[-1][1] - report["summary"]["ending_nav"]) > 1e-10:
            raise ValueError("Benchmark chart endpoint does not reconcile with the completed result")
        base = f"/api/v1/benchmarks/{policy}"
        result = dict(result_kind="btc_trade_replay", parameters=payload, fields=FIELDS, series=series,
                      summary=report["summary"], trade_replay=report["replay"],
                      backtest_period=dict(actual_start=report["summary"]["start"], actual_end=report["summary"]["end"],
                                           requested_start=payload["backtest_start"], requested_end=payload["backtest_end"]),
                      audit={"base_url": base + "/audit"},
                      benchmark={"policy": policy, "source_job_id": RUNS[policy], "report_uri": f"gs://{BUCKET}/{prefix}/benchmark-report.json"})
        return result, manifest
