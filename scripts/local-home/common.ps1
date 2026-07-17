$ErrorActionPreference = "Stop"
$script:Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $script:Utf8NoBom
[Console]::InputEncoding = $script:Utf8NoBom
[Console]::OutputEncoding = $script:Utf8NoBom
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$PSDefaultParameterValues["Get-Content:Encoding"] = "utf8"
$PSDefaultParameterValues["Select-String:Encoding"] = "utf8"
$PSDefaultParameterValues["Out-File:Encoding"] = "utf8"
$PSDefaultParameterValues["Set-Content:Encoding"] = "utf8"
$PSDefaultParameterValues["Add-Content:Encoding"] = "utf8"
$PSDefaultParameterValues["Import-Csv:Encoding"] = "utf8"
$PSDefaultParameterValues["Export-Csv:Encoding"] = "utf8"
try {
    chcp 65001 | Out-Null
} catch {
    # Keep local scripts usable in hosts that do not expose chcp.
}

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$script:DeployDir = Join-Path $script:RepoRoot ".home-deploy"
$script:PidDir = Join-Path $script:DeployDir "pids"
$script:LogDir = Join-Path $script:DeployDir "logs"
$script:EnvFile = Join-Path $script:DeployDir "local.env"
$script:InfraComposeFile = Join-Path $script:RepoRoot "compose.local-infra.yaml"
$script:ComposeProjectName = "codex-sdk-home"

function Initialize-LocalHomeDirs {
    New-Item -ItemType Directory -Force $script:DeployDir | Out-Null
    New-Item -ItemType Directory -Force $script:PidDir | Out-Null
    New-Item -ItemType Directory -Force $script:LogDir | Out-Null
}

function Set-DefaultEnv {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $current = [Environment]::GetEnvironmentVariable($Name, "Process")
    if ([string]::IsNullOrWhiteSpace($current)) {
        [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
    }
}

function Import-LocalHomeEnv {
    Initialize-LocalHomeDirs

    if (Test-Path -LiteralPath $script:EnvFile) {
        foreach ($line in Get-Content -Encoding UTF8 -LiteralPath $script:EnvFile) {
            $trimmed = $line.Trim()
            if (-not $trimmed -or $trimmed.StartsWith("#")) {
                continue
            }
            $separator = $trimmed.IndexOf("=")
            if ($separator -le 0) {
                continue
            }
            $name = $trimmed.Substring(0, $separator).Trim()
            $value = $trimmed.Substring($separator + 1).Trim()
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }

    Set-DefaultEnv "POSTGRES_DB" "codex"
    Set-DefaultEnv "POSTGRES_USER" "codex"
    Set-DefaultEnv "POSTGRES_PASSWORD" "CHANGE_ME_POSTGRES_PASSWORD"
    Set-DefaultEnv "POSTGRES_PORT" "5432"
    Set-DefaultEnv "CODEX_CLI_DATABASE_URL" "postgresql+asyncpg://codex:CHANGE_ME_POSTGRES_PASSWORD@127.0.0.1:5432/codex"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_ENDPOINT" "127.0.0.1:9000"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_ACCESS_KEY" "CHANGE_ME_MINIO_ACCESS_KEY"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_SECRET_KEY" "CHANGE_ME_MINIO_SECRET"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_BUCKET" "raw"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_PREFIX" "youtube/transcripts"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_SECURE" "false"
    Set-DefaultEnv "CODEX_CLI_EXTERNAL_API_CALL_MINIO_PREFIX" "external-api-calls"
    Set-DefaultEnv "CODEX_CLI_PIPELINE_SCHEDULER_ENABLED" "true"
    Set-DefaultEnv "CODEX_CLI_PIPELINE_SCHEDULER_CHANNEL_INTERVAL_SECONDS" "7200"
    Set-DefaultEnv "CODEX_CLI_PIPELINE_SCHEDULER_TRANSCRIPT_FALLBACK_GRACE_SECONDS" "21600"
    Set-DefaultEnv "CODEX_CLI_PIPELINE_SCHEDULER_TRANSCRIPT_RECHECK_INTERVAL_SECONDS" "1800"
    Set-DefaultEnv "CODEX_CLI_MICRO_EVENT_EXTRACT_CONCURRENCY_LIMIT" "1"
    Set-DefaultEnv "CODEX_CLI_MICRO_EVENT_WINDOW_CONCURRENCY_LIMIT" "6"
    Set-DefaultEnv "CODEX_CLI_SANDBOX" "workspace-write"
    Set-DefaultEnv "CODEX_CLI_APPROVAL" "auto-review"
    Set-DefaultEnv "CODEX_OPS_BACKEND_BASE_URL" "http://127.0.0.1:8000"
    Set-DefaultEnv "HOSTNAME" "127.0.0.1"
    Set-DefaultEnv "PORT" "3000"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [string]$WorkingDirectory = $script:RepoRoot
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath $($ArgumentList -join ' ') failed with exit code $LASTEXITCODE."
        }
    } finally {
        Pop-Location
    }
}

