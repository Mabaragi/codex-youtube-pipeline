param(
    [string]$ConnectionRef = "local-public-catalog"
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Import-LocalHomeEnv

Invoke-Checked "uv" @(
    "run",
    "python",
    "scripts/prepare_public_catalog.py",
    "--connection-ref",
    $ConnectionRef
)
Invoke-Checked "uv" @(
    "run",
    "python",
    "-m",
    "alembic",
    "-c",
    "catalog-alembic.ini",
    "-x",
    "connection_ref=$ConnectionRef",
    "upgrade",
    "head"
)
