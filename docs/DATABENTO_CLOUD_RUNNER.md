# Bounded Databento cloud research

The owner reported granting the existing `keep-lease-codex-operator` identity
access to Secret Manager secret `databento-api-key` on October 5, 2026. The
`databento-research.yml` workflow uses the existing GitHub OIDC connection on
`agent/cloud-autonomous-access`. Live secret access and encrypted result return were verified by run 37312663540.
Its combined September download estimate was $0.107625976205.
This operator addition runs research on a GitHub-hosted runner authenticated to
GCP; it is not a Cloud Run service, deployment, or a trading connection.

## Scope and purchase controls

A push changing only `.cloud-agent/requests/databento-research.json` triggers the
workflow. Requests accept `estimate` or `screen` only. The screen implementation
is pinned to reviewed commit `a48da25628a211194b73bbc09026a9f152627d84`.
Both actions use September 1 through October 1 exclusive for `SICZ6`/SLV and
`MBTV6`/IBIT, one contract each, Nasdaq ETF quotes and CME futures.

`estimate` retrieves metadata only. `screen` checks the combined cumulative
Databento estimate against a hard $1 ceiling before acquiring any market data.
This counts prior reserved acquisitions restored from the private cache. It is
not a vendor invoice limit or a query of remaining signup credits. Metadata-only server errors have at most three attempts; paid streaming requests
are never retried automatically. No MBO,
trades, arbitrary commands, other secrets, URLs or contract selections are
accepted by the request. The workflow has a 25-minute timeout and serializes all
requests through one concurrency group.

Private cache objects live under:
`gs://keep-and-lease-market-data/research/databento/september-2026-v1/`.
Raw data is content-addressed and immutable. Every acquisition writes an
append-only state before contacting the paid API. After download, raw data is
uploaded before the completed-state checkpoint. An uncertain or missing cache
stops rather than automatically purchasing again. This uses existing object
creator/viewer roles without requiring overwrite or delete permissions.

The separate gold Cloud Shell cache is not part of this fixed two-contract job.

## References and interpretation

Each `screen` request explicitly supplies `units_per_share`, `as_of` and `source`
for both ETF snapshots. These are **constant snapshot scenarios**, not daily
historical holdings. In particular, an October 2 snapshot applied to September
is retrospective and must not be described as a causal historical strategy
return. The job fetches FRED DGS3MO for the period and uses the latest prior
observation beginning the next UTC day. This is a three-month Treasury-yield
proxy with simple ACT/365 accrual, not a locked financing rate or a matching
one-month MBT funding instrument.

Entry fees remain the reviewed presets' zero defaults. The main output is a
sampled BBO indication; it does not demonstrate simultaneous execution. The
report includes distributions, coverage, positive sample fractions, common-
timestamp comparisons, break-even cash-rate quantiles, and constant 0/3/4/5%
cash-rate sensitivities. Settlement basis, margin, exit costs and ETF content
changes remain outside this preliminary screen.

## Confidential result return

The request contains an RSA public key (at least 3072 bits). The matching
private key stays in the requesting agent's private workspace; it is never sent
to GCP, GitHub, a workflow, or the repository. A fresh AES-256-GCM key encrypts
the result; RSA-OAEP-SHA256 wraps that key. Only this encrypted envelope is
published as a seven-day GitHub artifact. The artifact contains no raw DBN or
sample files. It includes the restored stream status/request metadata and
reserved estimate to diagnose acquisition failures without another purchase. Public logs show request ID and completion state only. SDK output
is captured in memory; outer errors return type and HTTP code. Databento errors are key-redacted
before inclusion in the encrypted envelope. Credentials are neither logged nor included
in the encrypted result. Complete summaries and samples remain in private GCS.

This is a fixed research return mechanism, not a general private diagnostic or
saved-backtest export interface. Existing operator request restrictions remain.

## Request example

```json
{
  "schema_version": 1,
  "request_id": "september-cost-check",
  "action": "estimate",
  "result_public_key_pem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----\n"
}
```

A screen additionally requires `references` with exactly `sic` and `mbt` entries,
each containing `units_per_share`, `source`, `as_of`. Use a new request ID for
each execution. There is no scheduled polling. Read workflow status and decrypt
the compact result after completion.

## IAM ownership and installation

The manual secret-level grant is represented by
`google_secret_manager_secret_iam_member.codex_databento_reader` in foundation
Terraform. This patch does not apply Terraform or broaden permissions itself.
If the manual grant is not yet tracked in foundation state, adopt it using the
normal authenticated foundation workflow before applying a reviewed plan.

Operator-only workflow installation uses `[skip ci]` to preserve the shared
application preview. The subsequent request-only push starts the research
workflow without triggering an application deployment. No master merge or GUI
change is part of this operational addition.

Validation: seven offline tests cover request limits, authenticated encryption
round-trip, write-ahead state/raw-file ordering, metadata-only retries, and the
reviewed recovery partitions. Run:
`python -m unittest discover -s tests -p 'test_cloud_databento_research.py'`.

## Reviewed MBT gateway-timeout recovery

Run 37313440074 completed SIC and persisted its private results, then returned
Databento HTTP 504 on the monthly MBT futures definition request. In SDK 0.87.0,
`check_http_error` executes before the DBN writer is opened; this is distinct
from an interrupted data stream. The failed monthly request was reviewed, not
silently retried. A screen may specify `reviewed_recovery_run: 37313440074` to
replace that exact request with six disjoint five-day ranges. Its original cost
reservation remains counted in the combined $1 ceiling, conservatively alongside
the new estimates. The original state records the reviewed run and reason. Any
uncertain partition stops as before; this is not a general retry permission.
SIC reuses its completed cache. Seven focused runner tests now pass.

The read-only cache diagnosis in run 37315520848 confirmed that both MBT/IBIT
BBO files were complete and the timeout affected `future-definition`. Recovery
partitions only that definition stream and reuses both completed price files.
