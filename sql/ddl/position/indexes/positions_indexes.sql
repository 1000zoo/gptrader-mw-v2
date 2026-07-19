CREATE INDEX IF NOT EXISTS idx_positions_symbol_status_reg_ymd
    ON positions (symbol, status, reg_ymd, upd_dt);
