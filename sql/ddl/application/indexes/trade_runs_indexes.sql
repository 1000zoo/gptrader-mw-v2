CREATE INDEX IF NOT EXISTS idx_trade_runs_symbol_timeframe_reg_ymd
    ON trade_runs (symbol, timeframe, reg_ymd, reg_dt);

CREATE INDEX IF NOT EXISTS idx_trade_runs_generator_status_reg_ymd
    ON trade_runs (generator_id, status, reg_ymd, reg_dt);
