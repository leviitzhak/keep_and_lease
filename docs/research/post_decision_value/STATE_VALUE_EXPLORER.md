# Local state-value explorer and optional market simulation

Implemented 28 October 2026 on `agent/btc-post-decision-value-v1`. This is a
standalone local research UI with a Python inference API. It does not alter the
production application, deploy a service, submit live orders, or start a learning
campaign. The current published model remains **diagnostic-only: its repeated
network policy failed acceptance**. There is no accepted fitted max–min model.

The subsequent [four-step, small single-BILL diagnostic](TREASURY_SMALL_DIAGNOSTIC.md)
uses a separate 44-feature checkpoint and failed scalar calibration. This explorer
and its downloadable package retain their original 20-feature model; the new
checkpoint is not compatible with the explorer's existing loader.

## Start on your computer

Clone or update this research branch, then run from its repository directory.
A small standalone ZIP is also available as
[treasury-explorer-windows.zip](treasury-explorer-windows.zip). It contains the UI,
necessary Python modules, checkpoint, examples and launch scripts; it excludes the
full repository, historical archives and dependencies. Extract All before running
scripts. `PACKAGE-MANIFEST.json` records per-file hashes. Build it with
`python scripts/package_explorer.py --output /tmp/treasury-explorer-windows.zip`.

On Intel/AMD Windows use x64 CPython 3.12, 3.13 or 3.14. On Snapdragon/ARM Windows
use native ARM64 CPython **3.12 or 3.13**: the pinned PyTorch 2.14.1 CPU index has
Windows ARM64 wheels for those versions, but not Python 3.14. NumPy 2.3.5 also has
matching ARM64 wheels. Native wheel availability is verified, Windows runtime is
still untested. Install Python and its launcher first if absent; setup does not
install Python itself. The launcher selects a compatible installed version:


