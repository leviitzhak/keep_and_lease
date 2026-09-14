# Standing operator results access

## September 14, 2026 — configuration added, not applied

Branch: `agent/operator-results-reader`, based on `agent/shared-run-plots` at
`989acd51b8895f868e96a7895a84a2d549ce9d8a`.

- [x] Declare `google_storage_bucket_iam_member.codex_results_reader` in the
  persistent foundation and add permission-scope regression tests.
- [ ] Run native Terraform validation, review/apply the live foundation plan,
  and verify the IAM binding.
- [ ] Add a protected diagnostic transport before retrieving private runs.

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

## Activate from authenticated Cloud Shell

Use the existing foundation checkout, approved variables and state. The backend
is `gs://keep-and-lease-terraform-state`, prefix `foundation`. Do not use
`infra/gcp/workloads/`, an empty local state, or a different workspace.

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

Review the saved plan. The intended change is **only** the new results reader:
usually `1 to add, 0 to change, 0 to destroy`. This is an expectation, not an
observed live plan. Stop for unrelated changes or resource creation/replacement/
destruction. Keep plans/state private and state locking enabled. The applying
human needs existing foundation/backend privileges and results-bucket IAM
administration; the operator cannot grant access to itself.

Only after that review, apply the exact saved plan:

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

## Deployment, privacy and validation

This is a foundation-only change. Normal application deployment applies the
workloads root and does not activate bucket IAM. The commit uses `[skip ci]`
to preserve the shared preview; no application deployment or master merge is
part of this patch. No private run data is retrieved by these changes.

The public operator still accepts only sanitized smoke requests. Bucket access
does not override the application's run-owner checks or authorize private
parameters, positions, results or credentials in public logs/artifacts. Protected
private diagnostics remain separate work, as documented in `CLOUD_AGENT_ACCESS.md`.

All 13 source-contract and existing operator request/privacy tests passed:

```bash
python -m unittest tests.test_operator_results_access tests.test_cloud_agent_operator -v
```

These check permission scope, not Terraform syntax or live IAM. Terraform CLI
is unavailable in the editing runtime; native fmt/validate/plan/apply are not
claimed to have run. No cloud credentials were requested or exported.

References: [bucket IAM resources](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/storage_bucket_iam),
[Terraform validation](https://developer.hashicorp.com/terraform/cli/commands/validate),
[saved plans](https://developer.hashicorp.com/terraform/cli/commands/plan), and
[GitHub skip instructions](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/skip-workflow-runs).
