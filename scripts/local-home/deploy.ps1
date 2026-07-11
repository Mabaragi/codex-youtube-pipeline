param(
    [switch]$SkipSync,
    [switch]$SkipUiBuild,
    [switch]$NoUi,
    [switch]$SkipDockerVolumeDbMigration
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Import-LocalHomeEnv
Stop-ManagedProcess "ops-ui"
Stop-ManagedProcess "workflow-coordinator"
Stop-ManagedProcess "timeline-compose-worker"
Stop-ManagedProcess "pipeline-scheduler"
Stop-ManagedProcess "transcript-cue-worker"
Stop-ManagedProcess "transcript-worker"
Stop-ManagedProcess "micro-event-worker"
Stop-ManagedProcess "api"
Stop-LocalHomeRuntimeProcesses

if (-not $SkipSync) {
    Invoke-Checked "uv" @("sync", "--dev", "--locked")
    Invoke-Checked "corepack" @("enable")
    Invoke-Checked "pnpm" @("install", "--frozen-lockfile")
}

Invoke-Checked "docker" @(
    "compose",
    "--project-name",
    $script:ComposeProjectName,
    "-f",
    $script:InfraComposeFile,
    "config"
)

Start-LocalMinio

if (-not $SkipDockerVolumeDbMigration) {
    & (Join-Path $PSScriptRoot "migrate-db-from-docker-volume.ps1")
}

Invoke-Checked "uv" @("run", "alembic", "upgrade", "head")

if (-not $NoUi -and -not $SkipUiBuild) {
    Invoke-Checked "pnpm" @("-C", "ops-ui", "build")
}

$startScript = Join-Path $PSScriptRoot "start.ps1"
if ($NoUi) {
    & $startScript -NoBuild -NoUi
} else {
    & $startScript -NoBuild
}
