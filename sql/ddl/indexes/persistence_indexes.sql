CREATE INDEX IF NOT EXISTS idx_strategy_definitions_reg_ymd
    ON strategy_definitions (reg_ymd, strategy_id);

CREATE INDEX IF NOT EXISTS idx_signal_generator_definitions_reg_ymd
    ON signal_generator_definitions (reg_ymd, generator_id);

CREATE INDEX IF NOT EXISTS idx_strategy_evaluations_target_reg_ymd
    ON strategy_evaluations (target_id, reg_ymd, reg_dt);

CREATE INDEX IF NOT EXISTS idx_signal_logs_generator_reg_ymd
    ON signal_logs (generator_id, reg_ymd, reg_dt);
