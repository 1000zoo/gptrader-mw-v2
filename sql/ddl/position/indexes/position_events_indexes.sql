CREATE INDEX IF NOT EXISTS idx_position_events_position_reg_ymd
    ON position_events (position_id, reg_ymd, occurred_dt);

CREATE INDEX IF NOT EXISTS idx_position_events_symbol_type_reg_ymd
    ON position_events (symbol, event_type, reg_ymd, occurred_dt);
