param(
    [string]$SourceDatabase = "data/app.db",
    [switch]$NoRestart
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Import-LocalHomeEnv

if (-not $env:CODEX_CLI_DATABASE_URL.StartsWith("postgresql+asyncpg://")) {
    throw "CODEX_CLI_DATABASE_URL must point to PostgreSQL before migration."
}

$source = [System.IO.Path]::GetFullPath((Join-Path $script:RepoRoot $SourceDatabase))
$dataRoot = [System.IO.Path]::GetFullPath((Join-Path $script:RepoRoot "data"))
if (-not $source.StartsWith($dataRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Source database must stay under $dataRoot."
}
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "SQLite source database does not exist: $source"
}

& (Join-Path $PSScriptRoot "stop.ps1")
Invoke-Checked "uv" @("run", "python", "scripts/sqlite_checkpoint.py", $source)

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $dataRoot "app.pre-postgres.$timestamp.db"
Copy-Item -LiteralPath $source -Destination $backup
Write-Host "SQLite backup: $backup"

Start-LocalPostgres
Invoke-Checked "uv" @("run", "alembic", "upgrade", "head")
Invoke-Checked "uv" @(
    "run",
    "python",
    "scripts/migrate_sqlite_to_postgres.py",
    "--source",
    $source,
    "--target-url",
    $env:CODEX_CLI_DATABASE_URL,
    "--replace"
)

if (-not $NoRestart) {
    & (Join-Path $PSScriptRoot "start.ps1") -NoBuild
}
