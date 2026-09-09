variable "project_id" {
  type    = string
  default = "keep-and-lease"
}

variable "region" {
  type    = string
  default = "me-west1"
}

variable "deployment_target" {
  description = "Stable production resources or isolated feature-branch preview resources."
  type        = string
  default     = "stable"

  validation {
    condition     = contains(["stable", "preview"], var.deployment_target)
    error_message = "deployment_target must be either stable or preview."
  }
}

variable "web_image" {
  description = "Immutable Artifact Registry web image reference."
  type        = string
}

variable "worker_image" {
  description = "Immutable Artifact Registry worker image reference."
  type        = string
}

variable "web_max_instances" {
  type    = number
  default = 3
}

variable "max_result_bytes" {
  description = "Maximum uncompressed JSON backtest-result size accepted before storage."
  type        = number
  default     = 268435456

  validation {
    condition = (
      var.max_result_bytes >= 104857600 &&
      floor(var.max_result_bytes) == var.max_result_bytes
    )
    error_message = "max_result_bytes must be an integer of at least 104857600 bytes (100 MiB)."
  }
}

variable "allow_unauthenticated" {
  description = "Expose billable job submission publicly; false for the private proof of concept."
  type        = bool
  default     = false
}

variable "iap_enabled" {
  description = "Protect every Cloud Run ingress path with Identity-Aware Proxy."
  type        = bool
  default     = false
}

variable "allowed_origins" {
  type    = string
  default = "https://keep-and-lease-fixed-preview.onrender.com,https://keep-and-lease.itzhakb.chatgpt.site"
}

variable "allowed_origin_regex" {
  type    = string
  default = ""
}

variable "trade_catalog_json" {
  description = "Pinned trade range catalog, set only after staged data/replay acceptance. Empty retains the one-day pilot."
  type        = string
  default     = ""
}

variable "worker_timeout_seconds" {
  description = "Worker duration; increase only after staged replay measurements."
  type        = number
  default     = 1800
  validation {
    condition     = var.worker_timeout_seconds >= 1800 && var.worker_timeout_seconds <= 604800 && floor(var.worker_timeout_seconds) == var.worker_timeout_seconds
    error_message = "Worker timeout must be an integer between 1800 and 604800 seconds."
  }
}

variable "worker_cpu" {
  description = "CPU allocation for the continuous replay worker."
  type        = string
  default     = "1"
  validation {
    condition     = contains(["1", "2", "4", "6", "8"], var.worker_cpu)
    error_message = "Select a supported worker CPU count."
  }
}

variable "worker_memory" {
  description = "Memory includes process allocations and temporary ordering files."
  type        = string
  default     = "4Gi"
  validation {
    condition     = contains(["1Gi", "2Gi", "4Gi", "8Gi", "16Gi", "24Gi", "32Gi"], var.worker_memory)
    error_message = "Select a supported worker memory allocation."
  }
}
