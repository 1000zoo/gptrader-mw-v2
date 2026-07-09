$ErrorActionPreference = "Stop"

if (-not $env:BINANCE_API_KEY -or -not $env:BINANCE_API_SECRET) {
    throw "Set BINANCE_API_KEY and BINANCE_API_SECRET before arming live trading."
}

$env:GPTRADER_MODE = "live-armed"
$env:GPTRADER_LIVE_ARMED = "true"
$env:GPTRADER_SYMBOL = "BTCUSDT"
$env:GPTRADER_TIMEFRAME = "1m"
$env:GPTRADER_CANDLE_LIMIT = "302"
$env:GPTRADER_CLIENT_ORDER_ID_PREFIX = "gptrader-live-tv-range"
$env:GPTRADER_GENERATOR_ID = "tv-range-seed-s1-t1-p2-fixed"
$env:GPTRADER_SIGNAL_ID_PREFIX = "live-tv-range"
$env:GPTRADER_TRADING_STRATEGY_ID = "tv-range-seed-s1-t1-p2-fixed"
$env:GPTRADER_TAKE_PROFIT_STOP_LOSS = "fixed"
$env:GPTRADER_STOP_LOSS_RATIO = "0.09"
$env:GPTRADER_REWARD_RISK_RATIO = "0.15"
$env:GPTRADER_POSITION_SIZING = "fixed"
$env:GPTRADER_FIXED_EQUITY_RATIO = "0.10"
$env:GPTRADER_FIXED_LEVERAGE = "15"
$env:GPTRADER_DB_URL = "sqlite:///./gptrader-live-tv-range.sqlite3"

Write-Host "LIVE ARMED config loaded for tv-range-seed-s1-t1-p2-fixed."
Write-Host "A trade trigger can submit a real Binance USD-M Futures market order plus TP/SL orders."
