. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Import-LocalHomeEnv

function Write-ProcessStatus {
    param([Parameter(Mandatory = $true)][string]$Name)

    $process = Get-ManagedProcess $Name
    if ($process) {
        Write-Host ("{0}: running PID {1}" -f $Name, $process.Id)
    } else {
        Write-Host ("{0}: stopped" -f $Name)
    }
}

Write-Host "Repository: $script:RepoRoot"
Write-Host "Env file: $script:EnvFile"
Write-Host "Database: $env:CODEX_CLI_DATABASE_URL"
Write-Host "MinIO endpoint: $env:CODEX_CLI_TRANSCRIPT_MINIO_ENDPOINT"
Write-Host ""

Write-ProcessStatus "api"
Write-ProcessStatus "micro-event-worker"
Write-ProcessStatus "transcript-worker"
Write-ProcessStatus "transcript-cue-worker"
Write-ProcessStatus "pipeline-scheduler"
Write-ProcessStatus "timeline-compose-worker"
Write-ProcessStatus "ops-ui"
Write-Host ""

if (Test-LocalHttp "http://127.0.0.1:8000/health" '"status"\s*:\s*"ok"') {
    Write-Host "API health: ok"
} else {
    Write-Host "API health: unavailable"
}

if (Test-LocalHttp "http://127.0.0.1:3000/ops") {
    Write-Host "Ops UI: ok"
} else {
    Write-Host "Ops UI: unavailable"
}

Write-Host ""
Invoke-Checked "docker" @(
    "compose",
    "--project-name",
    $script:ComposeProjectName,
    "-f",
    $script:InfraComposeFile,
    "ps",
    "minio"
)
