# Run BTC PRD research locally, offline

This guide concerns the Python research probes, not the deployed GUI or a live
exchange client. No GPU, database, Docker daemon or exchange connection is
required for offline replay. A 1 ms simulated delay is a timestamp rule and does
not require live low-latency hardware. Inputs must be copied and dependencies installed
once before disconnecting.

## Tested software

- Python 3.12 on Linux. The local 2026 comparison used Python 3.12.14 and NumPy
  2.3.5; the cloud workflow records its exact installed versions in each artifact.
- NumPy is the only non-standard dependency needed during offline replay.
- `google-cloud-storage` is needed only for the initial archive preparation.
  It uses the owner's existing read access and Application Default Credentials;
  the script neither grants permissions nor stores credentials in its cache.
- macOS should run the same scripts; Windows can use WSL2. Those platforms have
  not been benchmarked here. Linux `ru_maxrss` reporting is used for the recorded
  memory measurements; macOS requires unit conversion before comparing RSS.

## One-time preparation

Check out the `docs/btc-prd-exposure-band-plan` research branch from the canonical
repository. Source scripts live in `docs/research`, independently of application
packages. Create a Python environment and install NumPy. If this must also work
on a disconnected machine, stage the wheels on a compatible online machine:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip download --dest wheelhouse 'numpy==2.3.5'
.venv/bin/python -m pip install --no-index --find-links wheelhouse 'numpy==2.3.5'
```

Prepare the fixed retained archive cache on an authorized online machine:

```bash
.venv/bin/python -m pip install 'google-cloud-storage>=2.18,<4'
.venv/bin/python docs/research/btc_prd_prepare_offline.py --cache ./archive-cache
```

Use existing local Google credentials with archive read permission; no credential
files belong in the portable cache. The downloader reads only the already saved
October 9 archive, verifies compressed source hashes and retains the receipts.
It does not request new data from Deribit. `--symbol BTC-25DEC26` prepares a
single eligible contract for a smaller first run. Copy the resulting cache,
source code and compatible wheelhouse to the offline machine. Keep the cache's
nested relative paths unchanged.

## Offline execution

```bash
.venv/bin/python -m unittest discover -s docs/research -p test_btc_prd_calibration.py
.venv/bin/python docs/research/btc_prd_full_history.py \
  --offline --cache ./archive-cache --output ./local-results
```

A single-contract run:

```bash
.venv/bin/python docs/research/btc_prd_full_history.py \
  --offline --cache ./archive-cache --output ./dec26-results --symbol BTC-25DEC26
```

A missing cached file raises an error; offline mode does not fall back to a
network fetch. Results include input hashes, fees and marks, every actual fill,
coverage exclusions, training splits, delay assumptions and runtime/RSS metrics.
The offline benchmark includes the independent audit, so removing audit work is
not a like-for-like speed comparison.

For parallel runs, launch separate processes using `--shards N --shard K`, where
K ranges from 0 through N-1. Give each process a distinct output directory. They
may read the same completed cache. Prepare the cache before parallel replay;
do not have multiple preparation processes writing it concurrently. One process
uses one CPU core for most work; adding threads does not accelerate its Python
event loop. Multiple processes do run separate contracts concurrently.

The original 2026 comparison can also be reproduced from the retained verified
Dec26/Mar27 input artifact using `btc_prd_2026_extension.py --inputs INPUT_DIR
--output OUTPUT_DIR`. Its grid is fixed in `btc-prd-calibration-config.json`.
Do not replace this with a grid derived from the same test slice.

## Measured small-sample cost

The 2026 extension processed 486,203 raw / 462,642 ordinary trades, ran 260
execution paths and derived 156 exact fee-only comparisons. On this workspace's
Intel Xeon Platinum 8573C CPU it took **61.8 seconds overall**, including **57.1
seconds of replay**, with **172.6 MiB peak process RSS**. The input gzip files
occupy 8.70 MiB and the result JSON/fill audit 2.03 MiB. These are measurements
for the unit probe, not a prediction of a future funded multi-pair engine.

Full-history sizing and measured results are recorded in
[the extended calibration report](BTC_PRD_EXTENDED_CALIBRATION.md). Memory scales
with the largest contract's decoded tape and audit indexes, rather than the
whole archive at once. Disk estimates must distinguish required trade objects
from the larger archive's original API responses and anomaly evidence.

## Full-history measurement and hardware estimate

The complete 42-contract study ran 2,035 execution paths plus 1,221 fee-only
cases, auditing 1.17 million fills. Eight workers completed successfully; the
slowest shard spent **15.2 minutes** in its studies. Summed contract time was
**101.2 worker-minutes**, including downloads/parsing; summed replay-plus-audit
time was **76.1 worker-minutes**. The runners exposed four logical CPUs and about
16 GB RAM each (AMD EPYC 7763/9V74 and Intel Xeon hosts); each Python event loop
used one core for most computation. This was eight separate runners, not proof
that an eight-core laptop will match those exact wall times.

The maximum recorded worker RSS was **1,614 MiB (1.58 GiB)**. The largest decoded
contract had 3.31 million ordinary records. Required compressed trade objects
occupy **935 MiB**; all eight shard caches, including duplicated small metadata
and receipts, total **954 MiB**. Full result files occupy about **70 MiB** before
artifact ZIP compression. The complete 120-million-row archive with raw API
response evidence is larger and is not required for these eligible-history
probes; its total disk footprint was not measured here.

| Intended use | Practical specification | Planning time |
|---|---|---|
| Serial offline study | 2-4 modern CPU cores, 8 GB RAM, 10 GB free SSD | Roughly 1-2 hours for this grid |
| Regular local research | 4-8 cores, 16 GB RAM, 20 GB free SSD | Roughly 20-45 minutes with 4 workers |
| Larger parallel sweeps | 8+ cores, 32 GB RAM, 50 GB free SSD | Roughly 15-30 minutes for this grid; scales with added scenarios |

The RAM and SSD recommendations include operating-system and experimentation
headroom. Timing ranges are estimates derived from the measured work, not local
benchmarks on each proposed machine. Start with one worker, then increase to
four while watching RAM; 32 GB is comfortable for eight parallel workers and
additional analysis. Keep the compressed cache, load one contract per process,
and avoid materializing all 120 million records as Python objects at once.
No GPU is needed. Retaining alternative outputs, full exchange responses, or a
future funded multi-pair engine will increase these requirements.

Full-history environment: Python 3.12.15 / NumPy 2.5.4, recorded in
`requirements-observed.txt`. Stage that NumPy version for matching runs.
Matplotlib is needed only for chart regeneration.