function Invoke-JsonUtf8 {
    param(
        [ValidateSet("Get", "Post", "Put", "Patch", "Delete")]
        [string]$Method = "Post",
        [Parameter(Mandatory = $true)][string]$Uri,
        [object]$Body = $null,
        [int]$Depth = 20,
        [hashtable]$Headers = @{},
        [int]$TimeoutSec = 100
    )

    $parameters = @{
        Method = $Method
        Uri = $Uri
        Headers = $Headers
        TimeoutSec = $TimeoutSec
        UseBasicParsing = $true
    }
    if ($null -ne $Body) {
        if ($Body -is [string]) {
            $json = $Body
        } else {
            $json = $Body | ConvertTo-Json -Depth $Depth
        }
        $parameters["ContentType"] = "application/json; charset=utf-8"
        $parameters["Body"] = [System.Text.Encoding]::UTF8.GetBytes($json)
    }

    $response = Invoke-WebRequest @parameters
    if (-not $response.RawContentStream) {
        return $null
    }
    $response.RawContentStream.Position = 0
    $reader = New-Object System.IO.StreamReader(
        $response.RawContentStream,
        [System.Text.Encoding]::UTF8,
        $true
    )
    try {
        $content = $reader.ReadToEnd()
    } finally {
        $reader.Dispose()
    }
    if ([string]::IsNullOrWhiteSpace($content)) {
        return $null
    }
    return $content | ConvertFrom-Json
}

function Get-PidPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    return Join-Path $script:PidDir "$Name.pid"
}

function Test-ManagedProcessIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$ProcessId
    )

    $runtime = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $runtime -or [string]::IsNullOrWhiteSpace($runtime.CommandLine)) {
        return $false
    }
    $commandLine = $runtime.CommandLine.ToLowerInvariant()
    $repoRoot = $script:RepoRoot.ToLowerInvariant()
    $marker = switch ($Name) {
        "api" { "codex_sdk_cli.api.main:app" }
        "micro-event-worker" { "codex_sdk_cli.workers.micro_events" }
        "transcript-worker" { "run_transcript; run_transcript()" }
        "transcript-cue-worker" { "run_transcript_cue; run_transcript_cue()" }
        "asr-worker" { "codex_sdk_cli.workers.asr" }
        "pipeline-scheduler" { "codex_sdk_cli.workers.pipeline_scheduler" }
        "pipeline-supervisor" { "codex_sdk_cli.workers.pipeline_supervisor" }
        "timeline-compose-worker" { "codex_sdk_cli.workers.timelines" }
        "workflow-coordinator" { "codex_sdk_cli.workers.workflow_coordinator" }
        "ops-ui" { "pnpm -c ops-ui start" }
        default { return $false }
    }
    if (-not $commandLine.Contains($marker)) {
        return $false
    }
    return $Name -eq "ops-ui" -or $commandLine.Contains($repoRoot)
}

function Get-ManagedProcess {
    param([Parameter(Mandatory = $true)][string]$Name)

    $pidPath = Get-PidPath $Name
    if (-not (Test-Path -LiteralPath $pidPath)) {
        return $null
    }
    $rawPid = (
        Get-Content -Encoding UTF8 -LiteralPath $pidPath -ErrorAction SilentlyContinue |
            Select-Object -First 1
    )
    $processId = 0
    if (-not [int]::TryParse($rawPid, [ref]$processId)) {
        return $null
    }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process -or -not (Test-ManagedProcessIdentity -Name $Name -ProcessId $processId)) {
        return $null
    }
    return $process
}

