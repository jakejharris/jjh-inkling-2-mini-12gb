# Check downloaded files against SHA256SUMS with Get-FileHash.
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\verify-downloads.ps1 -Dir C:\models\inkling-2-mini
# Files listed in SHA256SUMS that are not in -Dir are reported as "absent" (fine for files you skipped).
param([string]$Dir = "C:\models\inkling-2-mini")

$sums = Join-Path $PSScriptRoot "SHA256SUMS"
$bad = 0
foreach ($line in Get-Content $sums) {
    if (-not $line.Trim()) { continue }
    $want, $name = $line -split '\s+', 2
    $file = Join-Path $Dir $name
    if (-not (Test-Path -LiteralPath $file)) { "absent    $name"; continue }
    $got = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
    if ($got -eq $want) { "OK        $name" } else { "MISMATCH  $name  (got $got)"; $bad++ }
}
if ($bad) { exit 1 }
