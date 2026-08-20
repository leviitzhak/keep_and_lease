#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-keep-and-lease}"

gcloud config set project "$PROJECT_ID"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  monitoring.googleapis.com \
  logging.googleapis.com \
  cloudresourcemanager.googleapis.com

echo "Google Cloud bootstrap APIs enabled for ${PROJECT_ID}."
