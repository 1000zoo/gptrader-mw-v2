$ErrorActionPreference = "Stop"

. "$PSScriptRoot\live_compression_s2_sl0030_rr045_balanced.ps1"

if (-not $env:GPTRADER_SCHEDULER_INTERVAL_SECONDS) {
    $env:GPTRADER_SCHEDULER_INTERVAL_SECONDS = "60"
}

Write-Host "Starting live strategy scheduler. Press Ctrl+C to stop."
Write-Host "Interval seconds: $env:GPTRADER_SCHEDULER_INTERVAL_SECONDS"

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
& $python -m scripts.live_strategy_scheduler
