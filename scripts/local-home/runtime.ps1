param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "status", "drain", "resume", "stop", "restart")]
    [string]$Action = "status",
    [ValidateRange(0, 1440)]
    [int]$TimeoutMinutes = 30,
    [ValidateRange(1, 60)]
    [int]$PollSeconds = 5,
    [switch]$Force,
    [switch]$StopInfra,
    [switch]$NoBuild,
    [switch]$NoUi,
    [switch]$Json,
    [switch]$KeepPaused,
    [ValidateLength(0, 255)]
    [string]$Reason
)

. "$PSScriptRoot\common.ps1"

$script:ApiBaseUrl = "http://127.0.0.1:8000"
$script:ManagedProcessNames = @(
    "api",
    "micro-event-worker",
    "transcript-worker",
    "transcript-cue-worker",
    "asr-worker",
    "pipeline-scheduler",
    "video-availability-worker",
    "pipeline-supervisor",
    "timeline-compose-worker",
    "workflow-coordinator",
    "ops-ui"
)

function Enter-RuntimeLock {
    Initialize-LocalHomeDirs
    $lockPath = Join-Path $script:DeployDir "runtime.lock"
    try {
        return [System.IO.File]::Open(
            $lockPath,
            [System.IO.FileMode]::OpenOrCreate,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    } catch {
        throw "Another local runtime command is already in progress."
    }
}

function Test-ApiHealth {
    return Test-LocalHttp "$script:ApiBaseUrl/health" '"status"\s*:\s*"ok"'
}

function Test-VideoAvailabilityWorkerEnabled {
    return $env:CODEX_CLI_ARCHIVE_VIDEO_AVAILABILITY_ENABLED -match "^(?i:true|1|yes|on)$"
}

function Wait-ApiHealth {
    param([int]$TimeoutSeconds = 30)

    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        if (Test-ApiHealth) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "API did not become healthy within $TimeoutSeconds seconds."
}

function Get-AutomationStatus {
    if (-not (Test-ApiHealth)) {
        throw "API is unavailable; a safe runtime transition cannot be performed."
    }
    $status = Invoke-JsonUtf8 -Method Get -Uri "$script:ApiBaseUrl/ops/automation/status"
    if ($null -eq $status.runtime) {
        throw "The running API does not support drain-aware runtime control. Deploy it first."
    }
    return $status
}

function Invoke-RuntimeTransition {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("drain", "mark-stopped", "resume")]
        [string]$Transition,
        [string]$TransitionReason
    )

    if (-not (Test-ApiHealth)) {
        throw "API is unavailable; a safe runtime transition cannot be performed."
    }
    return Invoke-JsonUtf8 `
        -Method Post `
        -Uri "$script:ApiBaseUrl/ops/automation/runtime/$Transition" `
        -Body @{ reason = $TransitionReason }
}

function Get-ProcessSnapshot {
    return @(
        foreach ($name in $script:ManagedProcessNames) {
            $process = Get-ManagedProcess $name
            [pscustomobject]@{
                name = $name
                state = $(if ($process) { "running" } else { "stopped" })
                pid = $(if ($process) { $process.Id } else { $null })
            }
        }
    )
}

function Get-InfraSnapshot {
    $items = @()
    try {
        $lines = @(
            & docker compose `
                --project-name $script:ComposeProjectName `
                -f $script:InfraComposeFile `
                ps --format json 2>$null
        )
        foreach ($line in $lines) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                $item = $line | ConvertFrom-Json
                $items += [pscustomobject]@{
                    service = $item.Service
                    state = $item.State
                    health = $item.Health
                }
            }
        }
    } catch {
        return @()
    }
    return $items
}

function Get-RuntimeSnapshot {
    $apiHealthy = Test-ApiHealth
    $automation = $null
    if ($apiHealthy) {
        try {
            $automation = Invoke-JsonUtf8 `
                -Method Get `
                -Uri "$script:ApiBaseUrl/ops/automation/status"
        } catch {
            $automation = $null
        }
    }
    return [pscustomobject]@{
        observedAt = [DateTimeOffset]::Now.ToString("o")
        apiHealthy = $apiHealthy
        processes = Get-ProcessSnapshot
        infrastructure = Get-InfraSnapshot
        automationMode = $(if ($automation) { $automation.mode } else { $null })
        runtime = $(if ($automation) { $automation.runtime } else { $null })
    }
}

