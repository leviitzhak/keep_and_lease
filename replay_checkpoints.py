"""Immutable restart journals. A checkpoint is visible only after its audits exist."""
import gzip
import hashlib
import json
import math
from pathlib import Path

MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
_FLOAT_SENTINEL = "__keep_and_lease_float__"


def _json_safe(value):
    """Encode deliberate infinity sentinels without emitting non-standard JSON.

    Checkpoint state occasionally needs an internal +inf/-inf accumulator before
    the first finite observation exists. JSON itself has no infinity numeric
    value, so store those sentinels as tagged objects. NaN remains an error: it
    never represents a legitimate replay state.
    """
    if isinstance(value, float):
        if math.isnan(value):
            raise ValueError("Replay checkpoint contains NaN")
        if math.isinf(value):
            return {_FLOAT_SENTINEL: "positive" if value > 0 else "negative"}
        return value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _restore_json_object(value):
    if set(value) == {_FLOAT_SENTINEL}:
        direction = value[_FLOAT_SENTINEL]
        if direction == "positive":
            return math.inf
        if direction == "negative":
            return -math.inf
        raise ValueError("Invalid replay checkpoint float sentinel")
    return value


def encode(value):
    data = json.dumps(_json_safe(value), allow_nan=False, separators=(",", ":")).encode()
    if len(data) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Replay checkpoint exceeds its bounded size")
    return gzip.compress(data, compresslevel=3, mtime=0)


def decode(data):
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        raw = stream.read(MAX_CHECKPOINT_BYTES + 1)
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Replay checkpoint exceeds its bounded size")
    return json.loads(raw, object_hook=_restore_json_object)


def fingerprint(payload, manifest_bytes, data_root=None):
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode())
    digest.update(manifest_bytes)
    for name in ("btc_trade_backtest.py", "trade_replay.py", "backtest_audit.py",
                 "trade_data_store.py", "trade_ordering.py", "backtest_silver_lease_strategy.py", "maturity_scoring.py",
                 "silver_strategy_gui.py"):
        digest.update((Path(__file__).parent / name).read_bytes())
    if data_root is not None:
        for name in ("DTB3", "DTB6", "DGS1", "DGS2", "DGS3", "DGS5"):
            path = Path(data_root) / (name+".csv")
            if path.exists():
                digest.update(path.read_bytes())
    return digest.hexdigest()


class DirectoryCheckpoints:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def latest(self):
        paths = sorted(self.path.glob("[0-9]*.json.gz"))
        return decode(paths[-1].read_bytes()) if paths else None

    def save(self, tick, state):
        data = encode(state)
        path = self.path / f"{tick:020d}.json.gz"
        temporary = path.with_suffix(".tmp")
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("Checkpoint conflict")
            return
        temporary.write_bytes(data)
        temporary.replace(path)


class GcsCheckpoints:
    def __init__(self, bucket, prefix):
        self.bucket, self.prefix = bucket, prefix

    def latest(self):
        objects = list(self.bucket.list_blobs(prefix=self.prefix))
        if not objects:
            return None
        blob = max(objects, key=lambda b: b.name)
        if blob.size > MAX_CHECKPOINT_BYTES:
            raise ValueError("Checkpoint object exceeds its size limit")
        return decode(blob.download_as_bytes(if_generation_match=blob.generation, checksum="crc32c"))

    def save(self, tick, state):
        from google.api_core.exceptions import PreconditionFailed
        blob = self.bucket.blob(self.prefix + f"{tick:020d}.json.gz")
        data = encode(state)
        try:
            blob.upload_from_string(data, if_generation_match=0, checksum="crc32c",
                                    content_type="application/gzip")
        except PreconditionFailed:
            if blob.download_as_bytes(checksum="crc32c") != data:
                raise ValueError("Checkpoint conflict") from None
