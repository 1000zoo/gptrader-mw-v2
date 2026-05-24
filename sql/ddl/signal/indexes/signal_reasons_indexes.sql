CREATE INDEX IF NOT EXISTS idx_signal_reasons_code_reg_ymd
    ON signal_reasons (code, reg_ymd, reg_dt);
