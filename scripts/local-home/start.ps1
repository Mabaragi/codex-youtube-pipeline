param(
    [switch]$NoBuild,
    [switch]$NoUi
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Import-LocalHomeEnv
Start-LocalMinio

if (Test-LocalHttp "http://127.0.0.1:8000/health" '"status"\s*:\s*"ok"') {
    Write-Host "api already healthy on http://127.0.0.1:8000."
} else {
    Start-LoggedProcess "api" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
        "-m",
        "uvicorn",
        "codex_sdk_cli.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000"
    )
}

Start-LoggedProcess "micro-event-worker" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
    "-c",
    '"from codex_sdk_cli.workers.micro_events import run; run()"'
)
Start-LoggedProcess "transcript-worker" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
    "-c",
    '"from codex_sdk_cli.workers.transcripts import run_transcript; run_transcript()"'
)
Start-LoggedProcess "transcript-cue-worker" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
    "-c",
    '"from codex_sdk_cli.workers.transcripts import run_transcript_cue; run_transcript_cue()"'
)
Start-LoggedProcess "pipeline-scheduler" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
    "-m",
    "codex_sdk_cli.workers.pipeline_scheduler"
)
Start-LoggedProcess "timeline-compose-worker" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
    "-c",
    '"from codex_sdk_cli.workers.timelines import run; run()"'
)

if ($NoUi) {
    Write-Host "Skipping ops-ui because -NoUi was provided."
    exit 0
}

$nextBuildDir = Join-Path $script:RepoRoot "ops-ui\.next"
if (-not (Test-Path -LiteralPath $nextBuildDir)) {
    Write-Host "ops-ui build output is missing. Run scripts/local-home/deploy.ps1 first."
    exit 0
}

if (Test-LocalHttp "http://127.0.0.1:3000/ops") {
    Write-Host "ops-ui already reachable on http://127.0.0.1:3000/ops."
} else {
    Start-LoggedProcess "ops-ui" "powershell.exe" @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "pnpm -C ops-ui start"
    )
}
