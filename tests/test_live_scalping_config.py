import subprocess


def test_live_scalping_script_loads_selected_combo_environment() -> None:
    command = (
        "$env:BINANCE_API_KEY='key'; "
        "$env:BINANCE_API_SECRET='secret'; "
        ". .\\scripts\\live_compression_s2_sl0030_rr045_balanced.ps1; "
        "Write-Output $env:GPTRADER_TRADING_STRATEGY_ID; "
        "Write-Output $env:GPTRADER_CANDLE_LIMIT; "
        "Write-Output $env:GPTRADER_STOP_LOSS_RATIO; "
        "Write-Output $env:GPTRADER_REWARD_RISK_RATIO; "
        "Write-Output $env:GPTRADER_MAX_EQUITY_RATIO; "
        "Write-Output $env:GPTRADER_MAX_LEVERAGE"
    )

    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )

    lines = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip() and not line.startswith("LIVE ARMED")
    ]
    assert lines[-6:] == [
        "live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2",
        "262",
        "0.0050",
        "0.25",
        "0.12",
        "8",
    ]
