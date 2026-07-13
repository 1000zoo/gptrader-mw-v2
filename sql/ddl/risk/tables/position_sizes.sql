CREATE TABLE IF NOT EXISTS position_sizes (
    position_size_id TEXT NOT NULL PRIMARY KEY,
    decision_id TEXT,
    exposure_limit_id TEXT NOT NULL,
    config_id TEXT,
    entry_price NUMERIC NOT NULL CHECK (entry_price > 0),
    notional NUMERIC NOT NULL CHECK (notional >= 0),
    quantity NUMERIC NOT NULL CHECK (quantity >= 0),
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    FOREIGN KEY (decision_id) REFERENCES trade_decisions (decision_id),
    FOREIGN KEY (exposure_limit_id) REFERENCES exposure_limits (exposure_limit_id),
    FOREIGN KEY (config_id) REFERENCES position_sizer_configs (config_id),
    CHECK (position_size_id <> '')
);
