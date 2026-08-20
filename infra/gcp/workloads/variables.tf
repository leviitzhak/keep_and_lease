variable "project_id" {
  type    = string
  default = "keep-and-lease"
}

variable "region" {
  type    = string
  default = "me-west1"
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

variable "allow_unauthenticated" {
  description = "Expose billable job submission publicly; false for the private proof of concept."
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
