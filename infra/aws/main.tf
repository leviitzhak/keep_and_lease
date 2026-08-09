data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }
data "aws_ami" "al2023_arm" {
  most_recent = true
  owners      = ["amazon"]
  filter { name = "name"
  values = ["al2023-ami-2023*-arm64"] }
  filter { name = "state"
  values = ["available"] }
}

locals {
  activity_parameter = "/${var.project_name}/preview/activity"
  common_user_data = <<-EOF
    #!/bin/bash
    set -euxo pipefail
    dnf update -y
    dnf install -y docker awscli
    systemctl enable --now docker
    usermod -aG docker ec2-user
    mkdir -p /opt/${var.project_name}
  EOF
}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}
resource "aws_internet_gateway" "main" { vpc_id = aws_vpc.main.id }
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.42.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true
}
resource "aws_route_table" "public" { vpc_id = aws_vpc.main.id
  route { cidr_block = "0.0.0.0/0"
  gateway_id = aws_internet_gateway.main.id }
}
resource "aws_route_table_association" "public" {
  subnet_id = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}
resource "aws_security_group" "web" {
  name_prefix = "${var.project_name}-web-"
  vpc_id      = aws_vpc.main.id
  ingress { from_port = 80
  to_port = 80
  protocol = "tcp"
  cidr_blocks = ["0.0.0.0/0"] }
  ingress { from_port = 443
  to_port = 443
  protocol = "tcp"
  cidr_blocks = ["0.0.0.0/0"] }
  egress { from_port = 0
  to_port = 0
  protocol = "-1"
  cidr_blocks = ["0.0.0.0/0"] }
}

resource "aws_iam_role" "instance" {
  name = "${var.project_name}-instance"
  assume_role_policy = jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Principal={Service="ec2.amazonaws.com"},Action="sts:AssumeRole"}]})
}
resource "aws_iam_role_policy_attachment" "ssm" {
  role = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_role_policy" "instance" {
  role = aws_iam_role.instance.id
  policy = jsonencode({Version="2012-10-17",Statement=[
    {Effect="Allow",Action=["ecr:GetAuthorizationToken"],Resource="*"},
    {Effect="Allow",Action=["ecr:BatchCheckLayerAvailability","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],Resource=[aws_ecr_repository.production.arn,aws_ecr_repository.preview.arn]},
    {Effect="Allow",Action=["ssm:GetParameter","ssm:PutParameter"],Resource=aws_ssm_parameter.preview_activity.arn}
  ]})
}
resource "aws_iam_instance_profile" "instance" { name = "${var.project_name}-instance"
  role = aws_iam_role.instance.name }

resource "aws_instance" "production" {
  ami                    = data.aws_ami.al2023_arm.id
  instance_type          = var.production_instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name
  user_data              = local.common_user_data
  root_block_device { volume_type = "gp3"
  volume_size = var.root_volume_gb
  encrypted = true }
  metadata_options { http_tokens = "required" }
  tags = { Name = "${var.project_name}-production", Environment = "production" }
}
resource "aws_instance" "preview" {
  ami                    = data.aws_ami.al2023_arm.id
  instance_type          = var.preview_instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name
  user_data              = local.common_user_data
  root_block_device { volume_type = "gp3"
  volume_size = var.root_volume_gb
  encrypted = true }
  metadata_options { http_tokens = "required" }
  tags = { Name = "${var.project_name}-preview", Environment = "preview", AutoStop = "true" }
}
resource "aws_eip" "production" { domain = "vpc"
  instance = aws_instance.production.id }
resource "aws_eip" "preview" { count = var.retain_preview_elastic_ip ? 1 : 0
  domain = "vpc"
  instance = aws_instance.preview.id }
resource "aws_ecr_repository" "production" { name = "${var.project_name}/production"
  image_scanning_configuration { scan_on_push = true } }
resource "aws_ecr_repository" "preview" { name = "${var.project_name}/preview"
  image_scanning_configuration { scan_on_push = true } }
resource "aws_ssm_parameter" "preview_activity" { name = local.activity_parameter
  type = "String"
  value = "0:0"
  lifecycle { ignore_changes = [value] } }

