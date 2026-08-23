# Google Cloud Run deployment design and implementation state

## Current state — 2026-08-23

The Google Cloud foundation is provisioned and verified. The durable application
split, containers, workload Terraform, and keyless deployment workflow are
implemented. The private web service and calculation Job were first deployed from
commit `fc4400e9a18a4e68846f250b64efee7fc0429ad7`; the production workflow now
deploys `master`, currently verified by the private operator at commit
`08b583696f52314b54e3be6bd6f1d39497b10a1c` (application version `1.3`).
The branch-restricted keyless operator has been applied and verified end-to-end:
the API returned `status=ok` and the private GUI rendered with HTTP 200. Direct
Cloud Run IAP for approved human users is documented below but is not yet enabled.
Bounded calculation, cancellation, and replacement acceptance tests remain.

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
- Autonomous operator identity:
  `keep-lease-codex-operator@keep-and-lease.iam.gserviceaccount.com`, with GitHub
  impersonation restricted to `refs/heads/agent/cloud-autonomous-access`.
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
  default. Its `run.app` URL returning `403 Forbidden` in an unauthenticated browser
  is expected. Do not make billable submission anonymous before application
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

### 3. Open the private GUI

The deployed service URL is currently
<https://keep-and-lease-web-vfk2j2rgoq-zf.a.run.app>. Until browser authentication
is added, use the authenticated Cloud SDK proxy from Cloud Shell:

```bash
gcloud run services proxy keep-and-lease-web \
  --project=keep-and-lease \
  --region=me-west1 \
  --port=8080
```

Leave the command running and select **Web preview > Preview on port 8080** in
Cloud Shell. The proxy attaches the caller's Google identity to requests. This is
an operator path, not a public application URL.

### 4. Bounded operator calculation smoke test

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

## Browser access and public URL plan

“Public URL” has two materially different meanings for this application.

### Planned next change: internet-reachable URL with an approved-user allowlist

Enable [Identity-Aware Proxy (IAP) directly on the Cloud Run
service](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run).
The existing
`https://keep-and-lease-web-vfk2j2rgoq-zf.a.run.app` URL remains reachable from
the internet, but IAP redirects browser users to Google sign-in and admits only
explicitly approved Google identities. Cloud Run remains
`--no-allow-unauthenticated`: this is a public address with private access, not an
anonymous application.

Direct IAP protects every ingress path to the service, including the default
`run.app` URL. A load balancer or custom domain is not required.

#### Identity and role mapping

| Principal | Authentication path | Required access after IAP |
|---|---|---|
| Owner and approved users | Google browser sign-in and IAP session cookie | `roles/iap.httpsResourceAccessor` on this Cloud Run IAP resource |
| Codex operator | Short-lived keyless service-account token issued through GitHub OIDC | `roles/iap.httpsResourceAccessor`; token audience changed to the IAP OAuth client ID |
| Deployment health check | Short-lived keyless deployment service-account token | `roles/iap.httpsResourceAccessor`; token audience changed to the IAP OAuth client ID |
| IAP service agent | IAP forwards an approved request to Cloud Run | `roles/run.invoker` on `keep-and-lease-web` |

The IAP service agent is
`service-989708711229@gcp-sa-iap.iam.gserviceaccount.com`. After the IAP cutover
is verified, the operator's direct `roles/run.invoker` binding can be removed:
IAP, rather than the original caller, invokes the service.

#### Required implementation

1. Enable `iap.googleapis.com` in foundation Terraform.
2. Because project `keep-and-lease` is not attached to a Google organization,
   perform the first IAP/OAuth activation in the Google Cloud console. Configure an
   **External** OAuth audience and let the console auto-generate the project OAuth
   client, or configure an equivalent custom client. Google does not support
   creating that first no-organization OAuth client entirely through Terraform.
3. Record the non-secret IAP OAuth client ID as the GitHub repository variable
   `GCP_IAP_CLIENT_ID`. Do not store the OAuth client secret in the repository,
   GitHub Actions artifacts, or the Codex environment.
4. Set `iap_enabled = true` on `google_cloud_run_v2_service.web` in workload
   Terraform.
