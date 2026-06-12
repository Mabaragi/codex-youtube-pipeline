locals {
  artifact_wheel_path = abspath(var.artifact_wheel_path)
  artifact_key        = "releases/${filesha256(local.artifact_wheel_path)}/${basename(local.artifact_wheel_path)}"
  selected_vpc_id     = coalesce(var.vpc_id, one(data.aws_vpc.default[*].id))
  selected_subnet_id  = coalesce(var.subnet_id, sort(data.aws_subnets.selected.ids)[0])
  s3_object_arns      = [for bucket_arn in var.read_only_s3_bucket_arns : "${bucket_arn}/*"]

  tags = merge(
    {
      Project     = "codex-sdk-cli-demo"
      Environment = var.environment
      ManagedBy   = "terraform"
    },
    var.extra_tags,
  )
}
