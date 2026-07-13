CREATE INDEX IF NOT EXISTS idx_account_snapshots_exchange_reg_ymd
    ON account_snapshots (exchange, account_id, reg_ymd, captured_dt);
