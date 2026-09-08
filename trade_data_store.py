"""Immutable Parquet trade datasets; lossless source numbers, bounded replay I/O."""
import csv
import gzip
import hashlib
import heapq
import io
import json
import resource
import re
import time
import zipfile
from itertools import chain
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path

from trade_replay import Trade

VERSION = 1
ENGINE_COLUMNS = ["timestamp_us", "symbol", "price", "native_quantity",
                  "quantity_currency", "side", "trade_id", "flags"]


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def schema():
    import pyarrow as pa
    return pa.schema([
        ("timestamp_us", pa.int64()), ("precision_us", pa.int32()),
        ("symbol", pa.string()), ("source_symbol", pa.string()),
        ("price", pa.decimal128(38, 12)), ("native_quantity", pa.decimal128(38, 12)),
        ("quantity_currency", pa.string()), ("quote_currency", pa.string()),
        ("side", pa.string()), ("trade_id", pa.string()),
        ("source_sequence", pa.int64()), ("flags", pa.uint8()),
        ("source_file", pa.string()),
    ], metadata={b"trade_schema_version": b"1", b"flags": b"1=block,2=block_rfq,4=combo"})


def spot_records(path):
    with zipfile.ZipFile(path) as archive:
        name, = archive.namelist()
        with archive.open(name) as raw:
            for row in csv.reader(io.TextIOWrapper(raw)):
                timestamp = int(row[4])
                precision = 1000 if timestamp < 10 ** 14 else 1
                yield dict(timestamp_us=timestamp * precision, precision_us=precision,
                           symbol="SPOT", source_symbol="BTCUSDT", price=Decimal(row[1]),
                           native_quantity=Decimal(row[2]), quantity_currency="BTC", quote_currency="USDT",
                           side="sell" if row[5].lower() == "true" else "buy", trade_id=row[0],
                           source_sequence=int(row[0]), flags=0, source_file=Path(path).name)


def future_records(symbol, path):
    with gzip.open(path, "rt") as stream:
        for line in stream:
            row = json.loads(line, parse_float=Decimal)
            flags = sum(1 << i for i, key in enumerate(("block_trade_id", "block_rfq_id", "combo_id"))
                        if row.get(key))
            yield dict(timestamp_us=row["timestamp"] * 1000, precision_us=1000,
                       symbol=symbol, source_symbol=symbol, price=Decimal(row["price"]),
                       native_quantity=Decimal(row["amount"]), quantity_currency="USD", quote_currency="USD",
                       side=row["direction"], trade_id=row["trade_id"], source_sequence=row["trade_seq"],
                       flags=flags, source_file=Path(path).name)


def record_key(row):
    return row["timestamp_us"], row["symbol"], row["source_sequence"]


def write_partition(records, destination, *, expected_rows, batch_rows=16384):
    import pyarrow as pa
    import pyarrow.parquet as pq
    if not 1 <= batch_rows <= 65536:
        raise ValueError("Batch size must be between 1 and 65536")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("Refusing to replace a partition")
    rows, count, previous, sequences, low, high = [], 0, None, {}, None, None
    with pq.ParquetWriter(destination, schema(), compression="zstd", compression_level=3,
                          use_dictionary=["symbol", "source_symbol", "quantity_currency", "quote_currency",
                                          "side", "source_file"], write_page_checksum=True) as writer:
        for row in records:
            key = record_key(row)
            if previous is not None and key <= previous:
                raise ValueError("Duplicate or unordered source event")
            prior_seq = sequences.get(row["symbol"])
            if prior_seq is not None and row["source_sequence"] != prior_seq + 1:
                raise ValueError("Source trade sequence gap")
            if row["price"] <= 0 or row["native_quantity"] <= 0 or row["side"] not in ("buy", "sell"):
                raise ValueError("Invalid source trade")
            previous, sequences[row["symbol"]] = key, row["source_sequence"]
            low = row["timestamp_us"] if low is None else low
            high = row["timestamp_us"]
            rows.append(row)
            count += 1
            if len(rows) == batch_rows:
                writer.write_table(pa.Table.from_pylist(rows, schema=schema()))
                rows.clear()
        if rows:
            writer.write_table(pa.Table.from_pylist(rows, schema=schema()))
    if count != expected_rows:
        raise ValueError("Partition row count differs from source manifest")
    return dict(rows=count, bytes=destination.stat().st_size, sha256=sha256(destination),
                first_us=low, last_us=high, row_groups=pq.ParquetFile(destination).num_row_groups)


