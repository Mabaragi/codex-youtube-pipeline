param(
    [switch]$StopInfra,
    [switch]$Force,
    [ValidateRange(0, 1440)]
    [int]$TimeoutMinutes = 30
)

$runtime = Join-Path $PSScriptRoot "runtime.ps1"
try {
    & $runtime `
        stop `
        -TimeoutMinutes $TimeoutMinutes `
        -StopInfra:$StopInfra `
        -Force:$Force
    if (-not $?) {
        exit 1
    }
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
exit 0
