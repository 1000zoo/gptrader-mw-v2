CREATE TABLE IF NOT EXISTS risk_checks (
    risk_check_id TEXT NOT NULL PRIMARY KEY,
    decision_id TEXT,
    exposure_limit_id TEXT NOT NULL,
    requested_notional NUMERIC NOT NULL CHECK (requested_notional >= 0),
    allowed INTEGER NOT NULL CHECK (allowed IN (0, 1)),
    reason TEXT NOT NULL CHECK (reason IN ('allowed', 'not_entry_decision', 'total_exposure_exceeded', 'symbol_exposure_exceeded')),
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    FOREIGN KEY (decision_id) REFERENCES trade_decisions (decision_id),
    FOREIGN KEY (exposure_limit_id) REFERENCES exposure_limits (exposure_limit_id),
    CHECK (risk_check_id <> '')
);
