CREATE TABLE IF NOT EXISTS asset_balances (
    balance_id TEXT NOT NULL PRIMARY KEY,
    account_snapshot_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    free NUMERIC NOT NULL CHECK (free >= 0),
    locked NUMERIC NOT NULL CHECK (locked >= 0),
    total NUMERIC NOT NULL CHECK (total >= 0),
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    UNIQUE (account_snapshot_id, asset),
    FOREIGN KEY (account_snapshot_id) REFERENCES account_snapshots (account_snapshot_id),
    CHECK (balance_id <> ''),
    CHECK (asset <> '')
);
