terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
}
provider "google" { project = var.project_id; region = var.region }
locals { prefix = "keep-and-lease" }
resource "google_artifact_registry_repository" "containers" { location = var.region; repository_id = local.prefix; format = "DOCKER" }
resource "google_storage_bucket" "market_data" { name = "${var.project_id}-market-data"; location = var.region; uniform_bucket_level_access = true; public_access_prevention = "enforced"; versioning { enabled = true } }
resource "google_storage_bucket" "results" { name = "${var.project_id}-results"; location = var.region; uniform_bucket_level_access = true; public_access_prevention = "enforced"; lifecycle_rule { condition { age = var.result_retention_days }; action { type = "Delete" } } }
resource "google_service_account" "web" { account_id = "keep-lease-web"; display_name = "Keep & Lease Cloud Run web" }
resource "google_service_account" "worker" { account_id = "keep-lease-worker"; display_name = "Keep & Lease calculation worker" }
resource "google_service_account" "deploy" { account_id = "keep-lease-github"; display_name = "Keep & Lease GitHub deployment" }
resource "google_storage_bucket_iam_member" "worker_market_reader" { bucket = google_storage_bucket.market_data.name; role = "roles/storage.objectViewer"; member = "serviceAccount:${google_service_account.worker.email}" }
resource "google_storage_bucket_iam_member" "worker_results_writer" { bucket = google_storage_bucket.results.name; role = "roles/storage.objectUser"; member = "serviceAccount:${google_service_account.worker.email}" }
resource "google_storage_bucket_iam_member" "web_results_reader" { bucket = google_storage_bucket.results.name; role = "roles/storage.objectViewer"; member = "serviceAccount:${google_service_account.web.email}" }
resource "google_firestore_database" "jobs" { project = var.project_id; name = "(default)"; location_id = var.firestore_location; type = "FIRESTORE_NATIVE" }
resource "google_project_iam_member" "worker_datastore" { project = var.project_id; role = "roles/datastore.user"; member = "serviceAccount:${google_service_account.worker.email}" }
resource "google_project_iam_member" "web_datastore" { project = var.project_id; role = "roles/datastore.user"; member = "serviceAccount:${google_service_account.web.email}" }
resource "google_iam_workload_identity_pool" "github" { workload_identity_pool_id = "github"; display_name = "GitHub Actions" }
resource "google_iam_workload_identity_pool_provider" "github" { workload_identity_pool_id = google_iam_workload_identity_pool.github.workload_identity_pool_id; workload_identity_pool_provider_id = "github"; display_name = "GitHub Actions"; attribute_mapping = { "google.subject" = "assertion.sub", "attribute.repository" = "assertion.repository", "attribute.ref" = "assertion.ref" }; attribute_condition = "assertion.repository == '${var.github_repository}'"; oidc { issuer_uri = "https://token.actions.githubusercontent.com" } }
resource "google_service_account_iam_member" "github_wif" { service_account_id = google_service_account.deploy.name; role = "roles/iam.workloadIdentityUser"; member = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}" }
resource "google_project_iam_member" "deploy_run" { project = var.project_id; role = "roles/run.admin"; member = "serviceAccount:${google_service_account.deploy.email}" }
resource "google_project_iam_member" "deploy_artifact" { project = var.project_id; role = "roles/artifactregistry.writer"; member = "serviceAccount:${google_service_account.deploy.email}" }
resource "google_service_account_iam_member" "deploy_use_web" { service_account_id = google_service_account.web.name; role = "roles/iam.serviceAccountUser"; member = "serviceAccount:${google_service_account.deploy.email}" }
resource "google_service_account_iam_member" "deploy_use_worker" { service_account_id = google_service_account.worker.name; role = "roles/iam.serviceAccountUser"; member = "serviceAccount:${google_service_account.deploy.email}" }
