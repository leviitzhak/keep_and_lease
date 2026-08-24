terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  prefix                 = "keep-and-lease"
  web_service_account    = "keep-lease-web@${var.project_id}.iam.gserviceaccount.com"
  worker_service_account = "keep-lease-worker@${var.project_id}.iam.gserviceaccount.com"
  market_data_bucket     = "${var.project_id}-market-data"
  results_bucket         = "${var.project_id}-results"
}

resource "google_cloud_run_v2_job" "calculation" {
  name                = "${local.prefix}-calculation"
  location            = var.region
  deletion_protection = false

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = local.worker_service_account
      timeout         = "1800s"
      max_retries     = 0

      containers {
        name  = "worker"
        image = var.worker_image

        resources {
          limits = {
            cpu    = "1"
            memory = "4Gi"
          }
        }

        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        env {
          name  = "KEEP_AND_LEASE_GCP_REGION"
          value = var.region
        }
        env {
          name  = "KEEP_AND_LEASE_CLOUD_RUN_JOB"
          value = "${local.prefix}-calculation"
        }
        env {
          name  = "KEEP_AND_LEASE_RESULTS_BUCKET"
          value = local.results_bucket
        }
        env {
          name  = "KEEP_AND_LEASE_MARKET_DATA_BUCKET"
          value = local.market_data_bucket
        }
        env {
          name  = "KEEP_AND_LEASE_IMAGE_REF"
          value = var.worker_image
        }
      }
    }
  }
}

resource "google_cloud_run_v2_job_iam_member" "web_executes_calculation" {
  project  = var.project_id
  location = google_cloud_run_v2_job.calculation.location
  name     = google_cloud_run_v2_job.calculation.name
  role     = "roles/run.jobsExecutorWithOverrides"
  member   = "serviceAccount:${local.web_service_account}"
}

resource "google_cloud_run_v2_service" "web" {
  name                = "${local.prefix}-web"
  location            = var.region
  deletion_protection = false
  ingress             = "INGRESS_TRAFFIC_ALL"
  iap_enabled         = var.iap_enabled

  template {
    service_account                  = local.web_service_account
    timeout                          = "300s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 0
      max_instance_count = var.web_max_instances
    }

    containers {
      name  = "web"
      image = var.web_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "KEEP_AND_LEASE_GCP_REGION"
        value = var.region
      }
      env {
        name  = "KEEP_AND_LEASE_CLOUD_RUN_JOB"
        value = google_cloud_run_v2_job.calculation.name
      }
      env {
        name  = "KEEP_AND_LEASE_RESULTS_BUCKET"
        value = local.results_bucket
      }
      env {
        name  = "KEEP_AND_LEASE_WORKER_IMAGE_REF"
        value = var.worker_image
      }
      env {
        name  = "KEEP_AND_LEASE_ALLOWED_ORIGINS"
        value = var.allowed_origins
      }
      env {
        name  = "KEEP_AND_LEASE_ALLOWED_ORIGIN_REGEX"
        value = var.allowed_origin_regex
      }

      startup_probe {
        timeout_seconds   = 2
        period_seconds    = 2
        failure_threshold = 15

        http_get {
          path = "/api/v1/health"
        }
      }
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.web_executes_calculation]
}

check "exclusive_web_authentication_mode" {
  assert {
    condition     = !(var.iap_enabled && var.allow_unauthenticated)
    error_message = "IAP and unauthenticated Cloud Run invocation cannot be enabled together."
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_web" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "deploy_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.servicesInvoker"
  member   = "serviceAccount:keep-lease-github@${var.project_id}.iam.gserviceaccount.com"
}

resource "google_cloud_run_v2_service_iam_member" "iap_service_agent_invoker" {
  count = var.iap_enabled ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-iap.iam.gserviceaccount.com"
}

resource "google_iap_web_cloud_run_service_iam_member" "machine_accessors" {
  for_each = var.iap_enabled ? toset([
    "serviceAccount:keep-lease-codex-operator@${var.project_id}.iam.gserviceaccount.com",
    "serviceAccount:keep-lease-github@${var.project_id}.iam.gserviceaccount.com",
  ]) : toset([])

  project                = var.project_id
  location               = google_cloud_run_v2_service.web.location
  cloud_run_service_name = google_cloud_run_v2_service.web.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.value

  depends_on = [google_cloud_run_v2_service_iam_member.iap_service_agent_invoker]
}
