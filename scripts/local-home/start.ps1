param(
    [switch]$NoBuild,
    [switch]$NoUi
)

$runtime = Join-Path $PSScriptRoot "runtime.ps1"
try {
    & $runtime start -NoBuild:$NoBuild -NoUi:$NoUi
    if (-not $?) {
        exit 1
    }
} catch {
    Write-Error $_.Exception.Message
    exit 1
}
exit 0
