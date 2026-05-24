CREATE TABLE IF NOT EXISTS exposure_limits (
    exposure_limit_id TEXT NOT NULL PRIMARY KEY,
    symbol TEXT,
    equity NUMERIC NOT NULL CHECK (equity > 0),
    current_total_exposure NUMERIC NOT NULL CHECK (current_total_exposure >= 0),
    current_symbol_exposure NUMERIC NOT NULL CHECK (current_symbol_exposure >= 0),
    max_total_exposure_ratio NUMERIC NOT NULL CHECK (max_total_exposure_ratio > 0),
    max_symbol_exposure_ratio NUMERIC NOT NULL CHECK (max_symbol_exposure_ratio > 0),
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    CHECK (exposure_limit_id <> '')
);
