CREATE INDEX IF NOT EXISTS idx_strategy_lifecycle_runs_target_type_reg_ymd
    ON strategy_lifecycle_runs (target_id, run_type, reg_ymd, reg_dt);

CREATE INDEX IF NOT EXISTS idx_strategy_lifecycle_runs_evaluations
    ON strategy_lifecycle_runs (source_evaluation_id, promoted_evaluation_id);
