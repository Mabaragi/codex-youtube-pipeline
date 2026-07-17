param(
    [string]$TaskName = "CodexSdkLocalHomeStart",
    [switch]$NoUi
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Initialize-LocalHomeDirs

$startScript = Join-Path $PSScriptRoot "runtime.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" start -NoBuild -KeepPaused"
if ($NoUi) {
    $arguments = "$arguments -NoUi"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $arguments `
    -WorkingDirectory $script:RepoRoot
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$repeatTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($logonTrigger, $repeatTrigger) `
    -Settings $settings `
    -Description "Keeps the Codex SDK local native Home PC runtime running." `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName'."
