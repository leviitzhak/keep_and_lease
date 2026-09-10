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
  preview                = var.deployment_target == "preview"
  prefix                 = local.preview ? "keep-and-lease-preview" : "keep-and-lease"
  web_service_account    = "keep-lease-web@${var.project_id}.iam.gserviceaccount.com"
  worker_service_account = "keep-lease-worker@${var.project_id}.iam.gserviceaccount.com"
  market_data_bucket     = "${var.project_id}-market-data"
  results_bucket         = "${var.project_id}-results"
  firestore_collection   = local.preview ? "backtests_preview" : "backtests"
  cache_collection       = local.preview ? "backtest_cache_preview" : "backtest_cache"
}

# Published, fixed research fixtures only. This grants no access to user results
# or arbitrary market-bucket jobs. The shared web identity serves both targets;
# preview owns this one binding so stable/preview states never compete over it.
resource "google_storage_bucket_iam_member" "web_published_benchmarks" {
  count  = local.preview ? 1 : 0
  bucket = local.market_data_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${local.web_service_account}"
  condition {
    title      = "published_btc_90day_benchmarks"
    expression = "resource.name.startsWith('projects/_/buckets/${local.market_data_bucket}/objects/jobs/d7afa21dd9da7d3b1b4ab15efe639ed4/') || resource.name.startsWith('projects/_/buckets/${local.market_data_bucket}/objects/jobs/e2e5ea42cb21f82926deb6d0ef9a3877/')"
  }
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
      timeout         = "${var.worker_timeout_seconds}s"
      max_retries     = 0

      containers {
        name  = "worker"
        image = var.worker_image

        resources {
          limits = {
            cpu    = var.worker_cpu
            memory = var.worker_memory
          }
        }

        env {
          name  = "KEEP_AND_LEASE_TRADE_CATALOG"
          value = var.trade_catalog_json
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
          name  = "KEEP_AND_LEASE_FIRESTORE_COLLECTION"
          value = local.firestore_collection
        }
        env {
          name  = "KEEP_AND_LEASE_FIRESTORE_CACHE_COLLECTION"
          value = local.cache_collection
        }
        env {
          name  = "KEEP_AND_LEASE_MARKET_DATA_BUCKET"
          value = local.market_data_bucket
        }
        env {
          name  = "KEEP_AND_LEASE_IMAGE_REF"
          value = var.worker_image
        }
        env {
          name  = "KEEP_AND_LEASE_MAX_RESULT_BYTES"
          value = tostring(var.max_result_bytes)
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
    timeout                          = "3600s"
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
        name  = "KEEP_AND_LEASE_TRADE_CATALOG"
        value = var.trade_catalog_json
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
        name  = "KEEP_AND_LEASE_FIRESTORE_COLLECTION"
        value = local.firestore_collection
      }
      env {
        name  = "KEEP_AND_LEASE_FIRESTORE_CACHE_COLLECTION"
        value = local.cache_collection
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
      env {
        name  = "KEEP_AND_LEASE_MAX_RESULT_BYTES"
        value = tostring(var.max_result_bytes)
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

resource "google_cloud_run_v2_service_iam_member" "codex_operator_preview_invoker" {
  count = local.preview ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:keep-lease-codex-operator@${var.project_id}.iam.gserviceaccount.com"
}

resource "google_cloud_run_v2_service_iam_member" "iap_service_agent_invoker" {
  count = var.iap_enabled ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.web.location
  name     = google_cloud_run_v2_service.web.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-iap.iam.gserviceaccount.com"
}
