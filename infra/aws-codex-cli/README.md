# AWS EC2 Deployment

This Terraform root deploys the `codex-demo` CLI onto one Amazon Linux 2023 EC2
instance.

## What It Creates

- Private S3 artifact bucket for the built wheel.
- EC2 IAM role with SSM Session Manager access.
- EC2 IAM read access to the wheel artifact.
- Optional read-only S3 bucket access for data buckets.
- Security group with no inbound access by default.
- Amazon Linux 2023 instance that installs `codex-demo`, `uv`, and Mountpoint
  for Amazon S3.

The Codex SDK launches the bundled Codex runtime from the installed
`openai-codex-cli-bin` package. Account login and thread state live on the EC2
host under the Linux user that runs `codex-demo`.

## Deploy

From the repository root:

```powershell
aws sts get-caller-identity --region ap-northeast-2
aws login --remote --region ap-northeast-2 # only when the session is expired
```

Then build and apply:

```powershell
uv build
terraform -chdir=infra/aws-codex-cli init
terraform -chdir=infra/aws-codex-cli apply
```

Open a shell through SSM:

```powershell
aws ssm start-session --target <instance-id> --region ap-northeast-2
```

Verify the CLI:

```bash
codex-demo --help
codex-demo login device
codex-demo account
```

## Optional S3 Data Access

Grant the instance read access to existing data buckets:

```powershell
terraform -chdir=infra/aws-codex-cli apply `
  -var 'read_only_s3_bucket_arns=["arn:aws:s3:::my-data-bucket"]'
```

Inside the instance:

```bash
sudo codex-s3-mount my-data-bucket /mnt/s3/my-data-bucket
codex-demo run --cwd /mnt/s3/my-data-bucket "이 데이터 구조를 분석해줘"
```

Mountpoint for Amazon S3 is best for read-heavy object access. Treat it as an
S3 object view, not a fully POSIX-compatible local disk.

## Destroy

```powershell
terraform -chdir=infra/aws-codex-cli destroy
```
