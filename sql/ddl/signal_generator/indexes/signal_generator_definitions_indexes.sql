CREATE INDEX IF NOT EXISTS idx_signal_generator_definitions_reg_ymd
    ON signal_generator_definitions (reg_ymd, generator_id);
