variable "codex_operator_branch" {
  description = "Only this GitHub branch may impersonate the bounded Codex operator identity."
  type        = string
  default     = "agent/cloud-autonomous-access"
}

resource "google_service_account" "codex_operator" {
  account_id   = "keep-lease-codex-operator"
  display_name = "Keep & Lease Codex cloud operator"
  description  = "Bounded keyless identity for private health, GUI, and API checks."
}

resource "google_service_account_iam_member" "codex_operator_github_wif" {
  service_account_id = google_service_account.codex_operator.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.ref/refs/heads/${var.codex_operator_branch}"
}

resource "google_cloud_run_v2_service_iam_member" "codex_operator_web_invoker" {
  project  = var.project_id
  location = var.region
  name     = "${local.prefix}-web"
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.codex_operator.email}"
}

output "codex_operator_service_account" {
  value = google_service_account.codex_operator.email
}

# Owner reports this secret-level grant was made manually on 2026-10-05.
# Adopt the existing binding in foundation state before a reviewed apply.
resource "google_secret_manager_secret_iam_member" "codex_databento_reader" {
  project   = var.project_id
  secret_id = "databento-api-key"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.codex_operator.email}"
}