function Show-RuntimeStatus {
    $snapshot = Get-RuntimeSnapshot
    if ($Json) {
        $snapshot | ConvertTo-Json -Depth 12
        return
    }

    Write-Host "Repository: $script:RepoRoot"
    foreach ($process in $snapshot.processes) {
        if ($process.state -eq "running") {
            Write-Host ("{0}: running PID {1}" -f $process.name, $process.pid)
        } else {
            Write-Host ("{0}: stopped" -f $process.name)
        }
    }
    Write-Host ""
    Write-Host ("API health: {0}" -f $(if ($snapshot.apiHealthy) { "ok" } else { "unavailable" }))
    if ($snapshot.runtime) {
        Write-Host ("Automation mode: {0}" -f $snapshot.automationMode)
        Write-Host ("Runtime state: {0}" -f $snapshot.runtime.state)
        Write-Host ("Running work items: {0}" -f $snapshot.runtime.runningWorkItemCount)
        Write-Host ("Running workflows: {0}" -f $snapshot.runtime.runningWorkflowCount)
        Write-Host ("Ready to stop: {0}" -f $snapshot.runtime.readyToStop)
        if ($snapshot.runtime.drainReason) {
            Write-Host ("Drain reason: {0}" -f $snapshot.runtime.drainReason)
        }
    }
    Write-Host ""
    foreach ($container in $snapshot.infrastructure) {
        Write-Host ("{0}: {1} {2}" -f $container.service, $container.state, $container.health)
    }
}

function Start-ApiProcess {
    if (Test-ApiHealth) {
        Write-Host "api already healthy on $script:ApiBaseUrl."
        return
    }
    Start-LoggedProcess "api" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
        "-m",
        "uvicorn",
        "codex_sdk_cli.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000"
    )
    Wait-ApiHealth
}

function Start-WorkerProcesses {
    Start-LoggedProcess "pipeline-supervisor" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
        "-m",
        "codex_sdk_cli.workers.pipeline_supervisor"
    )
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
    Start-LoggedProcess "asr-worker" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
        "-m",
        "codex_sdk_cli.workers.asr"
    )
    Start-LoggedProcess "timeline-compose-worker" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
        "-c",
        '"from codex_sdk_cli.workers.timelines import run; run()"'
    )
    Start-LoggedProcess "workflow-coordinator" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
        "-c",
        '"from codex_sdk_cli.workers.workflow_coordinator import run; run()"'
    )
    if (Test-VideoAvailabilityWorkerEnabled) {
        Start-LoggedProcess "video-availability-worker" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
            "-m",
            "codex_sdk_cli.workers.video_availability"
        )
    }
}

function Start-SchedulerProcess {
    Start-LoggedProcess "pipeline-scheduler" (Join-Path $script:RepoRoot ".venv\Scripts\python.exe") @(
        "-m",
        "codex_sdk_cli.workers.pipeline_scheduler"
    )
}

function Start-OpsUiProcess {
    if ($NoUi) {
        Write-Host "Skipping ops-ui because -NoUi was provided."
        return
    }
    $nextBuildDir = Join-Path $script:RepoRoot "ops-ui\.next"
    if (-not (Test-Path -LiteralPath $nextBuildDir)) {
        Write-Host "ops-ui build output is missing. Run scripts/local-home/deploy.ps1 first."
        return
    }
    if (Test-LocalHttp "http://127.0.0.1:3000/ops") {
        Write-Host "ops-ui already reachable on http://127.0.0.1:3000/ops."
        return
    }
    Start-LoggedProcess "ops-ui" "powershell.exe" @(
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "pnpm -C ops-ui start"
    )
}

function Assert-ProcessStarted {
    param([Parameter(Mandatory = $true)][string[]]$Names)

    Start-Sleep -Seconds 2
    $missing = @($Names | Where-Object { -not (Get-ManagedProcess $_) })
    if ($missing.Count -gt 0) {
        throw "Runtime process failed to remain running: $($missing -join ', ')."
    }
}

function Start-Runtime {
    Set-Location $script:RepoRoot
    Import-LocalHomeEnv
    Start-LocalInfra
    Start-ApiProcess
    $before = Get-AutomationStatus
    Start-WorkerProcesses
    Assert-ProcessStarted @(
        "pipeline-supervisor",
        "micro-event-worker",
        "transcript-worker",
        "transcript-cue-worker",
        "asr-worker",
        "timeline-compose-worker",
        "workflow-coordinator"
    )
    if (Test-VideoAvailabilityWorkerEnabled) {
        Assert-ProcessStarted @("video-availability-worker")
    }

    if ($before.runtime.state -eq "stopped" -and -not $KeepPaused) {
        Invoke-RuntimeTransition `
            -Transition resume `
            -TransitionReason $(if ($Reason) { $Reason } else { "runtime.ps1 start" }) | Out-Null
    } elseif ($before.runtime.state -eq "draining") {
        Write-Warning "Runtime remains draining. Run 'runtime.ps1 resume' explicitly."
    }

    Start-SchedulerProcess
    Assert-ProcessStarted @("pipeline-scheduler")
    Start-OpsUiProcess
}

