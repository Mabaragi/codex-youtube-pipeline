param(
    [string]$DatabasePath,
    [switch]$Rehearsal,
    [switch]$NoRestart
)

. "$PSScriptRoot\common.ps1"

Set-Location $script:RepoRoot
Import-LocalHomeEnv

function Resolve-AbsolutePath {
    param([string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $script:RepoRoot $Path))
}

function Resolve-LocalDatabasePath {
    param([string]$ExplicitPath)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        return Resolve-AbsolutePath $ExplicitPath
    }
    $prefix = "sqlite+aiosqlite:///"
    if (-not $env:CODEX_CLI_DATABASE_URL.StartsWith($prefix)) {
        throw "Work-model cutover currently supports local SQLite only."
    }
    $rawPath = [Uri]::UnescapeDataString($env:CODEX_CLI_DATABASE_URL.Substring($prefix.Length))
    if ($rawPath -match '^/[A-Za-z]:/') {
        $rawPath = $rawPath.Substring(1)
    }
    return Resolve-AbsolutePath $rawPath
}

function Stop-WorkRuntime {
    Stop-ManagedProcess "ops-ui"
    Stop-ManagedProcess "workflow-coordinator"
    Stop-ManagedProcess "timeline-compose-worker"
    Stop-ManagedProcess "pipeline-scheduler"
    Stop-ManagedProcess "transcript-cue-worker"
    Stop-ManagedProcess "transcript-worker"
    Stop-ManagedProcess "micro-event-worker"
    Stop-ManagedProcess "api"
    Stop-LocalHomeRuntimeProcesses
}

$database = Resolve-LocalDatabasePath $DatabasePath
if (-not (Test-Path -LiteralPath $database -PathType Leaf)) {
    throw "Database file does not exist: $database"
}
$databaseDirectory = [System.IO.Path]::GetDirectoryName($database)
$databaseName = [System.IO.Path]::GetFileNameWithoutExtension($database)
$databaseExtension = [System.IO.Path]::GetExtension($database)
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $databaseDirectory "$databaseName.pre-work-cutover.$timestamp$databaseExtension"
$candidate = Join-Path $databaseDirectory "$databaseName.work-candidate.$timestamp$databaseExtension"

Stop-WorkRuntime
try {
    Invoke-Checked "uv" @("run", "python", "scripts/sqlite_checkpoint.py", $database)
    if ($Rehearsal) {
        Copy-Item -LiteralPath $database -Destination $backup -ErrorAction Stop
    }
    Copy-Item -LiteralPath $database -Destination $candidate -ErrorAction Stop

    $originalDatabaseUrl = $env:CODEX_CLI_DATABASE_URL
    $candidateUrlPath = $candidate.Replace("\", "/")
    $env:CODEX_CLI_DATABASE_URL = "sqlite+aiosqlite:///$candidateUrlPath"
    try {
        Invoke-Checked "uv" @("run", "alembic", "upgrade", "head")
    } finally {
        $env:CODEX_CLI_DATABASE_URL = $originalDatabaseUrl
    }
    Invoke-Checked "uv" @(
        "run",
        "python",
        "scripts/validate_work_cutover.py",
        $database,
        $candidate
    )

    if ($Rehearsal) {
        Write-Host "Rehearsal succeeded. Candidate retained at $candidate"
        Write-Host "Backup retained at $backup"
    } else {
        [System.IO.File]::Replace($candidate, $database, $backup, $true)
        Write-Host "Work-model cutover completed. Backup retained at $backup"
    }
} catch {
    Write-Host "Cutover failed; original database was not replaced."
    Write-Host "Candidate: $candidate"
    if (Test-Path -LiteralPath $backup) {
        Write-Host "Backup: $backup"
    }
    throw
} finally {
    if (-not $NoRestart) {
        & (Join-Path $PSScriptRoot "start.ps1") -NoBuild
    }
}
