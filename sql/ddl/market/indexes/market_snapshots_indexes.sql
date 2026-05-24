CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_timeframe_reg_ymd
    ON market_snapshots (symbol, timeframe, reg_ymd, closed_at);
