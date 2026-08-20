# Google Cloud Run deployment design and implementation state

## Current state — 2026-08-20

The Google Cloud foundation is provisioned and verified. The durable application
split, containers, workload Terraform, and keyless deployment workflow are
implemented. The private web service and calculation Job were first deployed from
commit `fc4400e9a18a4e68846f250b64efee7fc0429ad7`; the authenticated health check
passed. The bounded operator calculation smoke test remains.

### Provisioned foundation

- Google Cloud project: `keep-and-lease` (project number `989708711229`).
- Primary region: Tel Aviv `me-west1`.
- Foundation Terraform: `infra/gcp/`, with remote state at
  `gs://keep-and-lease-terraform-state/foundation`.
- Artifact Registry: `me-west1-docker.pkg.dev/keep-and-lease/keep-and-lease`.
- Market data: `gs://keep-and-lease-market-data` with object versioning.
- Results: `gs://keep-and-lease-results` with a 90-day lifecycle rule.
- Firestore Native `(default)` database in `me-west1`.
- Runtime identities:
  - `keep-lease-web@keep-and-lease.iam.gserviceaccount.com`;
  - `keep-lease-worker@keep-and-lease.iam.gserviceaccount.com`.
- Deployment identity:
  `keep-lease-github@keep-and-lease.iam.gserviceaccount.com`.
- GitHub Workload Identity provider:
  `projects/989708711229/locations/global/workloadIdentityPools/github/providers/github`.
- GitHub OIDC authentication has been tested successfully; no service-account JSON
  key is stored.

The foundation delta is applied. It grants the runtime identities Artifact Registry
read access and creates the protected `gs://keep-and-lease-terraform-workloads`
bucket accessible to the deployment identity for workload state only.

### Implemented application split

| Component | Implementation | Initial resources |
|---|---|---:|
| Web GUI/API | `Dockerfile.web`, `server.app`, `CloudJobService` | 1 vCPU, 1 GiB, scale to zero |
| Calculation | `Dockerfile.worker`, `cloud_worker_main.py`, `WorkerRunner` | 1 vCPU, 4 GiB, one task |
| Job metadata | `FirestoreJobRepository` | Firestore `backtests` and `backtest_cache` |
| Results | `GcsResultStore` | immutable `jobs/<job-id>/result.json.gz` objects |
| Workloads | `infra/gcp/workloads/` | `gs://keep-and-lease-terraform-workloads/cloud-run` state |
| Deployment | `.github/workflows/deploy-google-cloud.yml` | `master` push or manual OIDC build/push/plan/apply/health check |

The local and Render modes retain `JobStore`, the existing in-process queue. Cloud
mode is selected with `KEEP_AND_LEASE_JOB_BACKEND=cloud`; it never starts the
background calculation thread. The web image serves the standalone GUI and v13
server adapter but contains no market archives or Pyodide fallback payload.

## Durable execution contract

1. `POST /api/v1/backtests` validates the versioned parameter document.
2. A Firestore transaction calculates the canonical parameter/provenance hash,
   reuses an active or completed identical job when present, or creates a new
   `queued` record and cache pointer.
3. Only after the record exists, the web identity executes the named Cloud Run Job
   with a per-execution `KEEP_AND_LEASE_JOB_ID` override.
4. The one-shot worker transactionally claims the record, stores its Cloud Run
   execution name and lease owner, changes it to `running`, and starts a durable
   heartbeat.
5. The worker runs the canonical `StrategyEngine` once. It checks that application,
   engine, data-manifest, and worker-image provenance match the submitted immutable
   identifiers.
6. Strict JSON encoding enforces the configured result limit. The worker creates a
   deterministic gzip object with `if_generation_match=0`, CRC32C transport
   checking, and SHA-256 checksums for compressed and uncompressed bytes.
7. A final Firestore transaction records `completed`, the `gs://` result pointer,
   checksums, timings, peak RSS, execution name, and exact provenance.
8. `GET /api/v1/backtests/{id}` reads Firestore. It also converts expired queued
   leases or worker heartbeats into a durable `failed/worker_lost` state.
9. `GET /api/v1/backtests/{id}/result` checks the completed record and streams the
   gzip object from the configured result bucket; the browser receives the same
   canonical JSON object after HTTP decompression.
10. `DELETE /api/v1/backtests/{id}` durably requests cancellation. Queued work is
    cancelled before claim; running work uses the recorded execution name to call
    Cloud Run cancellation and the worker treats SIGTERM during cancellation as a
    durable `cancelled` state.

Launch errors, calculation errors, serialization limits, SIGTERM interruption,
expired heartbeats, cancellation, and rejected remote-cancellation calls are written
to Firestore rather than existing only in container memory. Logs are bounded to the
latest 100 stage messages.

Cloud Run has no automatic worker retry initially. Result creation is immutable,
but a complete retry/reconciliation policy must be proven before enabling platform
retries.

## Identity boundaries

- The web identity can read/update job metadata, read result objects, and execute or
  cancel only `keep-and-lease-calculation` with per-run overrides.
- The worker identity can read market data, read/update job metadata, and create
  result objects.
- The GitHub identity can push images, manage Cloud Run workloads, impersonate only
  the web/worker runtime identities for deployment, and access the dedicated
  workload Terraform state bucket without access to foundation state.
- The first web service is private. `allow_unauthenticated=false` is the Terraform
  default. Do not make billable submission public before application
  authentication, quotas, and abuse controls exist.

The runtime Firestore permission is currently the predefined `roles/datastore.user`
role, which is broader than per-collection access. Revisit it if custom IAM support
or a separate metadata project becomes worthwhile.

## Container provenance

