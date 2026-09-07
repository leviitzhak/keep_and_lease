#!/usr/bin/env bash
set -euo pipefail
instance_id="${1:-}"
[[ "$instance_id" =~ ^i-[a-f0-9]+$ ]] || { echo "Usage: $0 INSTANCE_ID" >&2; exit 2; }
aws ec2 start-instances --instance-ids "$instance_id" >/dev/null
aws ec2 wait instance-status-ok --instance-ids "$instance_id"
echo "$instance_id is running and passed EC2 status checks"

