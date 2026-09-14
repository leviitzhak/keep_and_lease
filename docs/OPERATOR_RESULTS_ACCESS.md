# Standing operator results access

## September 14, 2026 — owner-reported activation and local diagnostic helper

Branch: `agent/operator-results-reader`, based on `agent/shared-run-plots` at
`989acd51b8895f868e96a7895a84a2d549ce9d8a`.

- [x] Declare `google_storage_bucket_iam_member.codex_results_reader` in the
  persistent foundation and add permission-scope regression tests.
- [x] Owner reports the reviewed foundation plan was applied and valid on
  September 14, 2026. This is owner confirmation, not an independent live-IAM
  verification by the editing agent.
- [x] Add an owner-run read-only fee/position diagnostic at
  `scripts/diagnose_run_costs.py`; see `RUN_COST_DIAGNOSTIC_README.md`.
- [ ] Independently verify live operator object reads and complete a protected
  automatic diagnostic transport. The local helper is not that transport.

The resource grants `roles/storage.objectViewer` on the existing results bucket
to the existing keyless operator. With project defaults these are
`keep-and-lease-results` and
`keep-lease-codex-operator@keep-and-lease.iam.gserviceaccount.com`.
There is no per-run condition or expiration: all existing/future result, audit,
checkpoint and export objects in this bucket are covered. Separate new buckets
are not automatically covered. This additive member preserves other bucket roles
and members. Market-data objectViewer/objectCreator and branch-restricted
impersonation remain unchanged. No result writes, public access, project-level
role, Terraform-state, Firestore or IAM-administration grant is added.

## Activation record and future setup

The owner-provided plan included four member additions and one in-place
service-account description update: operator market-data creator/viewer,
operator results viewer and conditional web access to the two published
benchmarks. These included older foundation declarations, not only the new
reader. The condition must use the literal `projects/_/buckets/` resource prefix,
not `projects/*/buckets/`. The owner subsequently confirmed application/validity.
No additional Terraform apply is needed simply to pull or execute the diagnostic.

For a future setup, use the existing foundation checkout, approved variables and
state. The backend is `gs://keep-and-lease-terraform-state`, prefix `foundation`.
Do not use `infra/gcp/workloads/`, an empty local state, or a different workspace.

```bash
cd ~/keep_and_lease
git fetch origin
git switch agent/operator-results-reader
git pull --ff-only
cd infra/gcp
terraform init
terraform fmt -check codex_operator.tf
terraform validate
terraform plan -out=operator-results-reader.tfplan
terraform show -no-color operator-results-reader.tfplan
```

Review the full saved plan rather than assuming a resource count. The intended
new grant is `google_storage_bucket_iam_member.codex_results_reader`; older
unmanaged declarations may also appear. Stop for unrelated changes or resource
replacements/destruction. Keep plans/state private and state locking enabled.
The applying human needs existing foundation/backend privileges and bucket IAM
administration; the operator cannot grant access to itself.

Only after review, apply the exact saved plan:

```bash
terraform apply operator-results-reader.tfplan
```

A saved-plan apply performs the reviewed changes without another approval
prompt. Inspect the bucket IAM policy afterward for the unconditional
objectViewer member. Any organization deny policies or service perimeters may
still affect actual object reads; a recorded binding alone is not proof of a
completed private diagnostic connection.

If the unconditional grant was already made manually and this resource is not
in Terraform state, it can instead be adopted before planning:

```bash
terraform import google_storage_bucket_iam_member.codex_results_reader \
  'keep-and-lease-results roles/storage.objectViewer serviceAccount:keep-lease-codex-operator@keep-and-lease.iam.gserviceaccount.com'
```

Use the actual foundation identifiers for a nondefault project. A conditional
single-run grant is not the same binding; do not import it as this resource or
remove independent grants as part of this change. To revoke only this grant,
remove its Terraform block, review the foundation plan and apply that removal;
do not delete the bucket, the service account or the other operator resources.

## Owner-run investigation

Pull the branch and run `python3 scripts/diagnose_run_costs.py --run-id <run-id>`
from its repository root in authenticated Cloud Shell. The helper reads saved
results/audits from GCS with the active gcloud account and produces ordinary
local reports. It has no remote writes, engine execution or automatic upload.
There is no need to rerun a strategy or deploy the GUI to add these statistics.
The run ID is supplied at execution and is not hard-coded in public source.
See [RUN_COST_DIAGNOSTIC_README.md](RUN_COST_DIAGNOSTIC_README.md) for period,
read-budget and output controls and the nine offline regression tests.

## Deployment, privacy and validation

The IAM declaration is foundation-only. Normal application deployment applies
the workloads root and does not activate bucket IAM. Both the initial declaration
and the local-helper addition use `[skip ci]` to preserve the shared preview.
No application deployment or master merge is part of this work. Adding the helper
does not itself retrieve any private run data.

The public operator still accepts sanitized smoke requests; the separate
blocked diagnostic workflow was not changed by adding this local script. Bucket
access does not override application run-owner checks. Do not commit private
parameters, positions, results or credentials to public logs/artifacts. Local
plain-text reports and protected automatic transport are different mechanisms.

The original 13 source-contract and existing operator request/privacy tests
passed when the grant was declared:

```bash
python -m unittest tests.test_operator_results_access tests.test_cloud_agent_operator -v
```

Those tests check permission scope, not Terraform syntax or live IAM. The editing
agent has not run native Terraform or live reads; activation is recorded from
the owner's confirmation. No cloud credentials were requested or exported.

References: [bucket IAM resources](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/storage_bucket_iam),
[Terraform validation](https://developer.hashicorp.com/terraform/cli/commands/validate),
[saved plans](https://developer.hashicorp.com/terraform/cli/commands/plan), and
[GitHub skip instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
