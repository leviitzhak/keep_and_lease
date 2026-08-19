# Google Cloud infrastructure

This directory is the source of truth for the persistent Keep & Lease Google Cloud foundation described in `docs/GOOGLE_CLOUD_RUN_SETUP.md`.

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

Cloud Run service/job resources are intentionally deferred until the application has separate durable web and worker entry points; the current in-memory background-thread server must not be treated as the final Cloud Run architecture.
