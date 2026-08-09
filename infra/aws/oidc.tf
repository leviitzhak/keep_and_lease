data "tls_certificate" "github" { url = "https://token.actions.githubusercontent.com" }
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
}
resource "aws_iam_role" "github_production" {
  name = "${var.project_name}-github-production"
  assume_role_policy = jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Principal={Federated=aws_iam_openid_connect_provider.github.arn},Action="sts:AssumeRoleWithWebIdentity",Condition={StringEquals={"token.actions.githubusercontent.com:aud"="sts.amazonaws.com","token.actions.githubusercontent.com:sub"="repo:${var.github_owner}/${var.github_repository}:ref:refs/heads/master"}}}]})
}
resource "aws_iam_role_policy" "github_production" {
  role = aws_iam_role.github_production.id
  policy = jsonencode({Version="2012-10-17",Statement=[
    {Effect="Allow",Action=["ecr:GetAuthorizationToken"],Resource="*"},
    {Effect="Allow",Action=["ecr:BatchCheckLayerAvailability","ecr:CompleteLayerUpload","ecr:InitiateLayerUpload","ecr:PutImage","ecr:UploadLayerPart"],Resource=aws_ecr_repository.production.arn},
    {Effect="Allow",Action=["ec2:DescribeInstances","ec2:DescribeInstanceStatus"],Resource="*"},
    {Effect="Allow",Action=["ssm:SendCommand"],Resource=[aws_instance.production.arn,"arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript"]},
    {Effect="Allow",Action=["ssm:GetCommandInvocation"],Resource="*"}
  ]})
}
resource "aws_iam_role" "github_preview" {
  name = "${var.project_name}-github-preview"
  assume_role_policy = jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Principal={Federated=aws_iam_openid_connect_provider.github.arn},Action="sts:AssumeRoleWithWebIdentity",Condition={StringEquals={"token.actions.githubusercontent.com:aud"="sts.amazonaws.com","token.actions.githubusercontent.com:sub"="repo:${var.github_owner}/${var.github_repository}:pull_request"}}}]})
}
resource "aws_iam_role_policy" "github_preview" {
  role = aws_iam_role.github_preview.id
  policy = jsonencode({Version="2012-10-17",Statement=[
    {Effect="Allow",Action=["ecr:GetAuthorizationToken"],Resource="*"},
    {Effect="Allow",Action=["ecr:BatchCheckLayerAvailability","ecr:CompleteLayerUpload","ecr:InitiateLayerUpload","ecr:PutImage","ecr:UploadLayerPart"],Resource=aws_ecr_repository.preview.arn},
    {Effect="Allow",Action=["ec2:DescribeInstances","ec2:DescribeInstanceStatus"],Resource="*"},
    {Effect="Allow",Action=["ec2:StartInstances"],Resource=aws_instance.preview.arn},
    {Effect="Allow",Action=["ssm:SendCommand"],Resource=[aws_instance.preview.arn,"arn:aws:ssm:${var.aws_region}::document/AWS-RunShellScript"]},
    {Effect="Allow",Action=["ssm:GetCommandInvocation"],Resource="*"}
  ]})
}
