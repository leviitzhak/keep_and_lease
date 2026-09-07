#!/usr/bin/env bash
set -euo pipefail
profile=""; region="eu-west-1"
while [[ $# -gt 0 ]]; do case "$1" in --profile) profile="$2"; shift 2;; --region) region="$2"; shift 2;; *) echo "Unknown argument: $1" >&2; exit 2;; esac; done
[[ -n "$profile" ]] || { echo "--profile is required" >&2; exit 2; }
account="$(aws --profile "$profile" --region "$region" sts get-caller-identity --query Account --output text)"
bucket="keep-and-lease-tfstate-${account}-${region}"
if ! aws --profile "$profile" --region "$region" s3api head-bucket --bucket "$bucket" 2>/dev/null; then
  args=(--bucket "$bucket"); [[ "$region" == "us-east-1" ]] || args+=(--create-bucket-configuration "LocationConstraint=$region")
  aws --profile "$profile" --region "$region" s3api create-bucket "${args[@]}"
fi
aws --profile "$profile" --region "$region" s3api put-bucket-versioning --bucket "$bucket" --versioning-configuration Status=Enabled
aws --profile "$profile" --region "$region" s3api put-bucket-encryption --bucket "$bucket" --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws --profile "$profile" --region "$region" s3api put-public-access-block --bucket "$bucket" --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
umask 077
printf 'bucket=%s\nkey=keep-and-lease/terraform.tfstate\nregion=%s\nuse_lockfile=true\nencrypt=true\nprofile=%s\n' "$bucket" "$region" "$profile" > infra/aws/backend.hcl
echo "Created/verified encrypted Terraform state bucket $bucket and wrote infra/aws/backend.hcl"

