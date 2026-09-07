data "archive_file" "idle_stop" {
  type        = "zip"
  source_file = "${path.module}/lambda/idle_stop.py"
  output_path = "${path.module}/.terraform/idle_stop.zip"
}
resource "aws_iam_role" "idle_stop" {
  name = "${var.project_name}-preview-idle-stop"
  assume_role_policy = jsonencode({Version="2012-10-17",Statement=[{Effect="Allow",Principal={Service="lambda.amazonaws.com"},Action="sts:AssumeRole"}]})
}
resource "aws_iam_role_policy" "idle_stop" {
  role = aws_iam_role.idle_stop.id
  policy = jsonencode({Version="2012-10-17",Statement=[
    {Effect="Allow",Action=["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"],Resource="*"},
    {Effect="Allow",Action=["ec2:DescribeInstances","ec2:StopInstances"],Resource="*"},
    {Effect="Allow",Action=["ssm:GetParameter"],Resource=aws_ssm_parameter.preview_activity.arn}
  ]})
}
resource "aws_lambda_function" "idle_stop" {
  function_name    = "${var.project_name}-preview-idle-stop"
  role             = aws_iam_role.idle_stop.arn
  handler          = "idle_stop.handler"
  runtime          = "python3.13"
  filename         = data.archive_file.idle_stop.output_path
  source_code_hash = data.archive_file.idle_stop.output_base64sha256
  environment { variables = { INSTANCE_ID=aws_instance.preview.id, ACTIVITY_PARAMETER=aws_ssm_parameter.preview_activity.name, IDLE_SECONDS=tostring(var.preview_idle_minutes * 60) } }
}
resource "aws_cloudwatch_event_rule" "idle_stop" { name = "${var.project_name}-preview-idle-stop"
  schedule_expression = "rate(5 minutes)" }
resource "aws_cloudwatch_event_target" "idle_stop" { rule = aws_cloudwatch_event_rule.idle_stop.name
  arn = aws_lambda_function.idle_stop.arn }
resource "aws_lambda_permission" "idle_stop" { statement_id="AllowEventBridge"
  action="lambda:InvokeFunction"
  function_name=aws_lambda_function.idle_stop.function_name
  principal="events.amazonaws.com"
  source_arn=aws_cloudwatch_event_rule.idle_stop.arn }