function Stop-ProcessTree {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $allProcesses = @(Get-CimInstance Win32_Process)
    $descendants = New-Object System.Collections.Generic.List[int]
    $pending = New-Object System.Collections.Generic.Queue[int]
    $pending.Enqueue($ProcessId)

    while ($pending.Count -gt 0) {
        $parentId = $pending.Dequeue()
        foreach ($child in $allProcesses | Where-Object { $_.ParentProcessId -eq $parentId }) {
            if ($child.ProcessId -ne $PID -and -not $descendants.Contains([int]$child.ProcessId)) {
                $descendants.Add([int]$child.ProcessId)
                $pending.Enqueue([int]$child.ProcessId)
            }
        }
    }

    for ($index = $descendants.Count - 1; $index -ge 0; $index--) {
        Stop-Process -Id $descendants[$index] -Force -ErrorAction SilentlyContinue
    }
    if ($ProcessId -ne $PID) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Get-LocalHomeRuntimeProcesses {
    $escapedRepoRoot = [regex]::Escape($script:RepoRoot)
    $escapedRepoRootLower = [regex]::Escape($script:RepoRoot.ToLowerInvariant())

    return Get-CimInstance Win32_Process | Where-Object {
        if ($_.ProcessId -eq $PID) {
            return $false
        }

        $commandLine = $_.CommandLine
        if ([string]::IsNullOrWhiteSpace($commandLine)) {
            return $false
        }
        $lowerCommandLine = $commandLine.ToLowerInvariant()
        $isRepoProcess = $commandLine -match $escapedRepoRoot -or $lowerCommandLine -match $escapedRepoRootLower
        $isKnownRuntime = (
            $lowerCommandLine -match "codex_sdk_cli\.api\.main:app" -or
            $lowerCommandLine -match "codex-micro-event-worker" -or
            $lowerCommandLine -match "codex_sdk_cli\.workers\.micro_events" -or
            $lowerCommandLine -match "codex-transcript-worker" -or
            $lowerCommandLine -match "codex-transcript-cue-worker" -or
            $lowerCommandLine -match "codex_sdk_cli\.workers\.transcripts" -or
            $lowerCommandLine -match "codex-asr-worker" -or
            $lowerCommandLine -match "codex_sdk_cli\.workers\.asr" -or
            $lowerCommandLine -match "codex-pipeline-scheduler" -or
            $lowerCommandLine -match "codex_sdk_cli\.workers\.pipeline_scheduler" -or
            $lowerCommandLine -match "codex-pipeline-supervisor" -or
            $lowerCommandLine -match "codex_sdk_cli\.workers\.pipeline_supervisor" -or
            $lowerCommandLine -match "codex-timeline-compose-worker" -or
            $lowerCommandLine -match "codex_sdk_cli\.workers\.timelines" -or
            $lowerCommandLine -match "codex-workflow-coordinator" -or
            $lowerCommandLine -match "codex_sdk_cli\.workers\.workflow_coordinator" -or
            $lowerCommandLine -match "ops-ui[\\/]\.next[\\/]standalone" -or
            $lowerCommandLine -match "scripts[\\/]start-standalone\.mjs" -or
            $lowerCommandLine -match "pnpm(?:\.cmd)?\s+-c\s+ops-ui\s+start"
        )
        return $isKnownRuntime -and ($isRepoProcess -or $lowerCommandLine -match "pnpm(?:\.cmd)?\s+-c\s+ops-ui\s+start" -or $lowerCommandLine -match "scripts[\\/]start-standalone\.mjs")
    }
}

function Stop-LocalHomeRuntimeProcesses {
    $processes = @(Get-LocalHomeRuntimeProcesses)
    if ($processes.Count -eq 0) {
        Write-Host "No orphan local runtime processes found."
        return
    }

    foreach ($process in $processes) {
        Write-Host "Stopping orphan local runtime process PID $($process.ProcessId) ($($process.Name))."
        Stop-ProcessTree -ProcessId ([int]$process.ProcessId)
    }
}

function Test-LocalHttp {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [string]$Contains
    )

    try {
        $response = Invoke-WebRequest -Uri $Uri -TimeoutSec 5 -UseBasicParsing
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
            return $false
        }
        if ($Contains -and $response.Content -notmatch $Contains) {
            return $false
        }
        return $true
    } catch {
        return $false
    }
}

function Start-LoggedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [string]$WorkingDirectory = $script:RepoRoot
    )

    $existing = Get-ManagedProcess $Name
    if ($existing) {
        Write-Host "$Name already running with PID $($existing.Id)."
        return
    }

    Initialize-LocalHomeDirs
    $stdout = Join-Path $script:LogDir "$Name.log"
    $stderr = Join-Path $script:LogDir "$Name.err.log"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    $process.Id | Set-Content -Encoding ascii -LiteralPath (Get-PidPath $Name)
    Write-Host "Started $Name with PID $($process.Id)."
}

function Stop-ManagedProcess {
    param([Parameter(Mandatory = $true)][string]$Name)

    $process = Get-ManagedProcess $Name
    if ($process) {
        Stop-ProcessTree -ProcessId $process.Id
        Write-Host "Stopped $Name with PID $($process.Id)."
    } else {
        Write-Host "$Name is not running."
    }
    $pidPath = Get-PidPath $Name
    if (Test-Path -LiteralPath $pidPath) {
        Remove-Item -LiteralPath $pidPath -Force
    }
}

function Start-LocalMinio {
    Import-LocalHomeEnv
    Invoke-Checked "docker" @(
        "compose",
        "--project-name",
        $script:ComposeProjectName,
        "-f",
        $script:InfraComposeFile,
        "up",
        "-d",
        "minio"
    )
}

function Start-LocalPostgres {
    Import-LocalHomeEnv
    Invoke-Checked "docker" @(
        "compose",
        "--project-name",
        $script:ComposeProjectName,
        "-f",
        $script:InfraComposeFile,
        "up",
        "-d",
        "--wait",
        "postgres"
    )
}

function Start-LocalInfra {
    Start-LocalPostgres
    Start-LocalMinio
}
