variable "aws_region" { type = string
  default = "eu-west-1" }
variable "aws_profile" { type = string
  default = "" }
variable "project_name" { type = string
  default = "keep-and-lease" }
variable "github_owner" { type = string }
variable "github_repository" { type = string
  default = "keep_and_lease" }
variable "production_instance_type" { type = string
  default = "t4g.small" }
variable "production_instance_state" {
  type        = string
  default     = "stopped"
  description = "Desired production EC2 state. Keep stopped until production deployment is ready."
  validation {
    condition     = contains(["running", "stopped"], var.production_instance_state)
    error_message = "production_instance_state must be either running or stopped."
  }
}
variable "preview_instance_type" { type = string
  default = "t4g.small" }
variable "root_volume_gb" { type = number
  default = 20 }
variable "preview_idle_minutes" { type = number
  default = 60 }
variable "retain_preview_elastic_ip" { type = bool
  default = false }
