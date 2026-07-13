CREATE TABLE IF NOT EXISTS risk_policies (
    policy_id TEXT NOT NULL PRIMARY KEY,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    implementation TEXT,
    rules TEXT,
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    UNIQUE (version),
    CHECK (policy_id <> ''),
    CHECK (version <> ''),
    CHECK (name <> '')
);
