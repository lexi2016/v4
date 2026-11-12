[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('live', 'replay', 'backfill')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$ScheduledDate,
    [Parameter(Mandatory = $true)][string]$BusinessDate,
    [Parameter(Mandatory = $true)][string]$TargetDate,
    [Parameter(Mandatory = $true)][string]$Slot,
    [switch]$DryRun
)

$pythonExe = $env:V4_PYTHON_EXE
if ([string]::IsNullOrWhiteSpace($pythonExe) -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'V4_PYTHON_EXE must point to the pinned Python 3.14 executable.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$arguments = @(
    '-m', 'ops.run_dispatcher',
    '--mode', $Mode,
    '--scheduled-date', $ScheduledDate,
    '--business-date', $BusinessDate,
    '--target-date', $TargetDate,
    '--slot', $Slot
)
if ($DryRun) {
    $arguments += '--dry-run'
}

Push-Location $repoRoot
try {
    & $pythonExe @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
