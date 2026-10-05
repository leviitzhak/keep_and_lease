#!/usr/bin/env python3
"""Cost-bounded 1OZ/IAU, SIC/SLV and MBT/IBIT research. No trading dependencies."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "strategies/research-1oz-dec26-september.json"
PRESETS = {
    "gold": DEFAULT_CONFIG,
    "sic": ROOT / "strategies/research-sic-dec26-september.json",
    "mbt": ROOT / "strategies/research-mbt-oct26-september.json",
}
# Exchange quote prices are already USD per underlying unit. Multipliers apply
# to quantities and per-contract fees, never to the price ratio.
MARKETS = {
    "1OZZ6": dict(holding="IAU", units_per_contract=1.0, unit="troy_oz", month=12, asset="gold", slug="1oz"),
    "SICZ6": dict(holding="SLV", units_per_contract=100.0, unit="troy_oz", month=12, asset="silver", slug="sic"),
    "MBTV6": dict(holding="IBIT", units_per_contract=0.1, unit="BTC", month=10, asset="btc", slug="mbt"),
}


def market(c):
    symbol = c["future_symbol"]
    match = re.fullmatch(r"(1OZ|SIC|MBT)([FGHJKMNQUVXZ])([5-8])", symbol)
    if not match:
        raise ValueError("Supported contracts: dated 1OZ, SIC and MBT futures, 2025–2028")
    root, code, year = match.groups()
    template = {"1OZ": "1OZZ6", "SIC": "SICZ6", "MBT": "MBTV6"}[root]
    return {**MARKETS[template], "month": "FGHJKMNQUVXZ".index(code) + 1, "year": 2020 + int(year)}


def holding_setting(c, suffix):
    # Preserve the original gold config and raw filenames so paid caches resume.
    prefix = "iau" if market(c)["holding"] == "IAU" else "holding"
    return c[f"{prefix}_{suffix}"]


def default_output(c):
    month = utc(c["start"]).strftime("%b%Y").lower()
    return ROOT / f"outputs/databento-{market(c)['slug']}-{month}"


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
    market(c)
    for key in ("contracts", "max_reference_age_days"):
        if not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if int(c["contracts"]) != c["contracts"]:
        raise ValueError("contracts must be an integer")
    for value in (c["future_fee_usd_per_contract"], holding_setting(c, "fee_usd_per_share"), holding_setting(c, "min_fee_usd")):
        if not math.isfinite(value) or value < 0:
            raise ValueError("Entry fees must be finite and nonnegative")
    if not isinstance(holding_setting(c, "dataset"), str) or not holding_setting(c, "dataset").strip():
        raise ValueError("Holding dataset must be specified")
    return c


def requests_for(c, stage):
    common = dict(start=c["start"], end=c["end"], stype_in="raw_symbol")
    holding = market(c)["holding"]
    legs = [("future", "GLBX.MDP3", c["future_symbol"]),
            (holding.lower(), holding_setting(c, "dataset"), holding)]
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
    m = market(c)
    if args.reference_csv:
        frame = pd.read_csv(args.reference_csv)
        if "units_per_share" not in frame and "ounces_per_share" in frame and m["unit"] == "troy_oz":
            frame = frame.rename(columns={"ounces_per_share": "units_per_share"})
        required = {"available_at", "units_per_share", "usd_rate", "source"}
        if not required <= set(frame):
            raise ValueError("Reference CSV requires available_at,units_per_share,usd_rate,source (BTC per IBIT share for MBT)")
        frame["available_at"] = frame["available_at"].map(utc)
        for column in ("units_per_share", "usd_rate"):
            frame[column] = pd.to_numeric(frame[column], errors="raise")
        if (frame["source"].isna() | frame["source"].astype(str).str.strip().eq("")).any():
            raise ValueError("Reference rows require a source description")
        provenance = {"mode": "dated_reference", "sha256": digest(args.reference_csv)}
    else:
        units = args.units_per_share
        if args.iau_oz_per_share is not None:
            if c["future_symbol"] != "1OZZ6" or units is not None:
                raise ValueError("--iau-oz-per-share is only for gold; use --units-per-share for SIC/MBT")
            units = args.iau_oz_per_share
        if units is None or args.cash_rate_pct is None:
            raise ValueError("Preview needs --reference-csv, or BOTH --units-per-share and --cash-rate-pct for an explicitly indicative scenario")
        frame = pd.DataFrame([{"available_at": utc(c["start"]),
                               "units_per_share": units,
                               "usd_rate": args.cash_rate_pct / 100,
                               "source": "user-specified constant scenario, not historical observations"}])
        provenance = {"mode": "constant_scenario", "units_per_share": units,
                      "cash_rate_pct": args.cash_rate_pct}
    provenance.update(holding_symbol=m["holding"], underlying_unit=m["unit"])
    if frame.empty or frame["available_at"].duplicated().any():
        raise ValueError("Reference input is empty or has duplicate available_at timestamps")
    if not frame["units_per_share"].map(lambda x: math.isfinite(x) and 0 < x < 1).all():
        raise ValueError(f"Invalid {m['holding']} underlying units per share")
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
        raise ValueError("No definitions for requested contract")
    month, year = market(c)["month"], market(c)["year"]
    maturity = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
    label = maturity.strftime("%B %Y")
    for column, expected in (("maturity_year", year), ("maturity_month", month)):
        if column in selected and not selected[column].eq(expected).all():
            raise ValueError(f"Contract definition disagrees with {label}: {column}")
    expiry = pd.to_datetime(selected["expiration"], utc=True).dropna().unique()
    lower = maturity if market(c)["holding"] == "IBIT" else maturity - pd.offsets.MonthBegin(1)
    upper = maturity + pd.offsets.MonthBegin(1)
    if len(expiry) != 1 or not max(utc(c["end"]), lower) < expiry[0] < upper:
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
    for col in ("long_lease_gross_pct", "long_lease_after_entry_cost_pct", "reverse_lease_boundary_pct",
                "long_gain_to_expiry_after_entry_cost_bps"):
        if col not in frame:  # Older saved gold output remains comparable.
            continue
        s = frame[col]
        result[col] = {"min": float(s.min()), "p05": float(s.quantile(.05)),
                       "median": float(s.median()), "p95": float(s.quantile(.95)), "max": float(s.max())}
    net = frame["long_lease_after_entry_cost_pct"]
    result["sample_fraction_above_0pct"] = float((net > 0).mean())
    result["sample_fraction_above_2pct"] = float((net > 2).mean())
    return result


def analyze(frames, references, provenance, c):
    m = market(c)
    leg = m["holding"].lower()
    references = references.copy()
    if "units_per_share" not in references and m["unit"] == "troy_oz":
        references = references.rename(columns={"ounces_per_share": "units_per_share"})
    expiry = expiry_from_definitions(frames["future-definition"], c)
    future = quotes(frames[f"future-{c['quote_schema']}"], "future", c)
    holding = quotes(frames[f"{leg}-{c['quote_schema']}"], "holding", c)
    paired = future.merge(holding, on="timestamp", how="inner", validate="one_to_one")
    counts = {"future_samples": len(future), "holding_samples": len(holding), "matched_interval_samples": len(paired)}
    if leg == "iau":
        counts["iau_samples"] = len(holding)
    # Restrict to the ETF regular session; missing holidays yield no paired samples.
    local = paired["timestamp"].dt.tz_convert("America/New_York")
    minute = local.dt.hour * 60 + local.dt.minute
    paired = paired[(local.dt.weekday < 5) & (minute >= 570) & (minute < 960)].copy()
    counts["regular_session_samples"] = len(paired)
    paired = pd.merge_asof(paired.sort_values("timestamp"), references,
                          left_on="timestamp", right_on="available_at", direction="backward")
    valid = paired["units_per_share"].notna() & paired["usd_rate"].notna()
    if provenance["mode"] == "dated_reference":
        valid &= (paired["timestamp"] - paired["available_at"]).dt.total_seconds() <= c["max_reference_age_days"] * 86400
    for prefix in ("future", "holding"):
        bid, ask = paired[f"{prefix}_bid_px_00"], paired[f"{prefix}_ask_px_00"]
        valid &= bid.map(math.isfinite) & ask.map(math.isfinite) & (bid > 0) & (ask >= bid) & (ask < 1e6)
        valid &= (paired[f"{prefix}_bid_sz_00"] > 0) & (paired[f"{prefix}_ask_sz_00"] > 0)
    paired = paired[valid].copy()
    counts["valid_reference_and_quotes"] = len(paired)
    q = c["contracts"]
    units = q * m["units_per_contract"]
    paired["underlying_quantity"] = units
    paired["holding_shares_needed"] = (units / paired["units_per_share"]).map(math.ceil)
    enough = (paired["future_ask_sz_00"] >= q) & (paired["holding_bid_sz_00"] >= paired["holding_shares_needed"])
    paired = paired[enough].copy()
    counts["long_size_qualified_samples"] = len(paired)
    if paired.empty:
        raise ValueError(f"No size-qualified synchronized quotes: {counts}")
    t = (expiry - paired["timestamp"]).dt.total_seconds() / (365 * 86400)
    spot_bid = paired["holding_bid_px_00"] / paired["units_per_share"]
    spot_ask = paired["holding_ask_px_00"] / paired["units_per_share"]
    f_ask, f_bid = paired["future_ask_px_00"], paired["future_bid_px_00"]
    paired["maturity_years"] = t
    paired["holding_bid_usd_per_unit"] = spot_bid
    paired["holding_ask_usd_per_unit"] = spot_ask
    paired["forward_premium_pct"] = 100 * (f_ask / spot_bid - 1)
    paired["annualized_forward_premium_pct"] = paired["forward_premium_pct"] / t
    paired["long_lease_gross_pct"] = 100 * (paired["usd_rate"] - (f_ask / spot_bid - 1) / t)
    # Explicit simple ACT/365 entry-cost drag, consistent with the preview signal.
    etf_fee = (paired["holding_shares_needed"] * holding_setting(c, "fee_usd_per_share")).clip(lower=holding_setting(c, "min_fee_usd"))
    fee_per_unit = (q * c["future_fee_usd_per_contract"] + etf_fee) / units
    paired["entry_cost_usd_per_unit"] = fee_per_unit
    paired["long_lease_after_entry_cost_pct"] = paired["long_lease_gross_pct"] - 100 * fee_per_unit / spot_bid / t
    paired["long_gain_to_expiry_after_entry_cost_bps"] = paired["long_lease_after_entry_cost_pct"] * t * 100
    paired["reverse_lease_boundary_pct"] = 100 * (paired["usd_rate"] - (f_bid / spot_ask - 1) / t)
    paired["reverse_size_qualified"] = (paired["future_bid_sz_00"] >= q) & (paired["holding_ask_sz_00"] >= paired["holding_shares_needed"])
    paired["holding_rounding_residual_units"] = paired["holding_shares_needed"] * paired["units_per_share"] - units
    if leg == "iau":
        # Retain the public columns consumed by existing gold notebooks.
        for column in [x for x in paired if x.startswith("holding_")]:
            paired[column.replace("holding_", "iau_", 1).replace("_per_unit", "_per_oz").replace("_residual_units", "_residual_oz")] = paired[column]
        paired["ounces_per_share"] = paired["units_per_share"]
        paired["entry_cost_usd_per_oz"] = paired["entry_cost_usd_per_unit"]
    paired["date"] = paired["timestamp"].dt.strftime("%Y-%m-%d")
    daily = [{"date": day, **summarize(group)} for day, group in paired.groupby("date")]
    summary = {"created_at": stamp(), "classification": "sampled_quote_indication",
               "config": c, "market": m, "future_symbol": c["future_symbol"],
               "holding_symbol": m["holding"], "annualization_horizon": "definition_expiration",
               "expiry": expiry.isoformat(), "reference": provenance, "coverage": counts,
               "overall": summarize(paired), "daily": daily,
               "limitations": [
                   "Sampled bid/ask indication, not demonstrated fills or a time-to-fill backtest.",
                   "BBO ts_recv is interval end; quote age within samples is unknown. ts_event is last trade time.",
                   f"{m['holding']} quotes are from {holding_setting(c, 'dataset')}; they are venue-specific, not an NBBO guarantee.",
                   "Two venues may change prices before either leg executes; only matching interval endpoints are compared.",
                   "ETF normalized by underlying units per share retains ETF premium/discount and settlement-benchmark basis risk.",
                   "Annualization uses the vendor definition expiration; settlement cash dates and terminal ETF convergence are not modeled.",
                   "Cash yield is a supplied benchmark/scenario, not a locked return; futures margin and variation cash flows excluded.",
                   "After-entry-cost rates exclude exit costs, taxes, slippage and future ETF expense advantage.",
                   "Reverse boundary is a price comparison, not a net short-strategy return; reverse depth flag is separate.",
                   "Daily and overall quantiles are sample-weighted; missing intervals are not filled or treated as zero.",
                   "Whole ETF shares leave disclosed residual exposure; the rate covers matched underlying units only."]}
    return paired, summary


def compare_outputs(outputs):
    """Read local screens only. Compare on identical, size-qualified timestamps."""
    if len(outputs) < 2:
        raise ValueError("compare needs at least two --compare-outputs directories")
    screens, common, window = [], None, None
    for output in outputs:
        summary = json.loads((output / "lease-summary.json").read_text())
        c = summary.get("config") or json.loads((output / "state.json").read_text())["config"]
        this_window = (c["start"], c["end"], c["quote_schema"])
        if window is not None and window != this_window:
            raise ValueError("Comparison requires the same date window and quote schema")
        window = this_window
        samples = pd.read_csv(output / "lease-samples.csv.gz")
        samples["timestamp"] = pd.to_datetime(samples["timestamp"], utc=True)
        if samples["timestamp"].duplicated().any():
            raise ValueError("Comparison samples contain duplicate timestamps")
        samples["long_gain_to_expiry_after_entry_cost_bps"] = samples["long_lease_after_entry_cost_pct"] * samples["maturity_years"] * 100
        times = pd.Index(samples["timestamp"])
        common = times if common is None else common.intersection(times)
        screens.append((c, summary, samples))
    if common.empty:
        raise ValueError("No shared size-qualified timestamps for comparison")
    rows, cash_rates = [], []
    for c, summary, samples in screens:
        subset = samples.set_index("timestamp").loc[common.sort_values()]
        cash_rates.append(subset["usd_rate"].reset_index(drop=True))
        rows.append({"future_symbol": c["future_symbol"], "holding_symbol": market(c)["holding"],
                     "reference": summary["reference"], "expiry": summary["expiry"],
                     "fees": {"future_per_contract_usd": c["future_fee_usd_per_contract"],
                              "holding_per_share_usd": holding_setting(c, "fee_usd_per_share"),
                              "holding_minimum_usd": holding_setting(c, "min_fee_usd")},
                     "all_qualified_samples": summarize(samples), "common_timestamps": summarize(subset)})
    same_cash = all((rates - cash_rates[0]).abs().le(1e-12).all() for rates in cash_rates[1:])
    return {"created_at": stamp(), "start": window[0], "end": window[1], "quote_schema": window[2],
            "common_samples": len(common), "same_cash_rate_on_common_samples": bool(same_cash), "contracts": rows,
            "note": "Compare common_timestamps for candidate selection. Positive indications are not demonstrated fills. Check reference modes, cash rates, fees and settlement basis before choosing a candidate."}


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
    p.add_argument("command", choices=["estimate", "preview", "compare", "submit-mbo", "download-mbo", "upload"])
    selection = p.add_mutually_exclusive_group()
    selection.add_argument("--config", type=Path)
    selection.add_argument("--preset", choices=list(PRESETS), help="Defaults to gold; all presets use September 2026")
    p.add_argument("--output", type=Path, help="Default: separate preset output directory")
    p.add_argument("--compare-outputs", nargs="+", type=Path, help="Local preview directories for compare (no API access)")
    p.add_argument("--stage", choices=["preview", "mbo"], default="preview", help="For estimate")
    p.add_argument("--max-cost-usd", type=float, help="Cumulative estimated Databento spend ceiling for this output directory")
    p.add_argument("--reference-csv", type=Path)
    p.add_argument("--iau-oz-per-share", type=float, help="Explicit constant scenario, not historical conversion")
    p.add_argument("--units-per-share", type=float, help="Constant scenario: troy oz per IAU/SLV share or BTC per IBIT share")
    p.add_argument("--cash-rate-pct", type=float, help="Explicit constant annual cash-rate scenario, percent")
    p.add_argument("--gcs-prefix", help="Default: asset/contract/month prefix in existing market-data bucket")
    args = p.parse_args(argv)
    key = ""
    try:
        if args.command == "compare":
            report = compare_outputs(args.compare_outputs or [])
            destination = args.output or ROOT / "outputs/databento-comparison-sep2026"
            save_json(destination / "lease-comparison.json", report)
            table = [{"contract": row["future_symbol"], "ETF": row["holding_symbol"],
                      "reference": row["reference"]["mode"], "samples": report["common_samples"],
                      "median_annual_pct": row["common_timestamps"]["long_lease_after_entry_cost_pct"]["median"],
                      "p05_annual_pct": row["common_timestamps"]["long_lease_after_entry_cost_pct"]["p05"],
                      "p95_annual_pct": row["common_timestamps"]["long_lease_after_entry_cost_pct"]["p95"],
                      "positive_sample_pct": 100 * row["common_timestamps"]["sample_fraction_above_0pct"],
                      "median_term_gain_bps": row["common_timestamps"]["long_gain_to_expiry_after_entry_cost_bps"]["median"]}
                     for row in report["contracts"]]
            table = pd.DataFrame(table)
            table.to_csv(destination / "lease-comparison.csv", index=False)
            print(table.to_string(index=False))
            print(f"Same cash rates on common samples: {report['same_cash_rate_on_common_samples']}")
            print(report["note"])
            return 0
        c = config_at(args.config or PRESETS[args.preset or "gold"])
        args.output = args.output or default_output(c)
        args.gcs_prefix = args.gcs_prefix or f"gs://keep-and-lease-market-data/{market(c)['asset']}/databento/{c['future_symbol']}/{utc(c['start']):%Y-%m}"
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
