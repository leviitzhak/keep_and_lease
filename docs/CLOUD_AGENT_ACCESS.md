# Keyless cloud-agent access

## Purpose

This workflow lets a Codex cloud chat inspect the private Keep & Lease Cloud Run
GUI/API without putting a Google service-account key in the agent environment and
without making the service anonymous.

The control path is:

1. Codex writes a bounded JSON request to the permanent
   `agent/cloud-autonomous-access` GitHub branch.
2. A path-restricted GitHub Actions workflow authenticates to Google Cloud through
   the existing GitHub OIDC provider.
3. The workflow impersonates
   `keep-lease-codex-operator@keep-and-lease.iam.gserviceaccount.com`.
4. The operator calls the private Cloud Run origin with a short-lived,
   audience-bound identity token.
5. Health, build metadata, sanitized fixed-fixture backtest status, and an
   authenticated Playwright screenshot are uploaded as a one-day workflow
   artifact.
6. Codex reads the workflow result and artifacts through the connected GitHub app.

The Google identity token exists only inside the GitHub runner. It is never stored
in the repository, a GitHub secret, an artifact, or the Codex agent filesystem.

## Least-privilege identity

`infra/gcp/codex_operator.tf` creates a dedicated service account with only:

- `roles/run.invoker` on `keep-and-lease-web`;
- `roles/iam.workloadIdentityUser` for the exact GitHub ref
  `refs/heads/agent/cloud-autonomous-access`.

It has no direct Firestore, Cloud Storage, Cloud Run Job execution, deployment,
Artifact Registry, Terraform-state, or service-account administration access. A
billable calculation can only be requested through the same guarded web API used
by a normal application caller.

## One-time activation

After reviewing the implementation branch, apply the foundation delta once from
an authenticated Cloud Shell checkout of that branch:

```bash
cd ~/keep_and_lease
git fetch origin
git switch agent/cloud-autonomous-access
git pull --ff-only
cd infra/gcp
terraform init
terraform fmt -check
terraform validate
terraform plan
terraform apply
```

The plan should add one service account and two IAM bindings. It must not replace
the web service, calculation Job, buckets, Firestore database, or GitHub deployment
identity.

No new GitHub secret is required. The workflow reuses the existing identifier
variable `GCP_WORKLOAD_IDENTITY_PROVIDER`.

## Submitting an autonomous request

Create or replace `.cloud-agent/requests/current.json` on the operator branch. A
non-billable GUI/API inspection looks like:

```json
{
  "schema_version": 1,
  "request_id": "deployed-health-gui",
  "actions": ["health", "gui"]
}
```

Pushing that one path starts **Cloud agent operator**. The workflow does not accept
shell commands, arbitrary URLs, arbitrary artifact paths, or arbitrary Google Cloud
queries.

An API calculation is opt-in and must state that it is billable:

```json
{
  "schema_version": 1,
  "request_id": "bounded-silver-smoke",
  "actions": ["health", "backtest"],
  "backtest": {
    "confirm_billable": true,
    "fixture": "silver-default",
    "timeout_seconds": 360,
    "poll_seconds": 10,
    "verify_result": false
  }
}
```

Because this is a public repository, the operator accepts only reviewed smoke
fixtures defined in `scripts/cloud-agent-operator.py`; arbitrary strategy
parameters are rejected instead of being committed publicly. It enforces a maximum
seven-minute polling window (within the short-lived identity token), requests
cancellation on timeout, and accepts only same-origin status and result URLs.
`verify_result=true` may read up to 50 MiB to record only byte count and SHA-256;
the result body is never uploaded.

## Evidence and diagnosis

Depending on the requested actions, the artifact contains:

- `health.json` and `build-info.json`;
- `gui.png` and `gui-report.json`, including console errors and failed requests;
- sanitized backtest submission/status documents, without parameters, worker logs,
  result URI, execution name, or error text; and
- result byte count and SHA-256 only when `verify_result` is explicitly true.

The browser route adds the identity token only to the configured Cloud Run origin,
so third-party assets and redirects never receive it.

The repository and its Actions artifacts are public. Do not add user-specific
parameters, raw Cloud Logging entries, result bodies, credentials, or other private
data to this workflow. Deeper private diagnostics require a private control plane,
such as a private repository workflow or an authenticated MCP tunnel.

## Rotation and removal

Delete the permanent operator branch or change `codex_operator_branch` and reapply
Terraform to revoke GitHub impersonation. To remove the integration completely,
remove `infra/gcp/codex_operator.tf` and apply the reviewed destruction plan. This
does not delete application data or either Terraform state bucket.
