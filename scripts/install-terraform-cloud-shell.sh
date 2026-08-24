#!/usr/bin/env bash
set -euo pipefail

TERRAFORM_VERSION="${TERRAFORM_VERSION:-1.15.9}"
TERRAFORM_INSTALL_DIR="${TERRAFORM_INSTALL_DIR:-$HOME/.local/bin}"
TERRAFORM_SHELL_RC="${TERRAFORM_SHELL_RC:-$HOME/.bashrc}"

if [[ ! "$TERRAFORM_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "TERRAFORM_VERSION must be a numeric release such as 1.15.0." >&2
  exit 1
fi

for command_name in curl unzip sha256sum install; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command not found: ${command_name}" >&2
    exit 1
  fi
done

case "$(uname -m)" in
  x86_64 | amd64)
    terraform_arch="amd64"
    ;;
  aarch64 | arm64)
    terraform_arch="arm64"
    ;;
  *)
    echo "Unsupported Cloud Shell architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

terraform_binary="${TERRAFORM_INSTALL_DIR}/terraform"
path_line='export PATH="$HOME/.local/bin:$PATH"'

configure_persistent_path() {
  if [[ "$TERRAFORM_INSTALL_DIR" == "$HOME/.local/bin" ]] &&
    ! grep -Fqx "$path_line" "$TERRAFORM_SHELL_RC" 2>/dev/null; then
    mkdir -p "$(dirname "$TERRAFORM_SHELL_RC")"
    printf '\n%s\n' "$path_line" >>"$TERRAFORM_SHELL_RC"
  fi
}

if [[ -x "$terraform_binary" ]] &&
  "$terraform_binary" version | head -n 1 | grep -Fqx "Terraform v${TERRAFORM_VERSION}"; then
  configure_persistent_path
  echo "Terraform ${TERRAFORM_VERSION} is already installed at ${terraform_binary}."
  exit 0
fi

terraform_archive="terraform_${TERRAFORM_VERSION}_linux_${terraform_arch}.zip"
terraform_base_url="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}"
temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/keep-lease-terraform.XXXXXX")"
trap 'rm -rf "$temporary_dir"' EXIT

curl --fail --location --silent --show-error \
  --output "${temporary_dir}/${terraform_archive}" \
  "${terraform_base_url}/${terraform_archive}"
curl --fail --location --silent --show-error \
  --output "${temporary_dir}/SHA256SUMS" \
  "${terraform_base_url}/terraform_${TERRAFORM_VERSION}_SHA256SUMS"

expected_checksum="$(awk -v archive="$terraform_archive" '$2 == archive { print $1 }' \
  "${temporary_dir}/SHA256SUMS")"
if [[ -z "$expected_checksum" ]]; then
  echo "Checksum for ${terraform_archive} was not published." >&2
  exit 1
fi

actual_checksum="$(sha256sum "${temporary_dir}/${terraform_archive}" | awk '{ print $1 }')"
if [[ "$actual_checksum" != "$expected_checksum" ]]; then
  echo "Terraform archive checksum verification failed." >&2
  exit 1
fi

unzip -q "${temporary_dir}/${terraform_archive}" -d "$temporary_dir"
mkdir -p "$TERRAFORM_INSTALL_DIR"
install -m 0755 "${temporary_dir}/terraform" "$terraform_binary"
configure_persistent_path

echo "Installed Terraform ${TERRAFORM_VERSION} at ${terraform_binary}."
if [[ "$TERRAFORM_INSTALL_DIR" == "$HOME/.local/bin" ]]; then
  echo 'Run: export PATH="$HOME/.local/bin:$PATH"'
fi