def convert(raw_directory, destination, *, batch_rows=16384):
    started = time.monotonic()
    converter_hash = sha256(__file__)
    raw, out = Path(raw_directory), Path(destination)
    if out.exists():
        raise ValueError("Use a new immutable dataset directory")
    source_bytes = (raw / "manifest.json").read_bytes()
    source = json.loads(source_bytes)
    for item in [source["spot"], *source["futures"].values()]:
        if sha256(raw / item["path"]) != item["sha256"]:
            raise ValueError("Source checksum mismatch")
    out.mkdir(parents=True)
    day = source["start"][:10]
    spot_path = f"venue=binance/market=spot/date={day}/part-000.parquet"
    futures_path = f"venue=deribit/market=dated-futures/date={day}/part-000.parquet"
    partitions = []
    for path, rows, expected in [
        (spot_path, spot_records(raw / source["spot"]["path"]), source["spot"]["rows"]),
        (futures_path, heapq.merge(*[future_records(s, raw / info["path"])
                                    for s, info in sorted(source["futures"].items())], key=record_key),
         sum(info["rows"] for info in source["futures"].values())),
    ]:
        result = write_partition(rows, out / path, expected_rows=expected, batch_rows=batch_rows)
        partitions.append(dict(path=path, **result))
    result = dict(schema_version=VERSION, source_manifest=source,
                  source_manifest_sha256=hashlib.sha256(source_bytes).hexdigest(),
                  converter_sha256=converter_hash, partitions=partitions,
                  sort_order=["timestamp_us", "symbol", "source_sequence"],
                  row_group_rows=batch_rows, compression="zstd:3",
                  native_futures_contract_type="inverse", native_futures_settlement_currency="BTC",
                  native_futures_contract_size_usd=10,
                  conversion_seconds=time.monotonic() - started,
                  conversion_peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    # The completion manifest is published last. Failed conversions are unreadable.
    (out / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


class BlockCachedReader(io.RawIOBase):
    """Seekable GCS input with at most two 4 MiB blocks retained.

    Parquet reads many small column chunks. Coalescing neighboring range reads
    avoids one inter-region round trip per column while keeping memory bounded.
    The caller owns the underlying NativeFile; whole-file SHA is checked first.
    """
    def __init__(self, stream, block_size=4 * 1024 * 1024, max_blocks=2):
        super().__init__()
        self.stream, self.length = stream, stream.size()
        self.block_size, self.max_blocks = block_size, max_blocks
        if block_size <= 0 or max_blocks <= 0:
            raise ValueError("Cache sizes must be positive")
        self.position, self.blocks = 0, OrderedDict()

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if whence not in (0, 1, 2):
            raise ValueError("Invalid seek mode")
        target = offset + (0 if whence == 0 else self.position if whence == 1 else self.length)
        if target < 0:
            raise ValueError("Negative seek")
        self.position = target
        return target

    def read(self, size=-1):
        if self.closed:
            raise ValueError("Read of closed cache")
        size = max(0, self.length - self.position) if size is None or size < 0 else size
        remaining = min(size, max(0, self.length - self.position))
        result = bytearray()
        while remaining:
            index, offset = divmod(self.position, self.block_size)
            if index not in self.blocks:
                if len(self.blocks) >= self.max_blocks:
                    self.blocks.popitem(last=False)
                self.stream.seek(index * self.block_size)
                block = self.stream.read(min(self.block_size, self.length - index * self.block_size))
                if len(block) != min(self.block_size, self.length - index * self.block_size):
                    raise OSError("Truncated remote Parquet block")
                self.blocks[index] = block
            self.blocks.move_to_end(index)
            block = self.blocks[index]
            take = min(remaining, len(block) - offset)
            result.extend(block[offset:offset + take])
            self.position += take
            remaining -= take
        return bytes(result)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        self.blocks.clear()
        super().close()


def partition_trades(path, *, batch_rows=8192, start_us=None, end_us=None, symbols=None, filesystem=None):
    import pyarrow.parquet as pq
    if not 1 <= batch_rows <= 65536:
        raise ValueError("Batch size must be between 1 and 65536")
    # Explicitly avoid file-wide prefetch and whole-table materialization.
    with pq.ParquetFile(path, filesystem=filesystem, pre_buffer=False, buffer_size=65536,
                        page_checksum_verification=True) as file:
        if not file.schema_arrow.equals(schema(), check_metadata=True):
            raise ValueError("Unknown trade Parquet schema")
        groups = []
        for i in range(file.num_row_groups):
            stats = file.metadata.row_group(i).column(0).statistics
            if stats and ((start_us is not None and stats.max < start_us) or
                          (end_us is not None and stats.min >= end_us)):
                continue
            groups.append(i)
        previous = None
        for batch in file.iter_batches(batch_size=batch_rows, row_groups=groups,
                                       columns=ENGINE_COLUMNS, use_threads=False):
            columns = [column.to_pylist() for column in batch.columns]
            for ts, symbol, price, quantity, currency, side, identifier, flags in zip(*columns):
                key = (ts, symbol)
                if previous is not None and key < previous:
                    raise ValueError("Unordered Parquet events")
                previous = key
                if ((start_us is not None and ts < start_us) or (end_us is not None and ts >= end_us)
                        or (symbols is not None and symbol not in symbols)):
                    continue
                price = float(price)
                if currency not in ("BTC", "USD"):
                    raise ValueError("Unknown quantity currency")
                btc = float(quantity) if currency == "BTC" else float(quantity) / price
                yield Trade(ts, symbol, price, btc, side, identifier, flags == 0)


class ParquetTradeStore:
    def __init__(self, directory):
        self.filesystem = None
        if str(directory).startswith("gs://"):
            from pyarrow.fs import GcsFileSystem
            self.filesystem = GcsFileSystem()
            from google.cloud import storage
            bucket_name, _, object_prefix = str(directory)[5:].partition("/")
            self.gcs_bucket = storage.Client().bucket(bucket_name)
            manifest_blob = self.gcs_bucket.blob(object_prefix.rstrip("/") + "/manifest.json")
            manifest_blob.reload()
            self.manifest_generation = int(manifest_blob.generation)
            self.root = str(directory)[5:].rstrip("/")
            self.manifest_bytes = manifest_blob.download_as_bytes(
                if_generation_match=self.manifest_generation, checksum="crc32c")
        else:
            self.root = Path(directory)
            self.manifest_bytes = (self.root / "manifest.json").read_bytes()
        self.manifest = json.loads(self.manifest_bytes)
        if self.manifest.get("schema_version") != VERSION:
            raise ValueError("Unknown dataset schema version")
        self.source_manifest = self.manifest["source_manifest"]
        self.verified = set()
        self.generations = {}
        self.accessed_partitions = []
        self.timings = {"checksum_reads": 0.0, "decode_and_merge": 0.0}
        self.daily_cache = OrderedDict()
        self.check_cancelled = lambda: None
        if self.manifest.get("daily_datasets"):
            self._validate_range()
            return
        paths = set()
        for item in self.manifest["partitions"]:
            relative = Path(item["path"])
            if relative.is_absolute() or ".." in relative.parts or item["path"] in paths:
                raise ValueError("Invalid partition path")
            paths.add(item["path"])
        expected = self.source_manifest["spot"]["rows"] + sum(x["rows"] for x in self.source_manifest["futures"].values())
        if sum(x["rows"] for x in self.manifest["partitions"]) != expected:
            raise ValueError("Dataset count differs from source")

    def _partition(self, item, **kwargs):
        path = self.root + "/" + item["path"] if self.filesystem else self.root / item["path"]
        blob = None
        if self.filesystem:
            blob = self.gcs_bucket.blob(path.split("/", 1)[1], generation=self.generations.get(item["path"]))
            if item["path"] not in self.generations:
                blob.reload()
                self.generations[item["path"]] = int(blob.generation)
            item = {**item, "generation": self.generations[item["path"]]}
        # Repeated warm-up/comparison reads within the same job reuse verified immutable inputs.
        if item["path"] not in self.verified:
            started = time.monotonic()
            digest = hashlib.sha256()
            stream = blob.open("rb", chunk_size=4 * 1024 * 1024) if blob else path.open("rb")
            with stream:
                while block := stream.read(1024 * 1024):
                    self.check_cancelled()
                    digest.update(block)
            if digest.hexdigest() != item["sha256"]:
                raise ValueError("Parquet checksum mismatch")
            self.timings["checksum_reads"] += time.monotonic() - started
            self.verified.add(item["path"])
            self.accessed_partitions.append(dict(item))
        if self.filesystem:
            # BlobReader pins every ranged read to the verified object generation.
            with blob.open("rb", chunk_size=4 * 1024 * 1024) as remote:
                class PinnedReader:
                    def size(self): return item["bytes"]
                    def read(self, n): return remote.read(n)
                    def seek(self, offset): return remote.seek(offset)
                with BlockCachedReader(PinnedReader()) as cached:
                    yield from partition_trades(cached, **kwargs)
        else:
            yield from partition_trades(path, **kwargs)

    def _validate_range(self):
        from btc_trade_backtest import us_time
        expected = us_time(self.source_manifest["start"])
        days = self.manifest["daily_datasets"]
        if not 1 <= len(days) <= 90:
            raise ValueError("Range dataset requires 1 to 90 UTC days")
        for day in days:
            lo, hi = us_time(day["start"]), us_time(day["end"])
            if lo != expected or hi-lo != 86400_000_000 or lo % 86400_000_000:
                raise ValueError("Missing, overlapping or non-UTC daily coverage")
            if not re.fullmatch("[0-9a-f]{64}", day["manifest_sha256"]):
                raise ValueError("Invalid daily manifest checksum")
            expected = hi
        if expected != us_time(self.source_manifest["end"]):
            raise ValueError("Range coverage does not match its days")

    def _range_trades(self, **kwargs):
        from btc_trade_backtest import us_time
        lo, hi = kwargs.get("start_us"), kwargs.get("end_us")
        for day in self.manifest["daily_datasets"]:
            if (lo is not None and us_time(day["end"]) <= lo) or (hi is not None and us_time(day["start"]) >= hi):
                continue
            key = day["manifest_sha256"]
            if key not in self.daily_cache:
                if self.filesystem:
                    # Range manifests may only reference immutable objects in this bucket.
                    uri = "gs://" + self.root.split("/", 1)[0] + "/btc/trades/v1/" + key
                else:
                    relative = Path(day["local_path"])
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError("Unsafe daily dataset path")
                    uri = self.root / relative
                child = ParquetTradeStore(uri)
                if hashlib.sha256(child.manifest_bytes).hexdigest() != key:
                    raise ValueError("Daily manifest checksum mismatch")
                if (us_time(child.source_manifest["start"]) != us_time(day["start"]) or
                        us_time(child.source_manifest["end"]) != us_time(day["end"])):
                    raise ValueError("Daily manifest coverage mismatch")
                # Retain metadata/checksum identities only; decoded batches are not cached.
                self.daily_cache[key] = child
            child = self.daily_cache[key]
            child.check_cancelled = self.check_cancelled
            before = dict(child.timings)
            yield from child.trades(**kwargs)
            for phase in self.timings:
                self.timings[phase] += child.timings[phase] - before[phase]
            for part in child.accessed_partitions:
                value = {**part, "daily_manifest_sha256": key}
                if value not in self.accessed_partitions:
                    self.accessed_partitions.append(value)

    def trades(self, *, batch_rows=8192, start_us=None, end_us=None, symbols=None):
        if self.manifest.get("daily_datasets"):
            return self._range_trades(batch_rows=batch_rows, start_us=start_us, end_us=end_us, symbols=symbols)
        # Open one partition at a time per venue/market, not one per historical day.
        markets = {}
        for item in self.manifest["partitions"]:
            if (not item["rows"] or (start_us is not None and item["last_us"] < start_us)
                    or (end_us is not None and item["first_us"] >= end_us)):
                continue
            if symbols is not None and "SPOT" not in symbols and "/market=spot/" in item["path"]:
                continue
            if symbols == {"SPOT"} and "/market=dated-futures/" in item["path"]:
                continue
            markets.setdefault(str(Path(item["path"]).parent.parent), []).append(item)
        streams = []
        for parts in markets.values():
            parts.sort(key=lambda x: (x["first_us"], x["path"]))
            for left, right in zip(parts, parts[1:]):
                if left["last_us"] > right["first_us"]:
                    raise ValueError("Overlapping partition times")
            streams.append(chain.from_iterable(self._partition(item, batch_rows=batch_rows,
                start_us=start_us, end_us=end_us, symbols=symbols) for item in parts))
        def measured():
            merged = iter(heapq.merge(*streams, key=lambda event: (event.us, event.symbol)))
            while True:
                started = time.monotonic()
                try:
                    event = next(merged)
                except StopIteration:
                    return
                finally:
                    self.timings["decode_and_merge"] += time.monotonic() - started
                yield event
        return measured()
