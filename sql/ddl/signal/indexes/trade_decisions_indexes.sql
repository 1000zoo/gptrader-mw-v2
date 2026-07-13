CREATE INDEX IF NOT EXISTS idx_trade_decisions_action_reg_ymd
    ON trade_decisions (action, reg_ymd, reg_dt);
