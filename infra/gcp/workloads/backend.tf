terraform {
  backend "gcs" {
    bucket = "keep-and-lease-terraform-workloads"
    prefix = "cloud-run"
  }
}
