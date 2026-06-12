output "artifact_bucket" {
  description = "Private S3 bucket that stores the CLI wheel artifact."
  value       = aws_s3_bucket.artifacts.bucket
}

output "artifact_key" {
  description = "S3 object key for the uploaded CLI wheel."
  value       = aws_s3_object.cli_wheel.key
}

output "instance_id" {
  description = "EC2 instance id for the CLI host."
  value       = aws_instance.cli.id
}

output "ecr_repository_name" {
  description = "ECR repository name for the Dockerized API image."
  value       = aws_ecr_repository.app.name
}

output "ecr_repository_url" {
  description = "ECR repository URL for the Dockerized API image."
  value       = aws_ecr_repository.app.repository_url
}

output "github_actions_role_arn" {
  description = "IAM role ARN that GitHub Actions assumes through OIDC."
  value       = aws_iam_role.github_actions.arn
}

output "private_ip" {
  description = "Private IP address of the CLI host."
  value       = aws_instance.cli.private_ip
}

output "ssm_start_session_command" {
  description = "Command to open an SSM shell on the CLI host."
  value       = "aws ssm start-session --target ${aws_instance.cli.id} --region ${var.aws_region}"
}

output "ssm_port_forward_command" {
  description = "Command to forward the deployed API port to localhost without opening public ingress."
  value       = "aws ssm start-session --target ${aws_instance.cli.id} --region ${var.aws_region} --document-name AWS-StartPortForwardingSession --parameters '{\"portNumber\":[\"${var.api_port}\"],\"localPortNumber\":[\"${var.api_port}\"]}'"
}

output "public_api_url" {
  description = "Public API URL when api_cidr_blocks allows ingress."
  value       = length(var.api_cidr_blocks) > 0 && aws_instance.cli.public_ip != null ? "http://${aws_instance.cli.public_ip}:${var.api_port}" : null
}

output "post_deploy_smoke_test" {
  description = "Command to verify the installed CLI after opening an SSM session."
  value       = "codex-demo --help && codex-demo account"
}

output "s3_mount_hint" {
  description = "How to mount a permitted S3 bucket on the instance."
  value       = "sudo mkdir -p /mnt/s3/<bucket> && sudo mount-s3 --read-only <bucket> /mnt/s3/<bucket>"
}
