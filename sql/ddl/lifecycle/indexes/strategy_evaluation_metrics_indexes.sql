CREATE INDEX IF NOT EXISTS idx_strategy_evaluation_metrics_name_reg_ymd
    ON strategy_evaluation_metrics (metric_name, reg_ymd, metric_value);
