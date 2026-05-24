CREATE INDEX IF NOT EXISTS idx_promotion_policies_reg_ymd
    ON promotion_policies (reg_ymd, version);
