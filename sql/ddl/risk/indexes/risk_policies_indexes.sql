CREATE INDEX IF NOT EXISTS idx_risk_policies_reg_ymd
    ON risk_policies (reg_ymd, version);
