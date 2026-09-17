param(
    [switch]$DryRun,
    [int]$Limit = 0
)

$scriptPath = Join-Path $PSScriptRoot 'scripts\run_review.py'
$runArgs = @($scriptPath)
if ($DryRun) { $runArgs += '--dry-run' }
if ($Limit -ne 0) { $runArgs += @('--limit', $Limit) }
$env:PYTHONIOENCODING = 'utf-8'
& python @runArgs
exit $LASTEXITCODE
