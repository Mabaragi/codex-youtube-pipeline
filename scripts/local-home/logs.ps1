param(
    [string]$Name,
    [int]$Tail = 120,
    [switch]$Wait
)

. "$PSScriptRoot\common.ps1"

Initialize-LocalHomeDirs

if (-not $Name) {
    Get-ChildItem -LiteralPath $script:LogDir -Filter "*.log" |
        Sort-Object Name |
        Select-Object -ExpandProperty FullName
    exit 0
}

$paths = @(
    (Join-Path $script:LogDir "$Name.log"),
    (Join-Path $script:LogDir "$Name.err.log")
)

foreach ($path in $paths) {
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host "Missing log file: $path"
        continue
    }
    Write-Host ""
    Write-Host "== $path =="
    if ($Wait) {
        Get-Content -Encoding UTF8 -LiteralPath $path -Tail $Tail -Wait
    } else {
        Get-Content -Encoding UTF8 -LiteralPath $path -Tail $Tail
    }
}
