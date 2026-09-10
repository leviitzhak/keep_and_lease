"""Bounded, lossless audit chunks shared by local and durable calculations."""
import gzip
import hashlib
import io
import json
import re
import time
from pathlib import Path

MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
AUDIT_NAME = re.compile(r"(?:[a-z][a-z0-9_]*/[0-9]{6}\.jsonl\.gz|manifest\.json)\Z")


def validate_name(name):
    if not AUDIT_NAME.fullmatch(name):
        raise ValueError("Invalid audit object name")
    return name


class MemoryAuditStore:
    def __init__(self):
        self.objects = {}

    def put(self, name, data):
        validate_name(name)
        if name in self.objects:
            raise ValueError("Audit objects are immutable")
        self.objects[name] = data

    def get(self, name):
        return self.objects[validate_name(name)]


class ReplayAuditStore:
    """Allow restart retries only when previously published bytes are identical."""
    def __init__(self, store):
        self.store = store

    def get(self, name):
        return self.store.get(name)

    def put(self, name, data):
        try:
            existing = self.store.get(name)
        except (KeyError, FileNotFoundError):
            self.store.put(name, data)
            return
        if existing != data:
            raise ValueError("Replay audit conflicts with an immutable object")


class DirectoryAuditStore:
    """CLI/test destination; Cloud Run uses GCS, not its memory-backed filesystem."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def put(self, name, data):
        path = self.directory / validate_name(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)

    def get(self, name):
        return (self.directory / validate_name(name)).read_bytes()


def read_chunk(store, entry):
    data = store.get(entry["object"])
    if hashlib.sha256(data).hexdigest() != entry["compressed_sha256"]:
        raise ValueError("Audit compressed checksum mismatch")
    digest = hashlib.sha256()
    count = size = 0
    # Read line by line. Never allocate the whole decompressed audit archive.
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        for line in stream:
            count += 1
            size += len(line)
            if size > MAX_CHUNK_BYTES * 2:
                raise ValueError("Audit chunk expands beyond its limit")
            digest.update(line)
            yield json.loads(line)
    if (digest.hexdigest() != entry["sha256"] or count != entry["rows"]
            or size != entry["uncompressed_bytes"]):
        raise ValueError("Audit row count or checksum mismatch")


class ChunkWriter:
    def __init__(self, collection, product):
        self.collection = collection
        self.product = product
        self.entries = []
        self.count = 0
        self.metadata = {}
        self.row_limit = 1024
        self._reset()

    def _reset(self):
        self.buffer = io.BytesIO()
        self.gzip = gzip.GzipFile(fileobj=self.buffer, mode="wb", mtime=0, compresslevel=3)
        self.digest = hashlib.sha256()
        self.size = self.rows = 0
        self.start = self.end = self.day = None
        self.opening_nav = self.closing_nav = None

    def emit(self, row):
        began = time.monotonic()
        old_writes = self.collection.timings["audit_write"]
        self.collection.check_cancelled()
        start = row.get("date") or row.get("start_date")
        end = row.get("exit_date", row.get("date"))
        partition = str(start)[:10] if "T" in str(start) else str(start)[:7]
        encoded = (json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n").encode()
        if len(encoded) > MAX_CHUNK_BYTES:
            raise ValueError("A single audit row exceeds the chunk limit")
        if self.rows and (self.rows >= self.row_limit or self.size + len(encoded) > MAX_CHUNK_BYTES
                          or partition != self.day):
            self.flush()
        if not self.rows:
            self.start = start
            self.day = partition
            self.opening_nav = row.get("starting_nav")
        self.end = end
        self.closing_nav = row.get("ending_nav")
        self.gzip.write(encoded)
        self.digest.update(encoded)
        self.size += len(encoded)
        self.rows += 1
        self.count += 1
        self.collection.timings["audit_compression"] += time.monotonic()-began-(self.collection.timings["audit_write"]-old_writes)

    def flush(self):
        if not self.rows:
            return
        self.collection.check_cancelled()
        self.gzip.close()
        encoded = self.buffer.getvalue()
        index = len(self.entries)
        name = f"{self.product}/{index:06d}.jsonl.gz"
        began = time.monotonic()
        self.collection.store.put(name, encoded)
        self.collection.timings["audit_write"] += time.monotonic()-began
        self.entries.append({"index": index, "object": name,
                             "first_row": self.count - self.rows, "rows": self.rows,
                             "start": self.start, "end": self.end,
                             "opening_nav": self.opening_nav, "closing_nav": self.closing_nav,
                             "uncompressed_bytes": self.size, "compressed_bytes": len(encoded),
                             "sha256": self.digest.hexdigest(),
                             "compressed_sha256": hashlib.sha256(encoded).hexdigest()})
        self._reset()

    def selected(self, indices):
        self.flush()
        wanted = set(indices)
        for entry in self.entries:
            first = entry["first_row"]
            if any(first <= index < first + entry["rows"] for index in wanted):
                # Exhaust even the final selected chunk to verify its checksum.
                for offset, row in enumerate(read_chunk(self.collection.store, entry)):
                    if first + offset in wanted:
                        yield first + offset, row


class AuditCollection:
    def __init__(self, store, *, base_url=None, provenance=None, check_cancelled=None):
        self.store = store
        self.base_url = base_url
        self.provenance = provenance or {}
        self.check_cancelled = check_cancelled or (lambda: None)
        self.writers = {}
        self.checkpoints = None
        self.timings = {"audit_compression": 0.0, "audit_write": 0.0}

    def snapshot(self):
        """Publish all data before the restart cursor; incomplete uploads are ignored."""
        result = {}
        for product, writer in self.writers.items():
            writer.flush()
            result[product] = dict(entries=list(writer.entries), count=writer.count,
                                   metadata=dict(writer.metadata), row_limit=writer.row_limit)
        return result

    def restore(self, state):
        for product, saved in state.items():
            writer = self.writer(product)
            if writer.count:
                raise ValueError("Cannot restore over an active audit")
            writer.entries = saved["entries"]
            writer.count = saved["count"]
            writer.metadata = saved["metadata"]
            writer.row_limit = saved["row_limit"]

    def writer(self, product):
        if not re.fullmatch(r"[a-z][a-z0-9_]*", product):
            raise ValueError("Invalid audit product")
        if product not in self.writers:
            self.writers[product] = ChunkWriter(self, product)
        return self.writers[product]

    def finish(self):
        self.check_cancelled()
        datasets = {}
        for product, writer in self.writers.items():
            writer.flush()
            # flush() prepares the next empty buffer. Close its unused gzip
            # wrapper explicitly before interpreter shutdown (including 3.13).
            writer.gzip.close()
            datasets[product] = {"rows": writer.count, "chunks": writer.entries,
                                 **writer.metadata}
        manifest = {"schema_version": 1, "base_url": self.base_url,
                    "provenance": self.provenance, "datasets": datasets}
        data = json.dumps(manifest, allow_nan=False, separators=(",", ":")).encode()
        if len(data) > MAX_MANIFEST_BYTES:
            raise ValueError("Audit manifest exceeds the limit")
        self.check_cancelled()
        self.store.put("manifest.json", data)
        return manifest


def load_manifest(store):
    data = store.get("manifest.json")
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("Audit manifest exceeds the limit")
    value = json.loads(data)
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported audit schema")
    return value


def project_row(row, product, section):
    """Lossless compatibility projections from stored canonical engine rows."""
    if section == "raw" or product == "portfolio":
        return row
    if section == "spreadsheet":
        from silver_strategy_gui import SPREADSHEET_FIELDS, HOLDING_FIELDS
        return {**{field: row.get(field) for field in SPREADSHEET_FIELDS},
                "held_futures": row.get("held_futures", []),
                "holding_ledger": [[item.get(field) for field in HOLDING_FIELDS]
                                   for item in row.get("holding_ledger", [])]}
    if section == "rate_change":
        return [{**point, "commodity": product, "date": point["end_date"],
                 "symbol": point["leg"], "days": point["weighted_maturity"],
                 "rate_change_return_pct": 100 * point["position_relative_return"]}
                for point in row.get("rate_change_attribution_points", [])
                if not point.get("excluded")]
    raise ValueError("Unknown audit section")


def archive_chunks(store, manifest):
    """Stream one ZIP containing the manifest and original compressed chunks."""
    import zipfile
    class Output(io.RawIOBase):
        def __init__(self):
            self.parts = []
            self.offset = 0
        def writable(self):
            return True
        def seekable(self):
            return False
        def tell(self):
            return self.offset
        def write(self, data):
            self.parts.append(data)
            self.offset += len(data)
            return len(data)
        def drain(self):
            parts, self.parts = self.parts, []
            yield from parts
    output = Output()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
        yield from output.drain()
        for dataset in manifest["datasets"].values():
            for entry in dataset["chunks"]:
                data = store.get(validate_name(entry["object"]))
                if hashlib.sha256(data).hexdigest() != entry["compressed_sha256"]:
                    raise ValueError("Audit checksum mismatch")
                archive.writestr(entry["object"], data)
                yield from output.drain()
    yield from output.drain()
