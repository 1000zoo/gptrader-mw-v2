CREATE INDEX IF NOT EXISTS idx_market_snapshot_candles_candle
    ON market_snapshot_candles (symbol, timeframe, opened_at);
