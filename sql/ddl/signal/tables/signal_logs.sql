CREATE TABLE IF NOT EXISTS signal_logs (
    signal_id TEXT NOT NULL PRIMARY KEY,
    generator_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    CHECK (signal_id <> ''),
    CHECK (generator_id <> '')
);
