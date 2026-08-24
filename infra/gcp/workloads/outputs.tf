output "web_service" { value = google_cloud_run_v2_service.web.name }
output "web_uri" { value = google_cloud_run_v2_service.web.uri }
output "calculation_job" { value = google_cloud_run_v2_job.calculation.name }
output "iap_enabled" { value = google_cloud_run_v2_service.web.iap_enabled }
