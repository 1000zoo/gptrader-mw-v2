CREATE INDEX IF NOT EXISTS idx_indicator_sets_symbol_timeframe_reg_ymd
    ON indicator_sets (symbol, timeframe, reg_ymd, measured_at);
