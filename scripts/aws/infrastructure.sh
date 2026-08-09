#!/usr/bin/env bash
set -euo pipefail
action="${1:-}"; shift || true
profile=""; region="eu-west-1"
while [[ $# -gt 0 ]]; do case "$1" in --profile) profile="$2"; shift 2;; --region) region="$2"; shift 2;; *) echo "Unknown argument: $1" >&2; exit 2;; esac; done
case "$action" in plan|apply|destroy) ;; *) echo "Usage: $0 plan|apply|destroy --profile PROFILE [--region REGION]" >&2; exit 2;; esac
[[ -n "$profile" && -f infra/aws/backend.hcl && -f infra/aws/terraform.tfvars ]] || { echo "Run bootstrap-state.sh and create infra/aws/terraform.tfvars first" >&2; exit 2; }
terraform -chdir=infra/aws init -backend-config=backend.hcl
args=(-var="aws_profile=$profile" -var="aws_region=$region")
if [[ "$action" == plan ]]; then terraform -chdir=infra/aws plan "${args[@]}" -out=tfplan; exit; fi
if [[ "$action" == apply ]]; then terraform -chdir=infra/aws apply "${args[@]}"; exit; fi
echo "Destroy is destructive; type the project name to continue:"
read -r confirmation
[[ "$confirmation" == "keep-and-lease" ]] || { echo "Cancelled"; exit 1; }
terraform -chdir=infra/aws destroy "${args[@]}"

