CREATE INDEX IF NOT EXISTS idx_generated_signals_generator_reg_ymd
    ON generated_signals (generator_id, reg_ymd, reg_dt);
