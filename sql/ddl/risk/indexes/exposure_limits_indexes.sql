CREATE INDEX IF NOT EXISTS idx_exposure_limits_symbol_reg_ymd
    ON exposure_limits (symbol, reg_ymd, reg_dt);
