CREATE INDEX IF NOT EXISTS idx_position_sizes_decision_reg_ymd
    ON position_sizes (decision_id, reg_ymd, reg_dt);
