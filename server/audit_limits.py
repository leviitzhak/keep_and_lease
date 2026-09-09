"""Deployment resource budget; deliberately outside replay semantic fingerprints."""
import os
import backtest_audit


def configure_audit_limits():
    # A 90-day replay has millions of rows, stored in bounded chunks. Its index
    # can exceed 4 MiB even though no individual chunk or checkpoint is too big.
    limit = int(os.getenv("KEEP_AND_LEASE_AUDIT_MANIFEST_MIB", "32"))
    if not 4 <= limit <= 64:
        raise ValueError("KEEP_AND_LEASE_AUDIT_MANIFEST_MIB must be between 4 and 64")
    backtest_audit.MAX_MANIFEST_BYTES = limit * 1024 * 1024
