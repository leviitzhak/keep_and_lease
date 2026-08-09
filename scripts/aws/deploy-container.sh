#!/usr/bin/env bash
set -euo pipefail
instance_id="${1:-}"; image="${2:-}"; name="${3:-}"; host_port="${4:-}"
[[ "$instance_id" =~ ^i-[a-f0-9]+$ && "$image" =~ ^[a-zA-Z0-9._:/@-]+$ && "$name" =~ ^[a-zA-Z0-9._-]+$ && "$host_port" =~ ^[0-9]+$ ]] || {
  echo "Usage: $0 INSTANCE_ID ECR_IMAGE_OR_DIGEST CONTAINER_NAME HOST_PORT" >&2; exit 2;
}
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
[[ -n "$region" ]] || { echo "AWS_REGION is required" >&2; exit 2; }
registry="${image%%/*}"
commands="set -euo pipefail; aws ecr get-login-password --region $region | docker login --username AWS --password-stdin $registry; docker pull $image; docker rm -f $name 2>/dev/null || true; docker run -d --restart unless-stopped --name $name --memory 1500m --cpus 1 --pids-limit 256 --read-only --tmpfs /tmp:rw,noexec,nosuid,size=256m -p 127.0.0.1:$host_port:8080 $image"
command_id="$(aws ssm send-command --instance-ids "$instance_id" --document-name AWS-RunShellScript --parameters "commands=[$(printf '%s' "$commands" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')]" --query Command.CommandId --output text)"
aws ssm wait command-executed --command-id "$command_id" --instance-id "$instance_id"
aws ssm get-command-invocation --command-id "$command_id" --instance-id "$instance_id" --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}'

