CREATE INDEX IF NOT EXISTS idx_strategy_definitions_reg_ymd
    ON strategy_definitions (reg_ymd, strategy_id);
