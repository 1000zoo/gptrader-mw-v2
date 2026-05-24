CREATE TABLE IF NOT EXISTS indicator_sets (
    indicator_set_id TEXT NOT NULL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    value_count INTEGER NOT NULL CHECK (value_count >= 0),
    source_snapshot_id TEXT,
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    UNIQUE (symbol, timeframe, measured_at, source_snapshot_id),
    FOREIGN KEY (source_snapshot_id) REFERENCES market_snapshots (snapshot_id),
    CHECK (indicator_set_id <> ''),
    CHECK (symbol <> ''),
    CHECK (timeframe <> '')
);
