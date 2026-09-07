#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api_port="${KEEP_AND_LEASE_LOCAL_API_PORT:-8000}"
api_origin="http://127.0.0.1:${api_port}"
api_pid=""

cleanup() {
  if [[ -n "${api_pid}" ]] && kill -0 "${api_pid}" 2>/dev/null; then
    kill "${api_pid}"
    wait "${api_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "${project_root}"
PORT="${api_port}" python server_main.py &
api_pid="$!"

for _ in $(seq 1 80); do
  if curl --fail --silent "${api_origin}/api/v1/health" >/dev/null; then
    break
  fi
  if ! kill -0 "${api_pid}" 2>/dev/null; then
    wait "${api_pid}"
  fi
  sleep 0.25
done

if ! curl --fail --silent "${api_origin}/api/v1/health" >/dev/null; then
  echo "Local calculation API did not become ready at ${api_origin}." >&2
  exit 1
fi

export KEEP_AND_LEASE_LOCAL_API_URL="${api_origin}"
npm run dev:gui
