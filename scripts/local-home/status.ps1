param(
    [switch]$Json
)

$runtime = Join-Path $PSScriptRoot "runtime.ps1"
try {
    & $runtime status -Json:$Json
    if (-not $?) {
        exit 1
    }
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
exit 0
