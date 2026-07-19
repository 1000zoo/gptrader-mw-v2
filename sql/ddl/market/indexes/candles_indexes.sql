CREATE INDEX IF NOT EXISTS idx_candles_symbol_timeframe_reg_ymd
    ON candles (symbol, timeframe, reg_ymd, closed_at);