1. Run `setup_ui.cmd`. It checks Python/architecture and creates `.venv-explorer`.
   Setup installs NumPy 2.3.5 from PyPI and CPU PyTorch 2.14.1 from the official
   [CPU wheel index](https://download.pytorch.org/whl/cpu/torch/).
2. Run `launch_ui.cmd`. It starts the backend and opens
   `http://127.0.0.1:8765` in your browser.
3. Keep the terminal open. Stop with **Ctrl+C** or close its terminal.

The first setup needs an Internet connection for dependencies. Later launches
load the repository's checksummed checkpoint archive and development fixtures
offline. No Node installation, frontend build, CDN, login or cloud account is
needed. Setup requests binary wheels only, refuses to reuse an environment from another
Python/architecture, and does not train or open the UI automatically. If Python is missing,
install Python matching the architecture/version above, including its launcher. If installation fails, read the terminal
error, check network/wheel availability, and rerun setup. If the port is occupied,
stop the previous process or choose another port with the CLI.

On x64 Linux:

```bash
python3 scripts/setup_explorer.py
.venv-explorer/bin/python -m research.post_decision_value.explorer --open
# Optional non-default local port:
.venv-explorer/bin/python -m research.post_decision_value.explorer --port 8766
```

`python3 scripts/setup_explorer.py --check` only checks prerequisites. The server
rejects non-loopback binding. It accepts only its exact loopback Host, same-origin
POSTs with a per-process token, bounded JSON bodies, and fixed static paths. This
is a local research server, not a hosted multi-user application.

**Actually tested:** fresh setup/install and API startup on Linux x86_64,
CPython 3.12.14, Torch 2.14.1+cpu, NumPy 2.3.5; real-checkpoint, accounting and HTTP
integration tests; JavaScript syntax and static DOM contracts. The small extracted package also passes independent inference/simulator startup.
**Not tested:**
Windows execution or rendered desktop/mobile interactions. The available cloud
browser returned `ERR_CONNECTION_REFUSED` for workspace localhost; no rendered
screenshots are claimed. The repository's prohibited Sites preview was not used.

## Using the four views

**State & value** starts with a known development Treasury fixture and simulation
off. The train/validation fixtures include profitable, overpriced, fee-erased and
cash-constrained controls. The untouched fresh-test split is deliberately excluded.
Choose a UTC time and remaining horizon; received history stops at that timestamp.
A portfolio edit describes hypothetical inventory **at that time**, not a backdated
trade. It does not manufacture historical coupon receipts. The original benchmark
stays BTC 1 / USD 10,000 with equal positive-growth weights, loss aversion 10,
10% holding floors and failure penalty 1. Collateral restricts cash but is not an
expense. Dated liability amounts are nonpositive, in native BTC/USD.

Add multiple signed native-quantity orders. Working and pending-create rows form
the current state; candidate rows form the new instruction. Choose create, amend,
cancel, batch or wait and specify target IDs where needed. Amend/cancel retains
resources until reports. Admission uses the existing engine's native lot/tick,
cash, holding-floor, dated-funding and uncertainty checks (at most six variants).
A sell needs owned cash inventory; futures use signed positions. SPOT ownership
is the BTC balance, not a separate position. Explicit SPOT buys can repurchase BTC;
closing does not automatically repair BTC holdings.

The value is real `TreasuryValue.predict(encode(...))` using checkpoint normalization
buffers. It sees only the observable immediate post-state, before arrivals/fills.
The quantity/limit grid compares a single new order against wait, conditional on
existing orders. It does not combine grid cells into a portfolio or substitute for
the candidate portfolio editor. Change the remaining horizon and rebuild the grid
for another surface. Prediction, reference and signed-error views share the same
cells; infeasible orders and unavailable references remain distinct.

| Display | Meaning / availability |
|---|---|
| Learned V̂ | Actual scalar checkpoint target; published target is `diagnostic-hold-boundary-v1` |
| Matching reference / signed error | Independent diagnostic arithmetic only for unchanged built-in fixture cash/hold, original 5/25/60-unit fixed-price purchase through maturity, or matched owned-inventory H=0 boundary |
| L_trade | Current portfolio closed on a copy using ex-post subsequent prints and contractual receipts, atomic cancellation, bounded two-day tail; closing duration ignored |
| Finite toy optimum | Separate exact two-opportunity fixed-price quantity grid (60-unit cap), only at an unchanged initial built-in fixture state; not the diagnostic label |
| Sampled max–min reference | Unavailable for edited states; no matching completed rollout labels are invented |
| Forward replay | One realized path under hold or the frozen network, not a guarantee, max–min estimate or oracle-controlled policy |

Changing cash, liabilities, instrument terms, date, orders or market law can move
outside diagnostic support. The UI marks encoded edited states unvalidated unless
a matching diagnostic reference exists. Intermediate pending/cancel horizons remain
unvalidated. Liabilities and a multi-instrument universe cannot be encoded by this
single-BILL model: inference is unavailable while accounting/hold replay still work.
Imported datasets never acquire the built-in toy oracle, even if their IDs match.

**Market simulation** is opt-in. Check Enable, change parameters, then press
Generate. Checking the box alone does not generate or replace data; unchecking
returns to the first development fixture. Full mode includes BILL, SPOT and a
native linear or inverse FUTURE. The displayed hash and export identify the exact
configuration, instruments, trade/funding tape and allocation windows. A bounded
JSON importer verifies SHA-256, timestamps, native units and provenance. Indicative
records are non-executable; backdated executable prints are rejected. Import is
for the documented bundle format, not an arbitrary CSV/history downloader.

**Forward replay** is a separate button. It submits the selected initial instruction
then either holds, or repeatedly uses the frozen network on its declared fixture
candidate domain. Horizon counts down to one fixed deadline. Hold processes every
exchange event without artificial policy wakeups. Network replay preserves the
published event-trigger clock/action domain and stops at 200 decisions, 30,000
strategic/closing events or an 8-second cooperative wall budget. The known churn
can therefore end in an explicit incomplete result with **no utility label**.
The source path is fixed; the seed changes execution/report jitter. Hidden events,
received events, decisions, fills, cash and inventory are separate diagnostic
outputs; closing appears in a separate tail. Export retains the full bounded
trace (the visible table shows at most 500 rows). This is one path, not a confidence
interval or repeated-replica robustness study.

**Checkpoint** includes the bundled published diagnostic and compatible user scalar
files loaded during this session. The explicit download control retrieves the
immutable published archive, checks the known size/hash, reads only five inference
members, caches the archive and loads the real weights. It never executes archived
source or extracts paths. Local .pt files require an expected SHA-256; loading uses
`weights_only=True`, bounded ZIP/member sizes, strict tensor shapes, finite positive
scales, compatible feature/target versions, no optimizer and no global RNG change.
User-file acceptance is always unverified. Legacy Transformer files are explicitly
unsupported by this first UI; their expected-value semantics are not relabeled.
The active model is unchanged on verification failures. Closing the process removes
session-only user models/datasets. Save state, market and replay JSON from the UI
when needed. The published cache defaults to `%LOCALAPPDATA%/keep-and-lease-explorer`
on Windows or `~/.cache/keep-and-lease-explorer` on Linux; override with `--cache`.

## Synthetic market law

`research/post_decision_value/market_simulation.py`, version `synthetic-market-v1`,
provides `generate(SimulationConfig(enabled=True, ...))`, `select_market(existing,
configuration)` and a native `MarketBundle.scenario(seed)` interface for bounded
collector consumers. `select_market` returns the **identical existing object** when
disabled; there is no fallback to generated data when real input is missing.
The generator is not enabled in the historical reader or existing learning campaign.
No new weights were fitted to this market law.

At time step Δt in years, spot follows
`S_next = S * exp((mu - sigma²/2)*Δt + sigma*sqrt(Δt)*z)`.
Up/flat/down select `mu = +trend_annual / 0 / -trend_annual`. With volatility,
flat means zero drift, not a constant path. Independent counter-keyed Gaussian
streams make one seed reproducible; adding instruments does not change spot/rate/
premium paths. Rates and premiums mean-revert with `rho = exp(-k*Δt)`, innovation
`vol*sqrt(Δt)*z`, and explicit clipping to [-5%,25%] and [-50%,50%]. There is no
historical calibration or fitted volatility claim.

The bill mid is `100*exp(-rate*time_to_maturity)` with a known $100 receipt at day 28.
The future mid is `spot*exp((rate+premium)*time_to_expiry)`. Thus basis converges as
expiry approaches. SPOT shares the same underlying index. Each step emits explicit
buy/sell synthetic prints around mid using the declared spread. Liquidity scales
positive lognormal finite print capacity. The normal engine fills opposing prints
strictly through posted limits, at those limits, with native lot rounding and fees;
closing uses subsequent printed prices. Print capacity is not inferred market depth.

A positive daily funding rate debits longs and credits shorts: `-q*price*rate` USD
for linear contracts, `-q/price*rate` BTC for inverse contracts. The event uses actual
inventory at that instant, precedes same-time trades, and reports later through
FIFO latency. The closing copy also pays intervening funding before position close.
Payments are idempotent per symbol/date. No idle USD interest or automatic futures
settlement/spot bridge is invented. Default future expiry is day 35, beyond the
28-day window and 2-day tail; unresolved positions without closing prints are
incomplete. The bill receipt is contractual simulated cash, not external settlement
evidence. Defaults: 6-hour steps, 20% annual spot volatility, 4% rate, -4% premium,
5 bps fees, 4 bps spread, unit liquidity, zero funding. All quantities are native.

Generate an export directly (explicit activation required):

```bash
.venv-explorer/bin/python -m research.post_decision_value.market_simulation \
  --enabled --output /tmp/treasury-market.json
# Optional JSON contains SimulationConfig fields:
.venv-explorer/bin/python -m research.post_decision_value.market_simulation \
  --enabled --config my-market-config.json --output /tmp/treasury-market-custom.json
```

Generation refuses existing output paths and caps rows. HTTP import bodies are at
most 8 MB, market bundles at most 10,000 records/16 instruments/60 days, checkpoint
files at most 2 MB and decompressed checkpoint members at most 8 MB. Surface grids
have at most 63 cells. Expensive work is serialized locally; a second concurrent
calculation receives a busy error. These are diagnostic limits, not production SLAs.

## Verification and remaining work

Validation receipt: [explorer-validation.json](explorer-validation.json). The initial implementation had **266 tests
passed**: 183 research (including 30 explorer/simulator tests) and 83 existing
funded-ledger/transfer/execution regressions. A fresh installed CLI successfully
served actual inference over HTTP, and an actual immutable download verified all
2,329,910 bytes against the published SHA-256. No training campaign was started. The subsequent Windows package adds three
platform/distribution tests, including actual inference from the extracted ZIP.

Tests cover opt-in identity preservation; reproducible and changing seeds; shared
spot paths; drift/maturity; native linear/inverse signed funding and delayed reports;
funding in closing tails; duplicate/unit/time/provenance rejection; offline real
checkpoint loading and direct-inference equality; no optimizer/RNG mutation;
future-tape isolation; owned boundaries; unsupported references; working/pending/
amend/cancel admission; finite surfaces; capped churn without labels; full-market
closing; verified download/cache behavior; and HTTP origin/token/body/path checks.

Run from the checkout:

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  .venv-explorer/bin/python -m unittest discover -s tests/post_decision_value -v
.venv-explorer/bin/python -m unittest tests.test_funded_ledger \
  tests.test_paired_transfer_economics tests.test_paired_execution_study -v
node --check research/post_decision_value/explorer_web/app.js
```

Remaining: rendered browser/Windows acceptance, legacy Transformer UI support,
matching sampled-search reference retrieval, repeated-replica UI evaluation,
train-only market-law calibration/stress-training study, horizon-policy comparisons,
and fixing/validating the repeated network policy. None is claimed complete here.
