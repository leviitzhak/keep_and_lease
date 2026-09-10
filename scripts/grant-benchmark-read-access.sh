#!/usr/bin/env bash
# Run once as a bucket IAM administrator in authenticated Cloud Shell.
# Matches the foundation-managed, prefix-restricted binding exactly.
set -euo pipefail
project_id="${1:-keep-and-lease}"
if [[ ! "$project_id" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]]; then
  echo 'Invalid Google Cloud project ID' >&2
  exit 2
fi
bucket_name="${project_id}-market-data"
object_prefix="projects/_/buckets/${bucket_name}/objects/jobs"
expression="resource.name.startsWith('${object_prefix}/d7afa21dd9da7d3b1b4ab15efe639ed4/') || resource.name.startsWith('${object_prefix}/e2e5ea42cb21f82926deb6d0ef9a3877/')"
gcloud storage buckets add-iam-policy-binding "gs://${bucket_name}" \
  --project="$project_id" \
  --member="serviceAccount:keep-lease-web@${project_id}.iam.gserviceaccount.com" \
  --role=roles/storage.objectViewer \
  --condition="title=published_btc_90day_benchmarks,expression=${expression}"
