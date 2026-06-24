$ErrorActionPreference = "Stop"

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
        foreach ($line in Get-Content -LiteralPath $script:EnvFile) {
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

    Set-DefaultEnv "CODEX_CLI_DATABASE_URL" "sqlite+aiosqlite:///./data/app.db"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_ENDPOINT" "127.0.0.1:9000"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_ACCESS_KEY" "codex"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_SECRET_KEY" "codex-transcript-dev-password"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_BUCKET" "raw"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_PREFIX" "youtube/transcripts"
    Set-DefaultEnv "CODEX_CLI_TRANSCRIPT_MINIO_SECURE" "false"
    Set-DefaultEnv "CODEX_CLI_EXTERNAL_API_CALL_MINIO_PREFIX" "external-api-calls"
    Set-DefaultEnv "CODEX_CLI_MICRO_EVENT_EXTRACT_CONCURRENCY_LIMIT" "6"
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

function Get-PidPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    return Join-Path $script:PidDir "$Name.pid"
}

function Get-ManagedProcess {
    param([Parameter(Mandatory = $true)][string]$Name)

    $pidPath = Get-PidPath $Name
    if (-not (Test-Path -LiteralPath $pidPath)) {
        return $null
    }
    $rawPid = (Get-Content -LiteralPath $pidPath -ErrorAction SilentlyContinue | Select-Object -First 1)
    $processId = 0
    if (-not [int]::TryParse($rawPid, [ref]$processId)) {
        return $null
    }
    return Get-Process -Id $processId -ErrorAction SilentlyContinue
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
        Stop-Process -Id $process.Id -Force
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

function Stop-LegacyHomeContainers {
    $legacyCompose = Join-Path $script:RepoRoot "compose.home.yaml"
    if (-not (Test-Path -LiteralPath $legacyCompose)) {
        return
    }

    Push-Location $script:RepoRoot
    try {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & docker compose `
            --project-name $script:ComposeProjectName `
            -f $legacyCompose `
            stop api micro-event-worker timeline-compose-worker ops-ui nginx ngrok 2>&1 | Out-Null
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($exitCode -eq 0) {
            Write-Host "Stopped legacy Docker app/proxy/tunnel containers."
        } else {
            Write-Host "Legacy Docker app/proxy/tunnel containers were not running."
        }
    } finally {
        if ($previousErrorActionPreference) {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        Pop-Location
    }
}
