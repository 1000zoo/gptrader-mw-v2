CREATE TABLE IF NOT EXISTS promotion_policies (
    policy_id TEXT NOT NULL PRIMARY KEY,
    version TEXT NOT NULL,
    minimum_metrics TEXT NOT NULL,
    allowed_statuses TEXT NOT NULL,
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    UNIQUE (version),
    CHECK (policy_id <> ''),
    CHECK (version <> ''),
    CHECK (minimum_metrics <> ''),
    CHECK (allowed_statuses <> '')
);
