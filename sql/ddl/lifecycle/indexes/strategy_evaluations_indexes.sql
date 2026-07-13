CREATE INDEX IF NOT EXISTS idx_strategy_evaluations_target_reg_ymd
    ON strategy_evaluations (target_id, reg_ymd, reg_dt);
