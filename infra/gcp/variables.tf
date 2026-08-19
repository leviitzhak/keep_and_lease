variable "project_id" { type = string; default = "keep-and-lease" }
variable "region" { type = string; default = "me-west1" }
variable "firestore_location" { type = string; default = "me-west1" }
variable "github_repository" { type = string; default = "leviitzhak/keep_and_lease" }
variable "result_retention_days" { type = number; default = 90 }
