#!/usr/bin/env python3
"""Cost-bounded 1OZ/IAU historical research. No trading or GUI dependencies."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "strategies/research-1oz-dec26-september.json"


def stamp():
    return datetime.now(timezone.utc).isoformat()


def utc(value):
    result = pd.Timestamp(value)
    if result.tzinfo is None:
        raise ValueError(f"Timestamp must include timezone: {value}")
    return result.tz_convert("UTC")


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, allow_nan=False, default=str) + "\n")
    temp.replace(path)


def config_at(path):
    c = json.loads(Path(path).read_text())
    start, end = utc(c["start"]), utc(c["end"])
    if not start < end or start != start.normalize() or end != end.normalize():
        raise ValueError("Use increasing UTC midnight boundaries; end is exclusive")
    if c["quote_schema"] not in ("bbo-1m", "bbo-1s"):
        raise ValueError("Preview supports bbo-1m or bbo-1s")
    if c["future_symbol"] != "1OZZ6":
        raise ValueError("This preset workflow validates December 2026 1OZ only")
    for key in ("contracts", "max_reference_age_days"):
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if int(c["contracts"]) != c["contracts"]:
        raise ValueError("contracts must be an integer")
    for key in ("future_fee_usd_per_contract", "iau_fee_usd_per_share", "iau_min_fee_usd"):
        if not math.isfinite(c[key]) or c[key] < 0:
            raise ValueError(f"{key} must be finite and nonnegative")
    return c


def requests_for(c, stage):
    common = dict(start=c["start"], end=c["end"], stype_in="raw_symbol")
    legs = [("future", "GLBX.MDP3", c["future_symbol"]),
            ("iau", c["iau_dataset"], "IAU")]
    schema = c["quote_schema"] if stage == "preview" else "mbo"
    result = [{"name": f"{leg}-{schema}", "request": dict(
        common, dataset=dataset, symbols=[symbol], schema=schema)}
        for leg, dataset, symbol in legs]
    # Keep definitions for both legs and the full period, including instrument IDs.
    result += [{"name": f"{leg}-definition", "request": dict(
        common, dataset=dataset, symbols=[symbol], schema="definition")}
        for leg, dataset, symbol in legs]
    return result


def state_at(output, c):
    path = output / "state.json"
    if path.exists():
        state = json.loads(path.read_text())
        if state["config"] != c:
            raise ValueError("Output belongs to a different configuration; use a new --output")
    else:
        state = {"version": 1, "created_at": stamp(), "config": c,
                 "reserved_estimated_usd": 0.0, "streams": {}, "batches": {}}
    return state


def api_client():
    import databento as db
    key = os.environ.get("DATABENTO_API_KEY")
    if not key:
        if not sys.stdin.isatty():
            raise ValueError("Set DATABENTO_API_KEY in this noninteractive environment")
        key = getpass.getpass("Databento API key (hidden): ").strip()
    if not key:
        raise ValueError("An API key is required")
    return db.Historical(key), key


def estimate(client, items, state, stage):
    rows = []
    for item in items:
        name, request = item["name"], item["request"]
        previous = state["streams" if stage == "preview" else "batches"].get(name)
        if previous:
            rows.append({**item, "estimated_usd": 0.0, "existing_status": previous["status"]})
            continue
        # get_cost is metadata only: it does not download market records.
        cost = float(client.metadata.get_cost(**request))
        if not math.isfinite(cost) or cost < 0:
            raise ValueError("Invalid Databento estimate")
        rows.append({**item, "estimated_usd": cost})
    return {"created_at": stamp(), "stage": stage, "requests": rows,
            "new_estimated_usd": sum(x["estimated_usd"] for x in rows),
            "previous_reserved_estimated_usd": state["reserved_estimated_usd"],
            "note": "Estimates are not credit balances or invoice totals. Check remaining credits in the portal."}


def check_budget(plan, maximum):
    if maximum is None or not math.isfinite(maximum) or maximum < 0:
        raise ValueError("Downloads require a finite --max-cost-usd equal to your remaining authorized allowance")
    total = plan["new_estimated_usd"] + plan["previous_reserved_estimated_usd"]
    if total > maximum + 1e-9:
        raise ValueError(f"Cumulative estimate ${total:.6f} exceeds --max-cost-usd ${maximum:.6f}")


def acquire_preview(client, plan, output, state):
    import databento as db
    frames = {}
    for row in plan["requests"]:
        name = row["name"]
        path = output / "raw" / f"{name}.dbn.zst"
        old = state["streams"].get(name)
        if old:
            if old["status"] != "done":
                raise ValueError(f"Uncertain previous request {name}; inspect state before retrying to avoid rebilling")
            if not path.exists() or digest(path) != old["sha256"]:
                raise ValueError(f"Missing or corrupted cached {name}; no automatic charged re-download")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = path.with_suffix(".partial")
            state["streams"][name] = {"status": "inflight", "request": row["request"],
                                       "estimated_usd": row["estimated_usd"]}
            state["reserved_estimated_usd"] += row["estimated_usd"]
            save_json(output / "state.json", state)
            client.timeseries.get_range(**row["request"], path=partial)
            partial.replace(path)
            state["streams"][name].update(status="done", sha256=digest(path))
            save_json(output / "state.json", state)
        frames[name] = db.DBNStore.from_file(path).to_df()
    return frames


def reference_data(args, c):
    if args.reference_csv:
        frame = pd.read_csv(args.reference_csv)
        required = {"available_at", "ounces_per_share", "usd_rate", "source"}
        if not required <= set(frame):
            raise ValueError("Reference CSV requires available_at,ounces_per_share,usd_rate,source")
        frame["available_at"] = frame["available_at"].map(utc)
        for column in ("ounces_per_share", "usd_rate"):
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        if (frame["source"].isna() | frame["source"].astype(str).str.strip().eq("")).any():
            raise ValueError("Reference rows require a source description")
        provenance = {"mode": "dated_reference", "sha256": digest(args.reference_csv)}
    else:
        if args.iau_oz_per_share is None or args.cash_rate_pct is None:
            raise ValueError("Preview needs --reference-csv, or BOTH --iau-oz-per-share and --cash-rate-pct for an explicitly indicative scenario")
        frame = pd.DataFrame([{"available_at": utc(c["start"]),
                               "ounces_per_share": args.iau_oz_per_share,
                               "usd_rate": args.cash_rate_pct / 100,
                               "source": "user-specified constant scenario, not historical observations"}])
        provenance = {"mode": "constant_scenario", "iau_oz_per_share": args.iau_oz_per_share,
                      "cash_rate_pct": args.cash_rate_pct}
    if frame.empty or frame["available_at"].duplicated().any():
        raise ValueError("Reference input is empty or has duplicate available_at timestamps")
    if not frame["ounces_per_share"].map(lambda x: math.isfinite(x) and 0 < x < 1).all():
        raise ValueError("Invalid IAU ounces per share")
    if not frame["usd_rate"].map(lambda x: math.isfinite(x) and -0.1 < x < 1).all():
        raise ValueError("usd_rate must be a decimal annual rate, e.g. 0.04 for 4%")
    frame = frame.sort_values("available_at")
    if not (frame["available_at"] <= utc(c["start"])).any():
        raise ValueError("Reference input must include a value available by the start of the window")
    return frame, provenance


def expiry_from_definitions(frame, c):
    if "raw_symbol" not in frame or "expiration" not in frame:
        raise ValueError("Definitions missing raw_symbol or expiration")
    selected = frame[frame["raw_symbol"].eq(c["future_symbol"])]
    if selected.empty:
        raise ValueError("No definitions for requested December contract")
    for column, expected in (("maturity_year", 2026), ("maturity_month", 12)):
        if column in selected and not selected[column].eq(expected).all():
            raise ValueError(f"Contract definition disagrees with December 2026: {column}")
    expiry = pd.to_datetime(selected["expiration"], utc=True).dropna().unique()
    if len(expiry) != 1 or not utc(c["end"]) < expiry[0] < pd.Timestamp("2027-01-01", tz="UTC"):
        raise ValueError("Missing, conflicting or implausible expiry; inspect the definitions")
    return pd.Timestamp(expiry[0])


def quotes(frame, prefix, c):
    frame = frame.reset_index()
    if "ts_recv" not in frame:
        raise ValueError("BBO requires ts_recv interval-end timestamps; ts_event is last trade time")
    required = ["bid_px_00", "ask_px_00", "bid_sz_00", "ask_sz_00"]
    if not set(required) <= set(frame):
        raise ValueError("Quote data missing BBO prices or sizes")
    frame["timestamp"] = pd.to_datetime(frame["ts_recv"], utc=True)
    frame = frame[(frame["timestamp"] >= utc(c["start"])) & (frame["timestamp"] < utc(c["end"]))]
    if frame["instrument_id"].nunique() != 1:
        raise ValueError(f"Expected one instrument in {prefix} quotes")
    frame = frame[["timestamp", *required]].copy()
    # Exact duplicates are harmless; conflicting samples at one interval are ambiguous.
    frame = frame.drop_duplicates()
    if frame["timestamp"].duplicated().any():
        raise ValueError(f"Conflicting {prefix} quotes at the same interval end")
    return frame.rename(columns={column: f"{prefix}_{column}" for column in required})


def summarize(frame):
    result = {"samples": len(frame)}
    for col in ("long_lease_gross_pct", "long_lease_after_entry_cost_pct", "reverse_lease_boundary_pct"):
        s = frame[col]
        result[col] = {"min": float(s.min()), "p05": float(s.quantile(.05)),
                       "median": float(s.median()), "p95": float(s.quantile(.95)), "max": float(s.max())}
    net = frame["long_lease_after_entry_cost_pct"]
    result["sample_fraction_above_0pct"] = float((net > 0).mean())
    result["sample_fraction_above_2pct"] = float((net > 2).mean())
    return result


def analyze(frames, references, provenance, c):
    expiry = expiry_from_definitions(frames["future-definition"], c)
    future = quotes(frames[f"future-{c['quote_schema']}"], "future", c)
    iau = quotes(frames[f"iau-{c['quote_schema']}"], "iau", c)
    paired = future.merge(iau, on="timestamp", how="inner", validate="one_to_one")
    counts = {"future_samples": len(future), "iau_samples": len(iau), "matched_interval_samples": len(paired)}
    # Restrict to the ETF regular session; missing holidays yield no paired samples.
    local = paired["timestamp"].dt.tz_convert("America/New_York")
    minute = local.dt.hour * 60 + local.dt.minute
    paired = paired[(local.dt.weekday < 5) & (minute >= 570) & (minute < 960)].copy()
    counts["regular_session_samples"] = len(paired)
    paired = pd.merge_asof(paired.sort_values("timestamp"), references,
                          left_on="timestamp", right_on="available_at", direction="backward")
    valid = paired["ounces_per_share"].notna() & paired["usd_rate"].notna()
    if provenance["mode"] == "dated_reference":
        valid &= (paired["timestamp"] - paired["available_at"]).dt.total_seconds() <= c["max_reference_age_days"] * 86400
    for leg in ("future", "iau"):
        bid, ask = paired[f"{leg}_bid_px_00"], paired[f"{leg}_ask_px_00"]
        valid &= bid.map(math.isfinite) & ask.map(math.isfinite) & (bid > 0) & (ask >= bid) & (ask < 1e6)
        valid &= (paired[f"{leg}_bid_sz_00"] > 0) & (paired[f"{leg}_ask_sz_00"] > 0)
    paired = paired[valid].copy()
    counts["valid_reference_and_quotes"] = len(paired)
    q = c["contracts"]
    paired["iau_shares_needed"] = (q / paired["ounces_per_share"]).map(math.ceil)
    enough = (paired["future_ask_sz_00"] >= q) & (paired["iau_bid_sz_00"] >= paired["iau_shares_needed"])
    paired = paired[enough].copy()
    counts["long_size_qualified_samples"] = len(paired)
    if paired.empty:
        raise ValueError(f"No size-qualified synchronized quotes: {counts}")
    t = (expiry - paired["timestamp"]).dt.total_seconds() / (365 * 86400)
    spot_bid = paired["iau_bid_px_00"] / paired["ounces_per_share"]
    spot_ask = paired["iau_ask_px_00"] / paired["ounces_per_share"]
    f_ask, f_bid = paired["future_ask_px_00"], paired["future_bid_px_00"]
    paired["maturity_years"] = t
    paired["iau_bid_usd_per_oz"] = spot_bid
    paired["iau_ask_usd_per_oz"] = spot_ask
    paired["long_lease_gross_pct"] = 100 * (paired["usd_rate"] - (f_ask / spot_bid - 1) / t)
    # Explicit simple ACT/365 entry-cost drag, consistent with the preview signal.
    etf_fee = (paired["iau_shares_needed"] * c["iau_fee_usd_per_share"]).clip(lower=c["iau_min_fee_usd"])
    fee_per_oz = c["future_fee_usd_per_contract"] + etf_fee / q
    paired["entry_cost_usd_per_oz"] = fee_per_oz
    paired["long_lease_after_entry_cost_pct"] = paired["long_lease_gross_pct"] - 100 * fee_per_oz / spot_bid / t
    paired["reverse_lease_boundary_pct"] = 100 * (paired["usd_rate"] - (f_bid / spot_ask - 1) / t)
    paired["reverse_size_qualified"] = (paired["future_bid_sz_00"] >= q) & (paired["iau_ask_sz_00"] >= paired["iau_shares_needed"])
    paired["iau_rounding_residual_oz"] = paired["iau_shares_needed"] * paired["ounces_per_share"] - q
    paired["date"] = paired["timestamp"].dt.strftime("%Y-%m-%d")
    daily = [{"date": day, **summarize(group)} for day, group in paired.groupby("date")]
    summary = {"created_at": stamp(), "classification": "sampled_quote_indication",
               "expiry": expiry.isoformat(), "reference": provenance, "coverage": counts,
               "overall": summarize(paired), "daily": daily,
               "limitations": [
                   "Sampled bid/ask indication, not demonstrated fills or a time-to-fill backtest.",
                   "BBO ts_recv is interval end; quote age within samples is unknown. ts_event is last trade time.",
                   f"IAU quotes are from {c['iau_dataset']}; they are venue-specific, not an NBBO guarantee.",
                   "Two venues may change prices before either leg executes; only matching interval endpoints are compared.",
                   "IAU normalized by gold ounces per share retains ETF premium/discount and basis risk.",
                   "Cash yield is a supplied benchmark/scenario, not a locked return; futures margin and variation cash flows excluded.",
                   "After-entry-cost rates exclude exit costs, taxes, slippage and future ETF expense advantage.",
                   "Reverse boundary is a price comparison, not a net short-strategy return; reverse depth flag is separate.",
                   "Daily and overall quantiles are sample-weighted; missing intervals are not filled or treated as zero.",
                   "Whole ETF shares leave a disclosed small residual gold exposure."]}
    return paired, summary


def submit_mbo(client, plan, output, state):
    for row in plan["requests"]:
        name = row["name"]
        if name in state["batches"]:
            if not state["batches"][name].get("job_id"):
                raise ValueError(f"Submission {name} has uncertain outcome; reconcile Download center before retrying")
            continue
        state["batches"][name] = {"status": "submitting", "request": row["request"], "estimated_usd": row["estimated_usd"]}
        state["reserved_estimated_usd"] += row["estimated_usd"]
        save_json(output / "state.json", state)
        job = client.batch.submit_job(**row["request"], encoding="dbn", compression="zstd", split_duration="day")
        state["batches"][name].update(status="submitted", job_id=job["id"])
        save_json(output / "state.json", state)
        print(f"{name}: {job['id']}")


def download_mbo(client, output, state):
    jobs = {j["id"]: j for j in client.batch.list_jobs(states="queued,processing,done,expired")}
    if not state["batches"]:
        raise ValueError("No MBO jobs submitted in this output directory")
    pending = False
    for name, saved in state["batches"].items():
        job_id = saved.get("job_id")
        if not job_id:
            raise ValueError(f"Uncertain submission {name}; reconcile Download center")
        job = jobs.get(job_id)
        if not job or job["state"] != "done":
            print(f"{name}: {job['state'] if job else 'not returned; check Download center'}")
            pending = True
            continue
        completed = saved.setdefault("files", {})
        for info in client.batch.list_files(job_id):
            filename = info["filename"]
            # Never accept vendor paths outside the selected job directory.
            if Path(filename).name != filename:
                raise ValueError("Unexpected batch filename")
            target = output / "batch" / job_id / filename
            if filename in completed and target.exists() and digest(target) == completed[filename]["sha256"]:
                continue
            client.batch.download(job_id=job_id, output_dir=output / "batch", filename_to_download=filename)
            if not target.exists():
                raise ValueError(f"Expected batch file not found: {filename}")
            vendor_hash = info.get("hash", "").removeprefix("sha256:")
            checksum = digest(target)
            if len(vendor_hash) != 64 or vendor_hash.lower() != checksum:
                raise ValueError(f"Vendor checksum mismatch: {filename}")
            if target.stat().st_size != info["size"]:
                raise ValueError(f"Vendor size mismatch: {filename}")
            completed[filename] = {"sha256": checksum, "bytes": target.stat().st_size}
            save_json(output / "state.json", state)
        saved["status"] = "downloaded"
        save_json(output / "state.json", state)
    return pending


def upload(output, destination):
    if not destination.startswith("gs://") or not destination[5:].strip("/"):
        raise ValueError("--gcs-prefix must be a gs:// bucket and prefix")
    # The output contains only generated research data/manifests, never credentials.
    files = [{"path": str(p.relative_to(output)), "bytes": p.stat().st_size, "sha256": digest(p)}
             for p in sorted(output.rglob("*")) if p.is_file() and p.name != "manifest.json" and not p.name.endswith((".tmp", ".partial"))]
    save_json(output / "manifest.json", {"created_at": stamp(), "files": files})
    subprocess.run(["gcloud", "storage", "rsync", "--recursive", "--exclude=.*\\.(tmp|partial)$", str(output), destination], check=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["estimate", "preview", "submit-mbo", "download-mbo", "upload"])
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--output", type=Path, default=ROOT / "outputs/databento-1oz-sep2026")
    p.add_argument("--stage", choices=["preview", "mbo"], default="preview", help="For estimate")
    p.add_argument("--max-cost-usd", type=float, help="Cumulative estimated Databento spend ceiling for this output directory")
    p.add_argument("--reference-csv", type=Path)
    p.add_argument("--iau-oz-per-share", type=float, help="Explicit constant scenario, not historical conversion")
    p.add_argument("--cash-rate-pct", type=float, help="Explicit constant annual cash-rate scenario, percent")
    p.add_argument("--gcs-prefix", default="gs://keep-and-lease-market-data/gold/databento/1OZZ6/2026-09")
    args = p.parse_args(argv)
    key = ""
    try:
        c = config_at(args.config)
        args.output.mkdir(parents=True, exist_ok=True)
        state = state_at(args.output, c)
        if args.command == "upload":
            if not (args.output / "state.json").exists():
                raise ValueError("No acquisition state in output directory")
            upload(args.output, args.gcs_prefix)
            return 0
        if args.command == "preview":
            references, provenance = reference_data(args, c)
        client, key = api_client()
        if args.command == "download-mbo":
            pending = download_mbo(client, args.output, state)
            print("Jobs still pending; rerun download-mbo later." if pending else "Downloads complete. Run upload to save to GCS.")
            return 2 if pending else 0
        stage = "mbo" if args.command == "submit-mbo" else args.stage if args.command == "estimate" else "preview"
        plan = estimate(client, requests_for(c, stage), state, stage)
        save_json(args.output / f"{stage}-estimate.json", plan)
        print(json.dumps(plan, indent=2))
        if args.command == "estimate":
            return 0
        check_budget(plan, args.max_cost_usd)
        if args.command == "submit-mbo":
            submit_mbo(client, plan, args.output, state)
        else:
            frames = acquire_preview(client, plan, args.output, state)
            samples, summary = analyze(frames, references, provenance, c)
            references.to_csv(args.output / "references-used.csv", index=False)
            samples.to_csv(args.output / "lease-samples.csv.gz", index=False)
            pd.json_normalize(summary["daily"]).to_csv(args.output / "lease-daily.csv", index=False)
            save_json(args.output / "lease-summary.json", summary)
            print(json.dumps({"classification": summary["classification"], "overall": summary["overall"], "coverage": summary["coverage"]}, indent=2))
        return 0
    except Exception as exc:
        message = str(exc)
        if key:
            message = message.replace(key, "[REDACTED]")
        print(f"Error: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
