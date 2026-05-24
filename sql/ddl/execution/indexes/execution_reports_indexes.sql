CREATE INDEX IF NOT EXISTS idx_execution_reports_symbol_reg_ymd
    ON execution_reports (symbol, reg_ymd, executed_dt);

CREATE INDEX IF NOT EXISTS idx_execution_reports_position_reg_ymd
    ON execution_reports (position_id, reg_ymd, executed_dt);
