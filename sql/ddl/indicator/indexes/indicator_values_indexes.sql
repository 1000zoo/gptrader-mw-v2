CREATE INDEX IF NOT EXISTS idx_indicator_values_symbol_timeframe_key_reg_ymd
    ON indicator_values (symbol, timeframe, indicator_key, reg_ymd, measured_at);
