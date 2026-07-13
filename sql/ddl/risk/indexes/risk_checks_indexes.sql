CREATE INDEX IF NOT EXISTS idx_risk_checks_allowed_reason_reg_ymd
    ON risk_checks (allowed, reason, reg_ymd, reg_dt);
