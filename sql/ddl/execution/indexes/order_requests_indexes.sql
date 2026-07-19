CREATE INDEX IF NOT EXISTS idx_order_requests_symbol_reg_ymd
    ON order_requests (symbol, reg_ymd, reg_dt);

CREATE INDEX IF NOT EXISTS idx_order_requests_decision_reg_ymd
    ON order_requests (decision_id, reg_ymd, reg_dt);
