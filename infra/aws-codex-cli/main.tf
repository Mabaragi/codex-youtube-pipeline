data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  count   = var.vpc_id == null ? 1 : 0
  default = true
}

data "aws_subnets" "selected" {
  filter {
    name   = "vpc-id"
    values = [local.selected_vpc_id]
  }
}

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-6.1-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "artifacts" {
  bucket        = "${var.name_prefix}-${data.aws_caller_identity.current.account_id}-${random_id.suffix.hex}"
  force_destroy = var.force_destroy_artifact_bucket
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_object" "cli_wheel" {
  bucket      = aws_s3_bucket.artifacts.id
  key         = local.artifact_key
  source      = local.artifact_wheel_path
  source_hash = filebase64sha256(local.artifact_wheel_path)
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${var.name_prefix}-instance-${random_id.suffix.hex}"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "instance" {
  statement {
    sid = "ReadCliArtifact"
    actions = [
      "s3:GetObject",
    ]
    resources = [
      "arn:aws:s3:::${aws_s3_bucket.artifacts.bucket}/${aws_s3_object.cli_wheel.key}",
    ]
  }

  dynamic "statement" {
    for_each = length(var.read_only_s3_bucket_arns) > 0 ? [1] : []

    content {
      sid = "ListConfiguredDataBuckets"
      actions = [
        "s3:ListBucket",
      ]
      resources = var.read_only_s3_bucket_arns
    }
  }

  dynamic "statement" {
    for_each = length(local.s3_object_arns) > 0 ? [1] : []

    content {
      sid = "ReadConfiguredDataObjects"
      actions = [
        "s3:GetObject",
      ]
      resources = local.s3_object_arns
    }
  }
}

resource "aws_iam_role_policy" "instance" {
  name   = "${var.name_prefix}-instance"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.name_prefix}-instance-${random_id.suffix.hex}"
  role = aws_iam_role.instance.name
}

resource "aws_security_group" "instance" {
  name        = "${var.name_prefix}-instance-${random_id.suffix.hex}"
  description = "Codex SDK CLI host"
  vpc_id      = local.selected_vpc_id

  dynamic "ingress" {
    for_each = var.ssh_key_name != null && length(var.ssh_cidr_blocks) > 0 ? [1] : []

    content {
      description = "Optional SSH access"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.ssh_cidr_blocks
    }
  }

  egress {
    description = "Outbound HTTPS and package downloads"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "cli" {
  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = var.instance_type
  subnet_id                   = local.selected_subnet_id
  associate_public_ip_address = var.associate_public_ip_address
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  vpc_security_group_ids      = [aws_security_group.instance.id]
  key_name                    = var.ssh_key_name
  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/templates/user_data.sh.tftpl", {
    artifact_bucket   = aws_s3_bucket.artifacts.bucket
    artifact_filename = basename(local.artifact_wheel_path)
    artifact_key      = aws_s3_object.cli_wheel.key
  })

  metadata_options {
    http_tokens = "required"
  }

  root_block_device {
    encrypted   = true
    volume_size = var.root_volume_size_gb
    volume_type = "gp3"
  }

  tags = {
    Name = "${var.name_prefix}-${var.environment}"
  }
}
