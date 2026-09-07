terraform {
  backend "gcs" {
    bucket = "keep-and-lease-terraform-state"
    prefix = "foundation"
  }
}
