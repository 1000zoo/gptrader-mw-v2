$ErrorActionPreference = "Stop"

if (-not $env:BINANCE_API_KEY -or -not $env:BINANCE_API_SECRET) {
    throw "Set BINANCE_API_KEY and BINANCE_API_SECRET before arming live trading."
}

$env:GPTRADER_MODE = "live-armed"
$env:GPTRADER_LIVE_ARMED = "true"
$env:GPTRADER_SYMBOL = "BTCUSDT"
$env:GPTRADER_TIMEFRAME = "1m"
$env:GPTRADER_CANDLE_LIMIT = "262"
$env:GPTRADER_CLIENT_ORDER_ID_PREFIX = "gptrader-live-scalp-multi"
$env:GPTRADER_GENERATOR_ID = "live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2"
$env:GPTRADER_SIGNAL_ID_PREFIX = "live-scalp-multi"
$env:GPTRADER_TRADING_STRATEGY_ID = "live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2"
$env:GPTRADER_TAKE_PROFIT_STOP_LOSS = "fixed"
$env:GPTRADER_STOP_LOSS_RATIO = "0.0050"
$env:GPTRADER_REWARD_RISK_RATIO = "0.25"
$env:GPTRADER_POSITION_SIZING = "confidence"
$env:GPTRADER_MIN_EQUITY_RATIO = "0.02"
$env:GPTRADER_MAX_EQUITY_RATIO = "0.12"
$env:GPTRADER_MIN_LEVERAGE = "2"
$env:GPTRADER_MAX_LEVERAGE = "8"
$env:GPTRADER_DB_URL = "sqlite:///./gptrader-live-scalp-multi.sqlite3"

Write-Host "LIVE ARMED config loaded for live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2."
Write-Host "A trade trigger can submit a real Binance USD-M Futures market order plus TP/SL orders."
