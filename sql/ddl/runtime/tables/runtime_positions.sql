CREATE TABLE IF NOT EXISTS runtime_positions (
    position_id TEXT NOT NULL PRIMARY KEY,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    CHECK (position_id <> ''),
    CHECK (symbol <> ''),
    CHECK (status <> '')
);