function Stop-NativeRuntime {
    Stop-ManagedProcess "pipeline-scheduler"
    Stop-ManagedProcess "video-availability-worker"
    Stop-ManagedProcess "workflow-coordinator"
    Stop-ManagedProcess "timeline-compose-worker"
    Stop-ManagedProcess "transcript-cue-worker"
    Stop-ManagedProcess "asr-worker"
    Stop-ManagedProcess "transcript-worker"
    Stop-ManagedProcess "micro-event-worker"
    Stop-ManagedProcess "pipeline-supervisor"
    Stop-ManagedProcess "ops-ui"
    Stop-ManagedProcess "api"
    Stop-LocalHomeRuntimeProcesses
}

function Stop-LocalInfrastructure {
    Invoke-Checked "docker" @(
        "compose",
        "--project-name",
        $script:ComposeProjectName,
        "-f",
        $script:InfraComposeFile,
        "down"
    )
}

function Stop-Runtime {
    Set-Location $script:RepoRoot
    Import-LocalHomeEnv
    $transitionReason = $(if ($Reason) { $Reason } else { "runtime.ps1 stop" })

    if ($Force) {
        if (Test-ApiHealth) {
            try {
                Invoke-RuntimeTransition `
                    -Transition drain `
                    -TransitionReason $transitionReason | Out-Null
            } catch {
                Write-Warning "Failed to persist draining state before forced stop: $($_.Exception.Message)"
            }
        }
        Stop-NativeRuntime
        if ($StopInfra) {
            Stop-LocalInfrastructure
        }
        Write-Warning "Forced stop completed. Runtime was not marked stopped and will not auto-resume."
        return
    }

    Invoke-RuntimeTransition `
        -Transition drain `
        -TransitionReason $transitionReason | Out-Null
    $deadline = [DateTimeOffset]::UtcNow.AddMinutes($TimeoutMinutes)
    while ($true) {
        $status = Get-AutomationStatus
        if ($status.runtime.readyToStop) {
            break
        }
        if ([DateTimeOffset]::UtcNow -ge $deadline) {
            throw (
                "Drain timed out after $TimeoutMinutes minute(s). " +
                "Runtime remains draining with $($status.runtime.runningWorkItemCount) " +
                "work item(s) and $($status.runtime.runningWorkflowCount) workflow(s) running."
            )
        }
        Write-Host (
            "Waiting for drain: workItems={0} workflows={1}" -f `
                $status.runtime.runningWorkItemCount,
                $status.runtime.runningWorkflowCount
        )
        Start-Sleep -Seconds $PollSeconds
    }
    Invoke-RuntimeTransition `
        -Transition "mark-stopped" `
        -TransitionReason $transitionReason | Out-Null
    Stop-NativeRuntime
    if ($StopInfra) {
        Stop-LocalInfrastructure
    }
}

if ($env:CODEX_LOCAL_HOME_RUNTIME_IMPORT_ONLY -eq "1") {
    return
}

$lock = $null
try {
    if ($Action -ne "status") {
        $lock = Enter-RuntimeLock
    }
    switch ($Action) {
        "start" { Start-Runtime }
        "status" { Show-RuntimeStatus }
        "drain" {
            Set-Location $script:RepoRoot
            Import-LocalHomeEnv
            Invoke-RuntimeTransition `
                -Transition drain `
                -TransitionReason $(if ($Reason) { $Reason } else { "runtime.ps1 drain" }) |
                ConvertTo-Json -Depth 8
        }
        "resume" {
            Set-Location $script:RepoRoot
            Import-LocalHomeEnv
            Invoke-RuntimeTransition `
                -Transition resume `
                -TransitionReason $(if ($Reason) { $Reason } else { "runtime.ps1 resume" }) |
                ConvertTo-Json -Depth 8
        }
        "stop" { Stop-Runtime }
        "restart" {
            $previous = Get-AutomationStatus
            Stop-Runtime
            if ($previous.runtime.state -eq "draining" -or $Force) {
                $KeepPaused = $true
            }
            Start-Runtime
        }
    }
} catch {
    Write-Error $_.Exception.Message
    exit 1
} finally {
    if ($lock) {
        $lock.Dispose()
    }
}
