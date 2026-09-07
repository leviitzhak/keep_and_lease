# BTC preview connection recovery

On 7 September 2026, a user reported an all-BTC run reaching the server's
`running` stage at approximately 101 seconds, with status observations through
127 seconds, followed by `Failed to fetch` and a failed browser retry at 925
seconds. The report contained no job ID or HTTP response status.

## Findings and limits

The previous adapter had no client deadline for fetch/body reads. A single
failed status GET abandoned polling and started the entire calculation in a
Pyodide worker. The Cloud Run web image does not include that worker or its
runtime/data; its public config nevertheless allowed automatic fallback.
These are confirmed defects in request recovery and error reporting.

The log does not establish whether the original interruption was a network
failure, browser suspension, IAP reauthentication, or a server-side issue.
It does not establish that the calculation worker failed, exceeded its memory
limit, or needed GCS input access. The GUI still runs bundled minute data;
the isolated Parquet pilot and its pending market-bucket upload are not used.
User jobs are owner-scoped; the diagnostic operator cannot read another user's
job by changing identities. No access-control bypass or resource increase is
part of this fix.

## Behavior

- Status/health requests have a 30-second client timeout, including body reads.
  Job creation has a 60-second timeout and is not automatically repeated: a
  missing response can conceal a successful submission.
- Status reads retry network failures, timeouts and HTTP 408/429/500/502/503/504
  up to five total attempts, with bounded exponential waits of 1/2/4/8 seconds.
  Progress identifies reconnection and the job ID.
- Result downloads have a 240-second per-attempt timeout and at most two
  attempts. Only the immutable result is fetched again; the strategy is not
  recalculated. A sufficiently slow connection can still exceed this deadline.
- A disconnected job is retained in the page's worker. Pressing Run with
  unchanged parameters reconnects without another POST. This retention ends on
  page reload; the cloud repository separately deduplicates submissions by
  owner, parameters and engine/data provenance. Completed durable results can
  also be restored through the existing latest-result mechanism.
- Sign-in failures (401/403 or a redirect) stop retries and explain the need to
  sign in. Terminal calculation errors remain visible with the job ID.
- After server execution is selected, a failed run never automatically starts a
  browser calculation. Cloud Run explicitly advertises `browserFallback: false`.
  Static deployments can retain browser initialization where that runtime exists.
- Strategy execution intervals, prices, fees, accounting and output resolution
  are unchanged.

The eight adapter regressions simulate network/status failures, stalled body
reads, exhausted retries and reconnection, interrupted result streams, auth
failures, terminal worker failure, ambiguous submission, and unavailable fallback.
They validate recovery logic; they do not recreate the user's original network.
The feature branch now also runs the existing authenticated full BTC minute
acceptance, audit/detailed-plot checks and one-day spreadsheet download. The PR
records the exact deployed revision and outcome; passing this preset does not
establish that every possible BTC parameter set fits the current worker limit.


Local validation passed 34 JavaScript/HTML tests (including the eight new adapter
regressions), 26 Python API/cloud/operator tests, and the bounded production build
with artifact validation. The current Python environment initially lacked
FastAPI; installing the repository-pinned `requirements.txt` enabled the API
checks. Assets were regenerated before fresh-process tests. Cloud adapters in
those Python tests are fakes; the deployment workflow provides live acceptance.