The deployment workflow builds two images from the same commit, pushes SHA-tagged
images, resolves their Artifact Registry digests, and supplies digest-qualified
references to Terraform. It also calculates a deterministic hash over the current
calculation-ready archives and rate files.

The web writes the worker digest, engine commit, data hash, and application version
into every request hash. The worker receives its own digest as runtime
configuration and refuses a mismatch. Completed metadata therefore identifies the
exact code, data, parameters, and result bytes.

## Deployment and acceptance

### 1. Maintain the foundation IAM delta

The initial delta was applied on 2026-08-20. For future foundation changes, run as
the project owner from an authenticated Cloud Shell checkout:

```bash
cd ~/keep_and_lease
git pull
cd infra/gcp
terraform init
terraform fmt -check
terraform validate
terraform plan
terraform apply
```

The foundation state remains under `foundation`; Cloud Run resources use the
separate protected workload-state bucket.

### 2. Run the GitHub workflow

A push to `master` runs **Deploy Google Cloud workloads** automatically. The
workflow also retains `workflow_dispatch` so a reviewed commit can be deployed
manually. It:

1. authenticates with the existing OIDC provider;
2. builds and pushes separate web/worker images;
3. resolves immutable digests;
4. initializes `infra/gcp/workloads/` against the dedicated workload-state bucket;
5. runs `terraform fmt -check`, `validate`, `plan`, and `apply`;
6. mints a short-lived identity token for the deployed service's exact audience
   through the existing GitHub OIDC trust, then invokes the private health
   endpoint; and
7. publishes the URI and immutable image references in the workflow summary.

Required repository Actions variables remain:

- `GCP_PROJECT_ID=keep-and-lease`
- `GCP_REGION=me-west1`
- `GCP_WORKLOAD_IDENTITY_PROVIDER=projects/989708711229/locations/global/workloadIdentityPools/github/providers/github`
- `GCP_DEPLOY_SERVICE_ACCOUNT=keep-lease-github@keep-and-lease.iam.gserviceaccount.com`

These are identifiers, not secrets.

### 3. Private operator smoke test

From an identity with Cloud Run invoke permission:

```bash
WEB_URI="$(gcloud run services describe keep-and-lease-web \
  --region=me-west1 --format='value(status.url)')"
TOKEN="$(gcloud auth print-identity-token)"

curl --fail --header "Authorization: Bearer ${TOKEN}" \
  "${WEB_URI}/api/v1/health"

curl --fail --header "Authorization: Bearer ${TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{"schema_version":1,"parameters":{"weight_silver":100}}' \
  "${WEB_URI}/api/v1/backtests"
```

Poll the returned `status_url` with the same token, download `result_url`, verify
the SHA-256 header against the decompressed bytes, and compare a bounded fixture to
the local canonical engine before treating the deployment as accepted.

## Terraform operator checks

Foundation:

```bash
cd infra/gcp
terraform init
terraform state list
terraform plan
terraform output
```

Workloads require the exact images that are in state. Normally inspect them through
the GitHub workflow. For a manual plan:

```bash
cd infra/gcp/workloads
terraform init
terraform state show google_cloud_run_v2_service.web
terraform state show google_cloud_run_v2_job.calculation
terraform output
```

Do not run a workload plan with invented image variables: doing so proposes a new
revision. Read the current digest-qualified image values from state or Artifact
Registry.

## Data direction and current limitation

The deployed worker image currently carries the repository's small calculation-ready
ZIP/CSV set so the first durable numerical proof can reproduce the existing engine
without changing formulas and data access simultaneously. The provisioned market
bucket is ready but is not yet the normal read path.

The next data phase remains immutable versioned Parquet under
`gs://keep-and-lease-market-data`, projected with DuckDB/Arrow by required dates,
commodities, and columns. Raw source archives remain available for audit. This
migration must create a manifest and numerical equivalence fixtures before the
bundled inputs are removed.

The synchronous `POST /api/v1/inspections` endpoint also remains local/Render-only;
the scale-to-zero web service returns `503` because it must not load full market
histories. Cloud inspection should be derived from a completed result or submitted
as a durable operation in a later API version.

## Remaining acceptance work

- Deploy the private service and Job and run the bounded numerical smoke test.
- Verify a result survives web/worker replacement and that a second identical
  request reuses it.
- Exercise queued and running cancellation plus forced worker interruption.
- Confirm stale heartbeat reconciliation and result lifecycle behavior.
- Measure cold start, load, calculation, gzip/upload, download, peak RSS, and billed
  execution time; keep peak RSS below 80% of 4 GiB.
- Add application authentication, ownership, parameter/date/result limits, quotas,
  budgets/alerts, retention checks, and a tested rollback procedure.
- Migrate calculation-ready inputs to versioned Parquet/DuckDB/Arrow.
- Restore cloud day inspection without loading histories in the web service.

## Reproducible foundation bootstrap

The account owner must create/link the project and billing account. Then run
`scripts/gcp-bootstrap.sh`. The Terraform state bucket is a bootstrap resource
because the GCS backend must exist before Terraform can initialize:

```bash
gcloud storage buckets create gs://keep-and-lease-terraform-state \
  --project=keep-and-lease --location=me-west1 --uniform-bucket-level-access
gcloud storage buckets update gs://keep-and-lease-terraform-state \
  --public-access-prevention=enforced
gcloud storage buckets update gs://keep-and-lease-terraform-state --versioning
```

For migration from local state, use `terraform init -migrate-state`. Never commit
state, credentials, or private variable files. Commit `.terraform.lock.hcl`.

## Teardown

Do not make deletion of canonical data or Terraform state an implicit application
teardown step. Cloud Run workloads can be destroyed independently from
`infra/gcp/workloads/`. Raw data, manifests, required results, audit metadata, and
both Terraform state buckets require an explicit retention decision.
