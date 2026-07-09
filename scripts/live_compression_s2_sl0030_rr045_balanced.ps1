$ErrorActionPreference = "Stop"

if (-not $env:BINANCE_API_KEY -or -not $env:BINANCE_API_SECRET) {
    throw "Set BINANCE_API_KEY and BINANCE_API_SECRET before arming live trading."
}

$env:GPTRADER_MODE = "live-armed"
$env:GPTRADER_LIVE_ARMED = "true"
$env:GPTRADER_SYMBOL = "BTCUSDT"
$env:GPTRADER_TIMEFRAME = "1m"
$env:GPTRADER_CANDLE_LIMIT = "1442"
$env:GPTRADER_CLIENT_ORDER_ID_PREFIX = "gptrader-live-compression-s2"
$env:GPTRADER_GENERATOR_ID = "live-compression-s2-sl0030-rr045-balanced"
$env:GPTRADER_SIGNAL_ID_PREFIX = "live-compression-s2"
$env:GPTRADER_TRADING_STRATEGY_ID = "live-compression-s2-sl0030-rr045-balanced"
$env:GPTRADER_TAKE_PROFIT_STOP_LOSS = "fixed"
$env:GPTRADER_STOP_LOSS_RATIO = "0.030"
$env:GPTRADER_REWARD_RISK_RATIO = "0.45"
$env:GPTRADER_POSITION_SIZING = "confidence"
$env:GPTRADER_MIN_EQUITY_RATIO = "0.02"
$env:GPTRADER_MAX_EQUITY_RATIO = "0.14"
$env:GPTRADER_MIN_LEVERAGE = "1"
$env:GPTRADER_MAX_LEVERAGE = "8"
$env:GPTRADER_DB_URL = "sqlite:///./gptrader-live-compression-s2.sqlite3"

Write-Host "LIVE ARMED config loaded for live-compression-s2-sl0030-rr045-balanced."
Write-Host "A trade trigger can submit a real Binance USD-M Futures market order plus TP/SL orders."
