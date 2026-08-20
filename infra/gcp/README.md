# Google Cloud infrastructure

This directory contains two independently managed Terraform roots described in
`docs/GOOGLE_CLOUD_RUN_SETUP.md`.

- `infra/gcp/` is the persistent foundation and uses GCS state prefix `foundation`.
- `infra/gcp/workloads/` is the replaceable Cloud Run web service and calculation
  Job and uses `gs://keep-and-lease-terraform-workloads/cloud-run`.

The first apply runs from an authenticated Google Cloud Shell and creates storage, Artifact Registry, Firestore, least-privilege runtime identities, and GitHub Workload Identity Federation. No service-account JSON key is required.

```bash
cd ~/keep_and_lease
git pull
cd infra/gcp
terraform init
terraform plan
terraform apply
terraform output
```

Defaults target project `keep-and-lease` and region `me-west1`. Review the plan before approving it, especially the Firestore location.

After pulling the durable web/worker implementation, apply the foundation once more
to grant runtime image-read access and GitHub access to workload state. Then run the
manual **Deploy Google Cloud workloads** GitHub Actions workflow. It builds and
pushes immutable images before planning and applying `workloads/`; do not attempt a
first workload apply before those image digests exist.

The web service is private by default. Public billable job creation requires
`allow_unauthenticated=true`, which must remain disabled until application
authentication and quotas are implemented.
