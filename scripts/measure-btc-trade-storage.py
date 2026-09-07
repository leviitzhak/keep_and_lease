#!/usr/bin/env python3
"""Measure public spot trade archive sizes without downloading the archives."""
import argparse
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

SOURCE = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}


def listing(prefix):
    token = None
    while True:
        params = {"list-type": 2, "prefix": prefix, "max-keys": 1000}
        if token:
            params["continuation-token"] = token
        with urllib.request.urlopen(SOURCE + "?" + urllib.parse.urlencode(params), timeout=90) as response:
            root = ET.fromstring(response.read())
        for item in root.findall("s:Contents", NS):
            key = item.find("s:Key", NS).text
            if key.endswith(".zip"):
                yield {"key": key, "bytes": int(item.find("s:Size", NS).text)}
        if root.find("s:IsTruncated", NS).text == "false":
            break
        token = root.find("s:NextContinuationToken", NS).text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="2026-09-07", help="History exclusive end date")
    parser.add_argument("--start", default="2026-06-06")
    parser.add_argument("--end", default="2026-09-04", help="Comparison exclusive end date")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cutoff = date.fromisoformat(args.as_of)
    months = [x for x in listing("data/spot/monthly/trades/BTCUSDT/")
              if x["key"][-11:-4] < args.as_of[:7]]
    if not months:
        raise ValueError("No monthly archive history")
    last_month = date.fromisoformat(max(x["key"][-11:-4] for x in months) + "-01")
    after = (last_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    years = range(min(after.year, date.fromisoformat(args.start).year), cutoff.year + 1)
    daily = [x for year in years for x in listing(f"data/spot/daily/trades/BTCUSDT/BTCUSDT-trades-{year}-")]
    pick = lambda lo, hi: [x for x in daily if lo <= x["key"][-14:-4] < hi]
    ninety, rest = pick(args.start, args.end), pick(after.isoformat(), args.as_of)
    if len(ninety) != (date.fromisoformat(args.end) - date.fromisoformat(args.start)).days:
        raise ValueError("Comparison archive days missing")
    if len(rest) != (cutoff - after).days:
        raise ValueError("Recent history archive days missing")
    total = lambda items: sum(x["bytes"] for x in items)
    report = dict(checked_date=date.today().isoformat(), unit="bytes", source=SOURCE,
                  scope="BTCUSDT raw spot trade ZIPs only; no order books, futures or redundant daily/monthly copies",
                  ninety_days=dict(start=args.start, end_exclusive=args.end, files=len(ninety), bytes=total(ninety)),
                  history=dict(start_month=min(x["key"][-11:-4] for x in months), end_exclusive=args.as_of,
                               monthly_files=len(months), daily_files=len(rest), bytes=total(months + rest)),
                  files=months + daily)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    main()
