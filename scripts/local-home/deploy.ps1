param(
    [switch]$SkipSync,
    [switch]$SkipUiBuild,
    [switch]$NoUi,
    [switch]$SkipDockerVolumeDbMigration
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Import-LocalHomeEnv
$runtimeStateBeforeDeploy = $null
$drainAware = $false
if (Test-LocalHttp "http://127.0.0.1:8000/health" '"status"\s*:\s*"ok"') {
    try {
        $automation = Invoke-JsonUtf8 `
            -Method Get `
            -Uri "http://127.0.0.1:8000/ops/automation/status"
        if ($automation.runtime) {
            $drainAware = $true
            $runtimeStateBeforeDeploy = $automation.runtime.state
        }
    } catch {
        $drainAware = $false
    }
}

if ($drainAware) {
    & (Join-Path $PSScriptRoot "runtime.ps1") `
        stop `
        -TimeoutMinutes 30 `
        -Reason "deploy.ps1"
    if ($LASTEXITCODE -ne 0) {
        throw "Drain-aware runtime stop failed; deploy was not started."
    }
} else {
    $runningCount = 0
    if ($automation) {
        $runningCount = @(
            $automation.queues | Where-Object { $_.status -eq "running" }
        ).Count
    }
    if ($runningCount -gt 0) {
        throw "Legacy runtime has active work; wait for it to finish before the first drain-aware deploy."
    }
    Write-Warning "Drain API is unavailable. Performing the one-time idle legacy shutdown."
    Stop-ManagedProcess "ops-ui"
    Stop-ManagedProcess "workflow-coordinator"
    Stop-ManagedProcess "timeline-compose-worker"
    Stop-ManagedProcess "pipeline-scheduler"
    Stop-ManagedProcess "pipeline-supervisor"
    Stop-ManagedProcess "transcript-cue-worker"
    Stop-ManagedProcess "asr-worker"
    Stop-ManagedProcess "transcript-worker"
    Stop-ManagedProcess "micro-event-worker"
    Stop-ManagedProcess "api"
    Stop-LocalHomeRuntimeProcesses
}

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
    "config",
    "--quiet"
)

Start-LocalInfra

if (
    -not $SkipDockerVolumeDbMigration -and
    $env:CODEX_CLI_DATABASE_URL.StartsWith("sqlite")
) {
    & (Join-Path $PSScriptRoot "migrate-db-from-docker-volume.ps1")
}

Invoke-Checked "uv" @("run", "python", "-m", "alembic", "upgrade", "head")

if (-not $NoUi -and -not $SkipUiBuild) {
    Invoke-Checked "pnpm" @("-C", "ops-ui", "build")
}

$runtimeScript = Join-Path $PSScriptRoot "runtime.ps1"
& $runtimeScript start -NoUi:$NoUi -KeepPaused:$drainAware
if ($LASTEXITCODE -ne 0) {
    throw "Runtime start failed after deploy."
}
if ($runtimeStateBeforeDeploy -eq "active") {
    & $runtimeScript resume -Reason "deploy.ps1 completed"
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime resume failed after deploy."
    }
}
