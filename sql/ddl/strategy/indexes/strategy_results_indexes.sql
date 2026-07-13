CREATE INDEX IF NOT EXISTS idx_strategy_results_strategy_name_reg_ymd
    ON strategy_results (strategy_name, reg_ymd, reg_dt);

CREATE INDEX IF NOT EXISTS idx_strategy_results_generated_signal
    ON strategy_results (generated_signal_id, strategy_name);
