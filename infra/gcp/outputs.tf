output "artifact_registry" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}" }
output "market_data_bucket" { value = google_storage_bucket.market_data.name }
output "results_bucket" { value = google_storage_bucket.results.name }
output "web_service_account" { value = google_service_account.web.email }
output "worker_service_account" { value = google_service_account.worker.email }
output "deployment_service_account" { value = google_service_account.deploy.email }
output "workload_identity_provider" { value = google_iam_workload_identity_pool_provider.github.name }
