CREATE TABLE IF NOT EXISTS position_sizer_configs (
    config_id TEXT NOT NULL PRIMARY KEY,
    version TEXT NOT NULL,
    base_risk_ratio NUMERIC NOT NULL CHECK (base_risk_ratio > 0),
    leverage NUMERIC NOT NULL CHECK (leverage > 0),
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    UNIQUE (version),
    CHECK (config_id <> ''),
    CHECK (version <> '')
);
