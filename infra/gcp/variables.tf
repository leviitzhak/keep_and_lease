variable "project_id" {
  description = "Dedicated Google Cloud project ID."
  type        = string
  default     = "keep-and-lease"
}

variable "region" {
  description = "Primary Google Cloud region."
  type        = string
  default     = "me-west1"
}

variable "firestore_location" {
  description = "Firestore database location; review before the first apply."
  type        = string
  default     = "me-west1"
}

variable "github_repository" {
  description = "GitHub repository allowed to federate to the deployment identity."
  type        = string
  default     = "leviitzhak/keep_and_lease"
}

variable "result_retention_days" {
  description = "Days before unpinned calculation results are deleted."
  type        = number
  default     = 90
}
