param(
    [ValidateSet("micro_event_extract", "timeline_compose")]
    [string]$Source,
    [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
    [int]$Tail = 120,
    [switch]$Wait,
    [switch]$Raw
)

. "$PSScriptRoot\common.ps1"

Initialize-LocalHomeDirs
Import-LocalHomeEnv

$configuredRoot = [Environment]::GetEnvironmentVariable("CODEX_CLI_LLM_TRACE_DIR", "Process")
if ([string]::IsNullOrWhiteSpace($configuredRoot)) {
    $configuredRoot = Join-Path $script:LogDir "llm-traces"
}
if ([System.IO.Path]::IsPathRooted($configuredRoot)) {
    $traceRoot = $configuredRoot
} else {
    $traceRoot = Join-Path $script:RepoRoot $configuredRoot
}
$dateDir = Join-Path $traceRoot $Date

if (-not (Test-Path -LiteralPath $dateDir)) {
    Write-Host "Missing trace date directory: $dateDir"
    exit 0
}

if ($Raw) {
    $rawDir = Join-Path $dateDir "raw"
    if (-not (Test-Path -LiteralPath $rawDir)) {
        Write-Host "Missing raw response directory: $rawDir"
        exit 0
    }
    Get-ChildItem -LiteralPath $rawDir -Filter "*.response.txt" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First $Tail -ExpandProperty FullName
    exit 0
}

if (-not $Source) {
    Get-ChildItem -LiteralPath $dateDir -Filter "*.jsonl" |
        Sort-Object Name |
        Select-Object -ExpandProperty FullName
    exit 0
}

$path = Join-Path $dateDir "$Source.jsonl"
if (-not (Test-Path -LiteralPath $path)) {
    Write-Host "Missing trace file: $path"
    exit 0
}

Write-Host "== $path =="
if ($Wait) {
    Get-Content -LiteralPath $path -Tail $Tail -Wait
} else {
    Get-Content -LiteralPath $path -Tail $Tail
}