5. Grant `roles/run.invoker` on the web service to the IAP service agent.
6. Manage approved users, groups, the Codex operator, and the deployment identity
   with `google_iap_web_cloud_run_service_iam_member` or an authoritative
   `google_iap_web_cloud_run_service_iam_binding`.
7. Update both the deployment health check and
   `.github/workflows/cloud-agent-operator.yml` to request an ID token whose
   audience is `GCP_IAP_CLIENT_ID`, with the service-account email claim included.
   Keep a reviewed direct/IAP mode switch during migration so IAP is not enabled
   before both machine callers are ready.

A Google-managed IAP OAuth client is sufficient for normal browser access. The
planned machine path uses the configured IAP client ID. If a client configuration
does not support that OIDC flow, use Google's documented keyless service-account
signed-JWT path instead; do not introduce a service-account key.

#### Safe cutover order

1. Prepare and review the Terraform and dual-mode workflow changes while the
   service still uses direct Cloud Run IAM.
2. Complete the one-time console OAuth/IAP configuration and record
   `GCP_IAP_CLIENT_ID`.
3. Add the human and service-account IAP allowlist entries and the IAP service-agent
   Cloud Run invoker binding.
4. Enable IAP and switch both machine workflows to the IAP audience.
5. Verify all acceptance cases below before removing the operator's old direct
   Cloud Run invoker binding. If a machine check fails, disable IAP and restore the
   direct audience while correcting the policy; no application data is affected.

#### Acceptance criteria

- an approved Google account opens the existing `run.app` URL and reaches the GUI;
- an unapproved or signed-out browser is denied;
- the Codex operator still obtains health/build evidence and an authenticated GUI
  screenshot without any stored Google key;
- the `master` deployment workflow still completes its private health check;
- the Cloud Run IAM policy contains no `allUsers` or
  `allAuthenticatedUsers` invoker grant; and
- billable calculation endpoints remain behind the same IAP allowlist.

### Truly anonymous GUI

Setting `allow_unauthenticated=true` would immediately remove the `403`, but must
not be done on the current combined GUI/API service: every anonymous visitor would
also reach the endpoint that starts billable calculation Jobs.

Before an anonymous launch, implement and test all of the following:

- split the public static GUI from a private calculation API, with an authenticated
  backend-for-frontend or equivalent trusted service between them;
- end-user authentication, per-job ownership checks, and authorization on status,
  result, and cancellation endpoints;
- strict date/parameter/result limits, per-user and per-IP quotas, bounded concurrent
  Job executions, idempotency, and cache reuse;
- budget and usage alerts, operational dashboards, audit logs, retention cleanup,
  and a tested disable/rollback switch;
- CSRF/CORS/session-cookie and security-header hardening; and
- abuse and authorization-bypass tests in addition to numerical acceptance.

For a custom public hostname, TLS policy, centralized routing, or edge controls,
place a [global external Application Load Balancer with a serverless
NEG](https://docs.cloud.google.com/load-balancing/docs/https/setup-global-ext-https-serverless)
in front and attach Cloud Armor rate-limiting/WAF rules. A load balancer and Cloud
Armor are defense in depth; they do not replace application authentication,
ownership, or spending limits.

Google's [Cloud Run authentication overview](https://docs.cloud.google.com/run/docs/authenticating/overview)
should remain the authority when choosing between IAM service authentication, IAP
browser authentication, and application-managed end-user authentication.

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

- Complete the bounded numerical smoke test and compare its fixture with the local
  canonical engine.
- Verify a result survives web/worker replacement and that a second identical
  request reuses it.
- Exercise queued and running cancellation plus forced worker interruption.
- Confirm stale heartbeat reconciliation and result lifecycle behavior.
- Measure cold start, load, calculation, gzip/upload, download, peak RSS, and billed
  execution time; keep peak RSS below 80% of 4 GiB.
- Add direct Cloud Run IAP and selected-user access if a normal browser URL is
  required before anonymous publication.
- Before any anonymous access, add application authentication, ownership,
  parameter/date/result limits, quotas, budgets/alerts, retention checks, and a
  tested rollback procedure.
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
