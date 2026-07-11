param(
    [switch]$StopInfra
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Import-LocalHomeEnv

Stop-ManagedProcess "ops-ui"
Stop-ManagedProcess "timeline-compose-worker"
Stop-ManagedProcess "pipeline-scheduler"
Stop-ManagedProcess "transcript-cue-worker"
Stop-ManagedProcess "transcript-worker"
Stop-ManagedProcess "micro-event-worker"
Stop-ManagedProcess "api"
Stop-LocalHomeRuntimeProcesses

if ($StopInfra) {
    Invoke-Checked "docker" @(
        "compose",
        "--project-name",
        $script:ComposeProjectName,
        "-f",
        $script:InfraComposeFile,
        "down"
    )
}
