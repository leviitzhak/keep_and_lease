#!/usr/bin/env python3
"""Repair bundled futures archives and refresh public benchmark/fund CSVs.

The legacy TurtleTrader archives contain headerless rows:
date,open,high,low,close,volume,open_interest.  The gold archive checked into
the source repository lost its central directory and ends part-way through a
contract.  Complete local members can still be recovered deterministically.

Yahoo's public chart endpoint is used only for cash/continuous benchmarks and
listed funds.  It is not presented as a replacement for individual expired
futures contracts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import struct
import time
import urllib.parse
import urllib.request
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
DATA = PUBLIC / "data"
USER_AGENT = "Mozilla/5.0 (compatible; KeepAndLeaseDataRefresh/1.0)"
TURTLETRADER_GOLD_URL = "https://www.turtletrader.com/cddata/gc.zip"

SERIES = {
    "silver/spot.csv": "SI=F",
    "silver/fund.csv": "SLV",
    "gold/spot.csv": "GC=F",
    "gold/fund.csv": "IAU",
    "sp500/spot.csv": "^GSPC",
    "sp500/fund.csv": "SPY",
    "treasuries/fund.csv": "SHY",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def recover_local_zip_members(source: Path) -> dict[str, bytes]:
    """Recover complete deflated/stored members without a central directory."""
    payload = source.read_bytes()
    offset = 0
    recovered: dict[str, bytes] = {}
    while offset + 30 <= len(payload) and payload[offset:offset + 4] == b"PK\x03\x04":
        (
            _signature, _version, flags, method, _mtime, _mdate,
            _crc, compressed_size, uncompressed_size, name_length, extra_length,
        ) = struct.unpack_from("<IHHHHHIIIHH", payload, offset)
        if flags & 0x08:
            raise ValueError("data-descriptor ZIP members are not supported")
        name_start = offset + 30
        body_start = name_start + name_length + extra_length
        body_end = body_start + compressed_size
        if body_end > len(payload):
            break
        name = payload[name_start:name_start + name_length].decode("utf-8")
        compressed = payload[body_start:body_end]
        try:
            if method == 8:
                body = zlib.decompress(compressed, -15)
            elif method == 0:
                body = compressed
            else:
                raise ValueError(f"unsupported ZIP compression method {method}")
        except zlib.error:
            break
        if len(body) != uncompressed_size:
            break
        recovered[name] = body
        offset = body_end
    return recovered


def materialize_contracts(members: dict[str, bytes], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.csv"):
        old.unlink()
    for name, body in members.items():
        target = directory / f"{Path(name).stem.upper()}.csv"
        target.write_bytes(body)


def repair_gold() -> dict[str, object]:
    source = PUBLIC / "gc.zip"
    request = urllib.request.Request(
        TURTLETRADER_GOLD_URL, headers={"User-Agent": USER_AGENT})
    downloaded = source.with_suffix(".download.zip")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            downloaded.write_bytes(response.read())
        with zipfile.ZipFile(downloaded) as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError(f"downloaded gold archive failed at {bad}")
            members = {
                name: archive.read(name) for name in archive.namelist()
                if name.lower().endswith(".txt")
            }
        downloaded.replace(source)
        materialize_contracts(members, DATA / "gold" / "futures")
        return {
            "source": TURTLETRADER_GOLD_URL,
            "contracts_downloaded": len(members),
            "first_contract": next(iter(members)),
            "last_contract": next(reversed(members)),
            "archive_sha256": sha256(source),
        }
    except Exception:
        downloaded.unlink(missing_ok=True)

    # Offline fallback: retain every complete member that survived locally.
    members = recover_local_zip_members(source)
    if not members:
        raise RuntimeError("no complete gold contracts could be recovered")
    repaired = PUBLIC / "gc.repaired.zip"
    with zipfile.ZipFile(repaired, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    with zipfile.ZipFile(repaired) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"repaired gold archive failed at {bad}")
    source.replace(PUBLIC / "gc.corrupted.zip")
    repaired.replace(source)
    (PUBLIC / "gc.corrupted.zip").unlink()
    materialize_contracts(members, DATA / "gold" / "futures")
    return {
        "contracts_recovered": len(members),
        "first_contract": next(iter(members)),
        "last_contract": next(reversed(members)),
        "archive_sha256": sha256(source),
    }


def yahoo_chart(symbol: str) -> list[dict[str, object]]:
    encoded = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{encoded}"
        "?period1=0&period2=2000000000&interval=1d&events=div%2Csplits"
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.load(response)["chart"]["result"][0]
    timestamps = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    adjusted = (result["indicators"].get("adjclose") or [{}])[0].get(
        "adjclose", [None] * len(timestamps))
    rows = []
    for index, timestamp in enumerate(timestamps):
        close = quote["close"][index]
        if close is None:
            continue
        rows.append({
            "date": datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat(),
            "open": quote["open"][index],
            "high": quote["high"][index],
            "low": quote["low"][index],
            "close": close,
            "adjusted_close": adjusted[index] if index < len(adjusted) else None,
            "volume": quote["volume"][index],
        })
    return rows


def write_series(relative_path: str, symbol: str) -> dict[str, object]:
    target = DATA / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = yahoo_chart(symbol)
    if not rows:
        raise RuntimeError(f"{symbol} returned no observations")
    with target.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return {
        "symbol": symbol,
        "observations": len(rows),
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "sha256": sha256(target),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-gold-repair", action="store_true")
    args = parser.parse_args()
    manifest: dict[str, object] = {
        "refreshed_at_utc": datetime.now(timezone.utc).isoformat(),
        "series": {},
    }
    corrupted = PUBLIC / "gc.corrupted.zip"
    if not args.skip_gold_repair and not corrupted.exists():
        manifest["gold_repair"] = repair_gold()
    elif (PUBLIC / "gc.zip").exists():
        with zipfile.ZipFile(PUBLIC / "gc.zip") as archive:
            manifest["gold_repair"] = {
                "contracts_recovered": len(archive.namelist()),
                "archive_sha256": sha256(PUBLIC / "gc.zip"),
                "already_repaired": True,
            }
    for relative_path, symbol in SERIES.items():
        manifest["series"][relative_path] = write_series(relative_path, symbol)
        time.sleep(0.35)
    manifest_path = DATA / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
