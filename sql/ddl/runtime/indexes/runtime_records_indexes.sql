CREATE INDEX IF NOT EXISTS idx_runtime_records_type_reg_ymd
    ON runtime_records (record_type, reg_ymd, reg_dt);
