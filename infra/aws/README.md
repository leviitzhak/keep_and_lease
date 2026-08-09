# AWS infrastructure automation

This directory implements the two-host design documented in
[`docs/AWS_SETUP.md`](../../docs/AWS_SETUP.md). Start with that guide. Nothing is
created by the scripts unless `apply` is passed explicitly.

The initial administrator credential is an existing named AWS CLI profile. Do not
put access keys in this repository or in GitHub. After bootstrap, GitHub Actions
uses OIDC and short-lived role credentials.

```bash
./scripts/aws/bootstrap-state.sh --profile my-admin --region eu-west-1
./scripts/aws/infrastructure.sh plan  --profile my-admin --region eu-west-1
./scripts/aws/infrastructure.sh apply --profile my-admin --region eu-west-1
```

Copy `terraform.tfvars.example` to an untracked `terraform.tfvars` and set the
GitHub repository and capacity choices before applying.

