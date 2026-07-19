CREATE INDEX IF NOT EXISTS idx_position_sizer_configs_reg_ymd
    ON position_sizer_configs (reg_ymd, version);
