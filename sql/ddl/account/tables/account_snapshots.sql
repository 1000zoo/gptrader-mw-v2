CREATE TABLE IF NOT EXISTS account_snapshots (
    account_snapshot_id TEXT NOT NULL PRIMARY KEY,
    exchange TEXT,
    account_id TEXT,
    total_equity NUMERIC NOT NULL CHECK (total_equity >= 0),
    balance_count INTEGER NOT NULL CHECK (balance_count >= 0),
    captured_dt TEXT NOT NULL,
    payload TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    CHECK (account_snapshot_id <> '')
);
