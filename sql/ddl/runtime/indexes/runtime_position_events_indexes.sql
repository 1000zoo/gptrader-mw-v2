CREATE INDEX IF NOT EXISTS idx_runtime_position_events_position_reg_ymd
    ON runtime_position_events (position_id, reg_ymd, reg_dt);
