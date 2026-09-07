#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-keep-and-lease}"
REGION="${REGION:-me-west1}"
SERVICE_NAME="${SERVICE_NAME:-keep-and-lease-preview-web}"
CONFIGURATION_NAME="${CONFIGURATION_NAME:-keep-and-lease}"
PERSISTENT_GCLOUD_CONFIG="${PERSISTENT_GCLOUD_CONFIG:-$HOME/.config/gcloud}"
SHELL_RC="${SHELL_RC:-$HOME/.bashrc}"
CLOUD_SHELL_INIT="${CLOUD_SHELL_INIT:-$HOME/.config/keep-and-lease/cloud-shell-init.sh}"
account_email=""
assume_yes=false

usage() {
  cat <<'EOF'
Configure persistent Cloud Shell gcloud authentication and grant the standard
Keep & Lease IAP allowlist to a Cloud Run service.

Usage:
  scripts/configure-cloud-run-iap-access.sh [options]

Options:
  --account EMAIL   Approved human Google account (prompted when omitted).
  --service NAME    Cloud Run service (default: keep-and-lease-preview-web).
  --yes             Skip the final permission-change confirmation.
  -h, --help        Show this help.

Environment overrides:
  PROJECT_ID, REGION, SERVICE_NAME, CONFIGURATION_NAME,
  PERSISTENT_GCLOUD_CONFIG, SHELL_RC, CLOUD_SHELL_INIT
EOF
}

while (($#)); do
  case "$1" in
    --account)
      [[ $# -ge 2 ]] || { echo "--account requires a value." >&2; exit 2; }
      account_email="$2"
      shift 2
      ;;
    --account=*)
      account_email="${1#*=}"
      shift
      ;;
    --service)
      [[ $# -ge 2 ]] || { echo "--service requires a value." >&2; exit 2; }
      SERVICE_NAME="$2"
      shift 2
      ;;
    --service=*)
      SERVICE_NAME="${1#*=}"
      shift
      ;;
    --yes)
      assume_yes=true
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

command -v gcloud >/dev/null 2>&1 || {
  echo "gcloud is required; run this script from Google Cloud Shell." >&2
  exit 1
}

if [[ -z "$account_email" ]]; then
  read -r -p "Approved human Google account email: " account_email
fi
if [[ ! "$account_email" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
  echo "A valid Google account email is required." >&2
  exit 2
fi
if [[ ! "$SERVICE_NAME" =~ ^[a-z][a-z0-9-]{0,62}$ ]]; then
  echo "Invalid Cloud Run service name: $SERVICE_NAME" >&2
  exit 2
fi

mkdir -p \
  "$(dirname "$SHELL_RC")" \
  "$PERSISTENT_GCLOUD_CONFIG" \
  "$(dirname "$CLOUD_SHELL_INIT")"
export CLOUDSDK_CONFIG="$PERSISTENT_GCLOUD_CONFIG"

if gcloud config configurations list \
  --filter="name=$CONFIGURATION_NAME" \
  --format='value(name)' | grep -Fqx "$CONFIGURATION_NAME"; then
  gcloud config configurations activate "$CONFIGURATION_NAME"
else
  gcloud config configurations create "$CONFIGURATION_NAME" --activate
fi

if ! gcloud auth list \
  --filter="account=$account_email" \
  --format='value(account)' | grep -Fqx "$account_email"; then
  echo "Authenticate ${account_email}. In Cloud Shell, approve the login prompt."
  gcloud auth login "$account_email"
fi

gcloud config set core/account "$account_email"
gcloud config set core/project "$PROJECT_ID"
gcloud config set run/region "$REGION"
gcloud projects describe "$PROJECT_ID" --format='value(projectId)' >/dev/null

# Cloud Shell can select the Console's current project after starting a new
# session. Source a small private initializer from .bashrc so this repository's
# named configuration wins consistently in every future interactive shell.
{
  printf 'export CLOUDSDK_CONFIG=%q\n' "$PERSISTENT_GCLOUD_CONFIG"
  printf 'gcloud config configurations activate %q --quiet >/dev/null 2>&1 || true\n' "$CONFIGURATION_NAME"
  printf 'gcloud config set core/account %q --quiet >/dev/null 2>&1 || true\n' "$account_email"
  printf 'gcloud config set core/project %q --quiet >/dev/null 2>&1 || true\n' "$PROJECT_ID"
  printf 'gcloud config set run/region %q --quiet >/dev/null 2>&1 || true\n' "$REGION"
} >"$CLOUD_SHELL_INIT"
chmod 600 "$CLOUD_SHELL_INIT"
printf -v source_line 'source %q' "$CLOUD_SHELL_INIT"
if ! grep -Fqx "$source_line" "$SHELL_RC" 2>/dev/null; then
  printf '\n%s\n' "$source_line" >>"$SHELL_RC"
fi

principals=(
  "user:${account_email}"
  "serviceAccount:keep-lease-github@${PROJECT_ID}.iam.gserviceaccount.com"
  "serviceAccount:keep-lease-codex-operator@${PROJECT_ID}.iam.gserviceaccount.com"
)

echo
echo "The following principals will receive roles/iap.httpsResourceAccessor"
echo "on Cloud Run service ${SERVICE_NAME} in ${PROJECT_ID}/${REGION}:"
printf '  - %s\n' "${principals[@]}"

if [[ "$assume_yes" != true ]]; then
  read -r -p "Apply these additive IAP bindings? [y/N] " confirmation
  [[ "$confirmation" =~ ^[Yy]$ ]] || {
    echo "No IAP policy changes were made."
    exit 0
  }
fi

for principal in "${principals[@]}"; do
  gcloud iap web add-iam-policy-binding \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --resource-type=cloud-run \
    --service="$SERVICE_NAME" \
    --member="$principal" \
    --role=roles/iap.httpsResourceAccessor \
    --quiet
done

echo
echo "IAP access configured for ${SERVICE_NAME}. Current policy:"
gcloud iap web get-iam-policy \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --resource-type=cloud-run \
  --service="$SERVICE_NAME"
