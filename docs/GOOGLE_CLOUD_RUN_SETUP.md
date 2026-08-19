# Google Cloud Run deployment design and implementation state

## Current deployed foundation — 2026-08-19

The Google Cloud foundation is now provisioned and verified for Keep & Lease.

- Google Cloud project: `keep-and-lease` (project number `989708711229`).
- Primary region: Tel Aviv `me-west1`.
- Billing is linked and required APIs are enabled.
- Terraform configuration: `infra/gcp/`.
- Terraform remote backend: `gs://keep-and-lease-terraform-state/foundation`.
- Terraform state bucket has uniform bucket-level access, public-access prevention,
  and object versioning enabled.
- Artifact Registry: `me-west1-docker.pkg.dev/keep-and-lease/keep-and-lease`.
- Market-data bucket: `gs://keep-and-lease-market-data`.
- Result bucket: `gs://keep-and-lease-results`, with a 90-day lifecycle rule.
- Firestore Native `(default)` database: `me-west1`.
- Runtime identities:
  - `keep-lease-web@keep-and-lease.iam.gserviceaccount.com`;
  - `keep-lease-worker@keep-and-lease.iam.gserviceaccount.com`.
- Deployment identity: `keep-lease-github@keep-and-lease.iam.gserviceaccount.com`.
- GitHub Workload Identity provider:
  `projects/989708711229/locations/global/workloadIdentityPools/github/providers/github`.
- GitHub OIDC authentication has been tested successfully from GitHub Actions;
  no service-account JSON key is stored.
- Repository Actions variables are used for the project, region, provider, and
  deployment identity. These values are configuration, not secrets.

A post-migration `terraform plan` reports no changes. The persistent cloud
foundation and remote state are therefore the current source of truth.

## Reproducible bootstrap

The account owner must create/link the project and billing account. Then run
`scripts/gcp-bootstrap.sh`, which enables the required APIs including Cloud
Resource Manager. The Terraform state bucket is a bootstrap resource because the
GCS backend must exist before Terraform can initialize against it.

Create it once with:

```bash
gcloud storage buckets create gs://keep-and-lease-terraform-state \
  --project=keep-and-lease --location=me-west1 --uniform-bucket-level-access
gcloud storage buckets update gs://keep-and-lease-terraform-state \
  --public-access-prevention=enforced
gcloud storage buckets update gs://keep-and-lease-terraform-state --versioning
```

Then:

```bash
cd infra/gcp
terraform init
terraform plan
terraform apply
```

For migration from an existing local state, use `terraform init -migrate-state`.
Never commit `terraform.tfstate`, credentials, or private variable files. Commit
`.terraform.lock.hcl` so provider selection is reproducible.

## Target application architecture

The target remains two independently scalable workloads:

| Component | Cloud Run product | Initial resources | Purpose |
|---|---|---:|---|
| Web | Cloud Run service | 1 vCPU, 1 GiB | GUI, validation, submission, status, result access |
| Calculation | Cloud Run Job | 1 vCPU, 4 GiB | One durable backtest execution |
| Market/result storage | Cloud Storage | usage based | Versioned analytical inputs and compressed results |
| Job metadata | Firestore | usage based | Durable status, progress, hashes, ownership, result pointer |
| Images | Artifact Registry | usage based | Immutable web and worker images |
| Build/deploy | GitHub Actions + OIDC | usage based | Keyless tested deployments |

Both Cloud Run workloads must scale to zero. The worker starts with one task,
1 vCPU, 4 GiB memory, a 30-minute timeout and no automatic retry until execution
is proven idempotent.

## Why the existing API cannot simply be deployed

The current server starts a background Python thread and retains job status and
results in process memory. A Cloud Run service instance can disappear after a
request, so this is not durable.

The next implementation must preserve the HTTP contract while replacing process
memory with durable interfaces:

1. `POST /api/v1/backtests` validates parameters and creates a Firestore `queued`
   record.
2. The web service starts the named Cloud Run Job with a job ID and immutable
   version identifiers.
3. The worker changes the record to `running`, loads market data, executes the
   canonical strategy and publishes bounded progress.
4. The worker writes a compressed result to Cloud Storage and atomically records
   `completed`, checksum, result URI, timing and peak RSS in Firestore.
5. `GET /api/v1/backtests/{id}` reads durable status.
6. `GET /api/v1/backtests/{id}/result` authorizes and streams the stored result.
7. Failures, interruption and cancellation must become durable actionable states.

The web service must not load complete market histories.

## Storage and data direction

Use immutable, versioned calculated-ready market data under
`gs://keep-and-lease-market-data`. Raw source archives remain available for audit,
but ZIP parsing should not be the normal calculation path. The planned analytical
format is partitioned Parquet queried with DuckDB, projecting only required dates,
commodities and columns and converting to Arrow/NumPy structures rather than
per-cell Python objects.

Results live under `gs://keep-and-lease-results/jobs/<job-id>/`. Every completed
result records the exact engine commit/image digest, data-manifest hash, parameters
and result checksum.

## Identity boundaries

The web identity may update job metadata, execute only the calculation Job and read
result objects. The worker may read market data, update its job metadata and write
results. The GitHub deployment identity may deploy Cloud Run workloads, push images
and impersonate only the two runtime identities as required for deployment.

The existing Terraform foundation establishes the initial IAM bindings. Tighten
roles further as application calls become concrete. Production must add application
authentication, parameter/result limits, quotas and abuse controls before exposing
billable job creation publicly.

## Next implementation sequence

1. Add a cloud-neutral durable job/result abstraction while preserving the current
   API contract and local/test implementation.
2. Implement Firestore job metadata and Cloud Storage result adapters.
3. Split web and worker entry points; the worker must execute one supplied job and
   exit.
4. Add the web-to-Cloud-Run-Job launcher and cancellation path.
5. Add worker peak-RSS/stage timing and durable heartbeat/lease handling.
6. Add separate web/worker container images.
7. Add Terraform Cloud Run service and Job resources with least-privilege IAM.
8. Add GitHub Actions build/push/deploy using the verified OIDC identity.
9. Deploy a private proof of concept and run a bounded numerical smoke test.
10. Introduce versioned Parquet ingestion and DuckDB/Arrow market access.
11. Benchmark cold start, data retrieval, calculation, serialization, memory and
    billed time; compare `me-west1` with a European region if useful.
12. Add budgets/alerts, authentication, quotas, retention checks and rollback, then
    validate scale-to-zero and repeat-run caching.

## Acceptance criteria

The deployment is acceptable only when jobs/results survive container replacement,
a cold submission requires no manual wake-up, the intended commodity set stays
below 80% of worker memory, canonical numerical fixtures match within documented
tolerances, exact code/data/parameter/result provenance is recoverable, interrupted
jobs have durable status, and budgets/authentication/quotas/rollback are tested.

## Operator checks

Useful verification commands:

```bash
cd infra/gcp
terraform init
terraform state list
terraform plan
terraform output
```

The expected steady-state plan is `No changes. Your infrastructure matches the
configuration.` The manual `.github/workflows/gcp-identity-check.yml` workflow can
be used after it is available on the default branch to verify GitHub federation.

## Teardown

Do not make deletion of canonical data or Terraform state an implicit application
teardown step. Export required results first. Cloud Run workloads and temporary
application resources may be destroyed separately; raw data, published manifests,
required analytical versions, audit information and Terraform state require an
explicit retention decision.
