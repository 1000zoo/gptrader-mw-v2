CREATE INDEX IF NOT EXISTS idx_signals_direction_reg_ymd
    ON signals (direction, reg_ymd, reg_dt);
