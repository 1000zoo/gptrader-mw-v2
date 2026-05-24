CREATE INDEX IF NOT EXISTS idx_research_runs_target_mode_reg_ymd
    ON research_runs (target_id, mode, reg_ymd, reg_dt);

CREATE INDEX IF NOT EXISTS idx_research_runs_symbol_timeframe_reg_ymd
    ON research_runs (symbol, timeframe, reg_ymd, reg_dt);
