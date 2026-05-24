CREATE TABLE IF NOT EXISTS strategy_definitions (
    strategy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    implementation TEXT NOT NULL,
    version TEXT NOT NULL,
    payload TEXT NOT NULL,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N'))
);
