CREATE TABLE IF NOT EXISTS strategy_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    target_id TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N'))
);
