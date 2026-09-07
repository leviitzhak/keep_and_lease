# Immutable BTC trade storage: pilot implementation

The first storage phase converts the verified 25 June 2026 raw-trade pilot into
Parquet and reads it through the existing research account. It remains separate
from the production GUI minute provider. The original silver/BTC strategies and
source archives are preserved. Review: [PR #38](https://github.com/leviitzhak/keep_and_lease/pull/38).

## Format and identity

`trade_data_store.py` writes two daily partitions, one Binance spot file and one
Deribit dated-futures file containing all 12 contracts. Files are ordered by
integer UTC microseconds, symbol and original sequence. Native precision is
recorded separately: microseconds for this Binance archive, milliseconds for
Deribit. No resampling, interpolation or timestamp rounding is applied.

Prices and native quantities use Decimal128(38,12), preserving the source values
exactly; excess precision fails conversion rather than rounding. Each row retains
source symbol, quote/quantity currencies, trade ID, sequence, source filename,
aggressor side and block/RFQ/combo flags. Other source fields remain in the raw
archives linked by file hash plus trade ID. The replay adapter converts native
USD face amounts to BTC using the same float division as the raw replay. It does
not change the inverse instrument's identity or measure USDT/USD parity.

Partitions use Parquet with Zstandard level 3 and 16,384-row groups. The completed
manifest includes source manifest and hashes, seed trades, expiry metadata,
inverse contract size/settlement convention, row counts, time bounds, partition
hashes, schema/converter versions and sort order. It is written last. Existing
dataset directories cannot be overwritten; failed conversions have no completion
manifest. Raw bytes, sequence continuity, ordering and counts are verified.

## Reading and memory

`ParquetTradeStore` reads local directories or `gs://` prefixes. It merges spot
and futures chronologically and converts at most 8,192 rows per batch by default.
It reads only execution columns, skips row groups outside the selected half-open
time window, supports symbol filters, and verifies selected partition SHA-256 and
Parquet page checksums. Prefetch of whole files and read-table concatenation are
disabled. Consecutive partitions are opened lazily per market; memory does not
require a separate input batch for every historical day.

The current implementation does a bounded checksum scan before reading a selected
partition. This deliberately adds I/O for verification. GCS reads use Arrow's
native authenticated filesystem, without a complete temporary local-file copy.
The Cloud Run writable filesystem consumes RAM, so large caches there must not
be treated as free disk.

## Reproduction

```sh
python -m pip install -r requirements-trade-data.txt
python scripts/convert-btc-trade-parquet.py --output work/btc-trade-parquet/validated-v1-2026-06-25
python scripts/check-btc-parquet-equivalence.py --parquet work/btc-trade-parquet/validated-v1-2026-06-25 --output work/btc-trade-parquet/validated-equivalence.json
python scripts/check-btc-trade-pilot.py --parquet work/btc-trade-parquet/validated-v1-2026-06-25 --data work/no-raw-inputs --output work/btc-trade-parquet/validated-one-dollar
python scripts/check-btc-trade-pilot.py --parquet work/btc-trade-parquet/validated-v1-2026-06-25 --data work/no-raw-inputs --capital 100000 --participation 0.1 --output work/btc-trade-parquet/validated-capacity
```

Use fresh output paths for reruns. `--data work/no-raw-inputs` demonstrates that
the Parquet replay does not open the source archives. It still reads the existing
causal Treasury files and saved strategy. Optional Arrow/storage dependencies are
isolated in `requirements-trade-data.txt`; production image requirements are not
changed. The uploader's API-core version matches the cloud stack's documented
Firestore routing fix.

## Cloud publication

`scripts/upload-btc-trade-parquet.py` defaults to validating and printing a plan:

```sh
python scripts/upload-btc-trade-parquet.py --data work/btc-trade-pilot/2026-06-25 --parquet work/btc-trade-parquet/validated-v1-2026-06-25
```

Add `--execute` in an environment with existing Application Default Credentials
authorized to create and read objects in `keep-and-lease-market-data`.

- Raw objects: `btc/raw/sha256/<source-sha>/<filename>`. Multiple dataset versions
  reuse the same source objects instead of duplicating the originals.
- Normalized objects: `btc/trades/v1/<dataset-manifest-sha>/venue=.../market=.../date=.../part-000.parquet`.
- The dataset's `manifest.json` is uploaded last. Every upload uses create-only
  generation preconditions and CRC32C; retries byte-verify existing objects and
  fail on conflicts. Readers use the manifest URI rather than listing a prefix
  that might contain a partially uploaded dataset.

The local upload plan covers 17 objects, approximately 65.59 MB including both
representations and manifests. **Cloud upload and live GCS reading have not been
verified.** This workspace has no configured ADC credentials, and metadata-based
credential discovery could not complete. The repository's existing cloud-agent
operator has no market-bucket write authority; its bounded diagnostic path is
not an upload route. No IAM grants, credentials or cloud resource sizes were
changed. The create-only uploader is covered by mocked client tests, which are
not evidence of real GCS access.

## Measurements and remaining gates

The final pilot conversion retained all 5,739,608 trades:

| Representation | Spot bytes | Futures bytes | Total bytes |
| --- | ---: | ---: | ---: |
| Original compressed archives | 40,814,230 | 1,040,996 | 41,855,226 |
| Parquet | 23,107,333 | 601,904 | 23,709,237 |

Conversion took 43.82 seconds, peaking at 155.95 MiB RSS. Parquet is approximately
43.4% smaller than these compressed raw inputs. This is a one-day measurement;
historical compression and futures activity can differ. Applying these ratios to
the earlier archive inventory suggests about 3.31 GB for 90 days or 130 GB for
history **when retaining both raw and normalized copies**. A provisional 150 GB
history input budget replaces the earlier 100 GB single-copy allowance. Audits,
backups, retained dataset versions and additional markets are extra.

Evidence is recorded under `validation/btc-trade-parquet/`. Full event comparison
uses the independently maintained raw CSV/JSON decoders, including IDs, flags,
prices, BTC quantities and ordering. Full-day replay validation compares complete
uncompressed audits and financial summaries against both saved raw baselines.

Both financial summaries matched exactly, and the entire decompressed audit
streams were byte-for-byte identical (724,281 and 1,782,063 rows). Parquet replay
peaked at 144.16 MiB / 146.35 MiB RSS and took 63.47 / 87.34 seconds for the $1
and $100,000 scenarios. These concurrent-run timings are measurements, not a
controlled claim of speedup over the earlier raw runs. Arrow's libraries and
batches use more RAM than the 39.79 MiB raw-only prototype, while remaining well
within the current worker limit for this pilot. No cloud resource increase was
made or established as necessary for longer histories.

All 26 focused Python tests passed, including seven storage/publication tests.
The publication tests use a mock cloud client: they check create-only writes,
manifest-last ordering, retry verification and refusal of conflicting objects.
The optional storage tests explicitly skip if their optional dependencies are
absent. `npm run prepare:assets` was run before fresh-process tests; the prior
full API/workbook acceptance was not repeated for this isolated storage change.

The next gates are an authenticated immutable upload/read check, a multi-day
source manifest and ingestion driver, and continuous-account checkpoint/restore
tests across partition boundaries. The current research runner still explicitly
accepts one UTC day; 90-day raw-trade ingestion, production worker integration,
and GUI activation have not been performed. These must preserve positions,
pending fills and Treasury accrual across days, rather than restarting the
strategy independently each day.

## Giving automation access to the bucket

IAP protects the web preview. Cloud Storage uses separate bucket IAM bindings.
The existing keyless operator identity is
`keep-lease-codex-operator@keep-and-lease.iam.gserviceaccount.com`. To authorize
create-only publication and verification using that identity, an administrator
can grant these two roles **on the market-data bucket only**:

```sh
gcloud storage buckets add-iam-policy-binding gs://keep-and-lease-market-data --member=serviceAccount:keep-lease-codex-operator@keep-and-lease.iam.gserviceaccount.com --role=roles/storage.objectCreator
gcloud storage buckets add-iam-policy-binding gs://keep-and-lease-market-data --member=serviceAccount:keep-lease-codex-operator@keep-and-lease.iam.gserviceaccount.com --role=roles/storage.objectViewer
```

These commands are proposed administrator actions, not actions performed by this
change. They grant creation and read/list access without object deletion or
overwrite permission. They do not change IAP or make the bucket public. Equivalent
console steps are Cloud Storage → `keep-and-lease-market-data` → Permissions →
Grant access, using the identity and the two roles above.

**A grant alone is not an upload connection.** The current operator workflow
accepts diagnostics only. Using this route also requires an explicitly reviewed,
bounded ingestion workflow on its OIDC-authorized branch, running the existing
archive downloader/converter/uploader inside GitHub Actions. It must check source
and manifest hashes and publish the manifest last. No credential needs to be
copied into chat or the working-agent filesystem. The IAM bindings should then
be represented in the foundation Terraform so configuration matches deployed
access. A dedicated uploader service account with its own branch-restricted OIDC
binding is preferable if keeping the diagnostic identity read-only is desired;
that identity/workflow has not yet been created.

The calculation worker's market-bucket `roles/storage.objectViewer` binding
already exists in `infra/gcp/main.tf`; its authority is separate from the agent's.
This input bucket grant is unrelated to the current minute GUI transport failure;
see [BTC_CONNECTION_RECOVERY.md](BTC_CONNECTION_RECOVERY.md).

References: [Cloud Storage roles](https://cloud.google.com/storage/docs/access-control/iam-roles)
and [GitHub/OIDC federation](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).
