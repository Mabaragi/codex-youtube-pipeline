variable "aws_region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "ap-northeast-2"
}

variable "name_prefix" {
  description = "Prefix used for named AWS resources."
  type        = string
  default     = "codex-sdk-cli"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name_prefix))
    error_message = "name_prefix must be 3-31 characters, start with a lowercase letter, and contain only lowercase letters, numbers, and hyphens."
  }
}

variable "environment" {
  description = "Environment tag value."
  type        = string
  default     = "dev"
}

variable "artifact_wheel_path" {
  description = "Path to the built codex-sdk-cli-demo wheel. Relative paths are resolved from this Terraform root."
  type        = string
  default     = "../../dist/codex_sdk_cli_demo-0.1.0-py3-none-any.whl"
}

variable "instance_type" {
  description = "EC2 instance type for the CLI host."
  type        = string
  default     = "t3.small"
}

variable "root_volume_size_gb" {
  description = "Encrypted gp3 root volume size in GiB."
  type        = number
  default     = 20

  validation {
    condition     = var.root_volume_size_gb >= 8
    error_message = "root_volume_size_gb must be at least 8."
  }
}

variable "vpc_id" {
  description = "Existing VPC id. Defaults to the account default VPC."
  type        = string
  default     = null
}

variable "subnet_id" {
  description = "Existing subnet id. Defaults to the first subnet in the selected/default VPC."
  type        = string
  default     = null
}

variable "associate_public_ip_address" {
  description = "Whether to assign a public IP. Keep true for a default public subnet without NAT."
  type        = bool
  default     = true
}

variable "ssh_key_name" {
  description = "Optional EC2 key pair name. SSM Session Manager is preferred, so this can stay null."
  type        = string
  default     = null
}

variable "ssh_cidr_blocks" {
  description = "CIDR blocks allowed to SSH when ssh_key_name is set. Empty means no SSH ingress."
  type        = list(string)
  default     = []
}

variable "read_only_s3_bucket_arns" {
  description = "Optional S3 bucket ARNs the instance may read and mount with Mountpoint for Amazon S3."
  type        = list(string)
  default     = []
}

variable "api_port" {
  description = "Host port used for the Codex FastAPI container."
  type        = number
  default     = 8000

  validation {
    condition     = var.api_port > 0 && var.api_port < 65536
    error_message = "api_port must be between 1 and 65535."
  }
}

variable "api_cidr_blocks" {
  description = "Optional public CIDR blocks allowed to reach the FastAPI container. Empty keeps the API reachable through SSM port forwarding only."
  type        = list(string)
  default     = []
}

variable "ecr_repository_name" {
  description = "ECR repository name for the Dockerized Codex API image."
  type        = string
  default     = "codex-sdk-cli"
}

variable "force_destroy_ecr_repository" {
  description = "Allow Terraform destroy to delete the ECR repository and images."
  type        = bool
  default     = true
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the deploy role, in OWNER/REPO form."
  type        = string
  default     = "Mabaragi/codex-sdk"
}

variable "github_branch" {
  description = "GitHub branch allowed to deploy through OIDC."
  type        = string
  default     = "main"
}

variable "github_allow_tag_deploys" {
  description = "Allow v* tag refs from github_repository to assume the deploy role."
  type        = bool
  default     = true
}

variable "force_destroy_artifact_bucket" {
  description = "Allow Terraform destroy to delete the artifact bucket and its objects."
  type        = bool
  default     = true
}

variable "extra_tags" {
  description = "Additional tags to apply to all supported resources."
  type        = map(string)
  default     = {}
}
