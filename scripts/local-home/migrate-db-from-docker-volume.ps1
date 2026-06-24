param(
    [string]$VolumeName = "codex-sdk-home_db-data",
    [switch]$Force
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Initialize-LocalHomeDirs

$dataDir = Join-Path $script:RepoRoot "data"
$targetDb = Join-Path $dataDir "app.db"

if ((Test-Path -LiteralPath $targetDb) -and -not $Force) {
    Write-Host "Local SQLite DB already exists at $targetDb; skipping migration."
    exit 0
}

docker volume inspect $VolumeName *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker volume $VolumeName does not exist; no DB migration needed."
    exit 0
}

New-Item -ItemType Directory -Force $dataDir | Out-Null

if (Test-Path -LiteralPath $targetDb) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupPath = Join-Path $dataDir "app.db.before-docker-volume-copy.$timestamp"
    Copy-Item -LiteralPath $targetDb -Destination $backupPath -Force
    Write-Host "Backed up existing local DB to $backupPath."
}

$copyScript = "if [ ! -f /from/app.db ]; then echo 'No /from/app.db in Docker volume.'; exit 2; fi; cp /from/app.db /to/app.db"
docker run --rm -v "${VolumeName}:/from:ro" -v "${dataDir}:/to" alpine:3.22 sh -c $copyScript
if ($LASTEXITCODE -eq 2) {
    Write-Host "Docker volume exists but does not contain app.db; no DB migration needed."
    exit 0
}
if ($LASTEXITCODE -ne 0) {
    throw "Failed to copy SQLite DB from Docker volume $VolumeName."
}

Write-Host "Copied SQLite DB from Docker volume $VolumeName to $targetDb."
