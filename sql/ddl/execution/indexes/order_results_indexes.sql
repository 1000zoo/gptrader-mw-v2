CREATE INDEX IF NOT EXISTS idx_order_results_client_order_reg_ymd
    ON order_results (client_order_id, reg_ymd, reg_dt);

CREATE INDEX IF NOT EXISTS idx_order_results_exchange_order_reg_ymd
    ON order_results (exchange_order_id, reg_ymd, reg_dt);
