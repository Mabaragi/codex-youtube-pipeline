param(
    [string] $Region = "ap-northeast-2",
    [switch] $Apply
)

$ErrorActionPreference = "Stop"

uv build
terraform -chdir=infra/aws-codex-cli init
terraform -chdir=infra/aws-codex-cli validate

$terraformArgs = @(
    "-chdir=infra/aws-codex-cli",
    "plan",
    "-var",
    "aws_region=$Region"
)

if ($Apply) {
    $terraformArgs[1] = "apply"
}

terraform @terraformArgs
