CREATE INDEX IF NOT EXISTS idx_signal_logs_generator_reg_ymd
    ON signal_logs (generator_id, reg_ymd, reg_dt);
