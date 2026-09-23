$ErrorActionPreference = "Stop"
$env:CODEX_LOCAL_HOME_RUNTIME_IMPORT_ONLY = "1"
. (Join-Path $PSScriptRoot "..\scripts\local-home\runtime.ps1") status
Remove-Item Env:CODEX_LOCAL_HOME_RUNTIME_IMPORT_ONLY

function Assert-Equal {
    param(
        [Parameter(Mandatory = $true)]$Actual,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if ($Actual -ne $Expected) {
        throw "$Message Expected '$Expected', got '$Actual'."
    }
}

$script:transitions = New-Object System.Collections.Generic.List[string]
$script:nativeStopCount = 0
$script:infraStopCount = 0
$script:statusQueue = New-Object System.Collections.Generic.Queue[object]
$script:transitionFailure = $null

function Import-LocalHomeEnv {}
function Test-ApiHealth { return $true }
function Stop-NativeRuntime { $script:nativeStopCount += 1 }
function Stop-LocalInfrastructure { $script:infraStopCount += 1 }
function Start-Sleep { param([int]$Seconds) }
function Invoke-RuntimeTransition {
    param([string]$Transition, [string]$TransitionReason)
    if ($script:transitionFailure) {
        throw $script:transitionFailure
    }
    $script:transitions.Add($Transition)
    return [pscustomobject]@{ state = $Transition; reason = $TransitionReason }
}
function Get-AutomationStatus {
    if ($script:statusQueue.Count -eq 0) {
        throw "No fake automation status remains."
    }
    return $script:statusQueue.Dequeue()
}

$script:statusQueue.Enqueue(
    [pscustomobject]@{
        runtime = [pscustomobject]@{
            readyToStop = $true
            runningWorkItemCount = 0
            runningWorkflowCount = 0
        }
    }
)
$Force = $false
$StopInfra = $false
$TimeoutMinutes = 30
$PollSeconds = 5
$Reason = "test clean stop"
Stop-Runtime
Assert-Equal ($script:transitions -join ",") "drain,mark-stopped" "Clean stop transitions failed."
Assert-Equal $script:nativeStopCount 1 "Clean stop must stop native processes once."
Assert-Equal $script:infraStopCount 0 "Clean stop must preserve infrastructure by default."

$script:transitions.Clear()
$script:statusQueue.Enqueue(
    [pscustomobject]@{
        runtime = [pscustomobject]@{
            readyToStop = $false
            runningWorkItemCount = 1
            runningWorkflowCount = 1
        }
    }
)
$TimeoutMinutes = 0
$timedOut = $false
try {
    Stop-Runtime
} catch {
    $timedOut = $_.Exception.Message.Contains("Drain timed out")
}
Assert-Equal $timedOut $true "Timeout must fail without forcing shutdown."
Assert-Equal $script:nativeStopCount 1 "Timeout must leave native processes running."

$script:transitions.Clear()
$Force = $true
$StopInfra = $true
$TimeoutMinutes = 30
Stop-Runtime
Assert-Equal ($script:transitions -join ",") "drain" "Forced stop must request drain first."
Assert-Equal $script:nativeStopCount 2 "Forced stop must stop native processes."
Assert-Equal $script:infraStopCount 1 "-StopInfra must stop infrastructure."

$script:transitionFailure = "API unavailable"
$Force = $false
$StopInfra = $false
$failedSafely = $false
try {
    Stop-Runtime
} catch {
    $failedSafely = $_.Exception.Message.Contains("API unavailable")
}
Assert-Equal $failedSafely $true "Safe stop must fail when the API is unavailable."
Assert-Equal $script:nativeStopCount 2 "API failure must not stop native processes."
$script:transitionFailure = $null

$firstLock = Enter-RuntimeLock
$secondLockRejected = $false
try {
    try {
        $secondLock = Enter-RuntimeLock
        $secondLock.Dispose()
    } catch {
        $secondLockRejected = $true
    }
} finally {
    $firstLock.Dispose()
}
Assert-Equal $secondLockRejected $true "Concurrent runtime commands must be rejected."

$previousAsrWorkerEnabled = [Environment]::GetEnvironmentVariable("CODEX_CLI_ASR_WORKER_ENABLED", "Process")
try {
    $script:startedProcesses = New-Object System.Collections.Generic.List[string]
    function Start-LoggedProcess {
        param([string]$Name, [string]$FilePath, [string[]]$ArgumentList)
        $script:startedProcesses.Add($Name)
    }
    function Get-ProcessSnapshot { return @() }
    function Get-InfraSnapshot { return @() }

    $env:CODEX_CLI_ASR_WORKER_ENABLED = "false"
    Assert-Equal (Test-AsrWorkerEnabled) $false "ASR worker must be disabled by false."
    Assert-Equal ((Get-RequiredWorkerProcessNames) -contains "asr-worker") $false "Disabled ASR must not be required."
    Start-WorkerProcesses
    Assert-Equal ($script:startedProcesses.Contains("asr-worker")) $false "Disabled ASR must not start."
    Assert-Equal (Get-RuntimeSnapshot).asrWorkerEnabled $false "Status must show disabled ASR."

    $script:startedProcesses.Clear()
    $env:CODEX_CLI_ASR_WORKER_ENABLED = "true"
    Assert-Equal ((Get-RequiredWorkerProcessNames) -contains "asr-worker") $true "Enabled ASR must be required."
    Start-WorkerProcesses
    Assert-Equal ($script:startedProcesses.Contains("asr-worker")) $true "Enabled ASR must start."
    Assert-Equal (Get-RuntimeSnapshot).asrWorkerEnabled $true "Status must show enabled ASR."
} finally {
    if ($null -eq $previousAsrWorkerEnabled) {
        Remove-Item Env:CODEX_CLI_ASR_WORKER_ENABLED -ErrorAction SilentlyContinue
    } else {
        $env:CODEX_CLI_ASR_WORKER_ENABLED = $previousAsrWorkerEnabled
    }
}

Write-Host "local runtime orchestration tests passed"
