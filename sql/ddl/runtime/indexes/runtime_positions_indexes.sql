CREATE INDEX IF NOT EXISTS idx_runtime_positions_symbol_status_reg_ymd
    ON runtime_positions (symbol, status, reg_ymd, reg_dt);
