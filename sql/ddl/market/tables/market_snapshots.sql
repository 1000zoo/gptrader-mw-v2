CREATE TABLE IF NOT EXISTS market_snapshots (
    snapshot_id TEXT NOT NULL PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    candle_count INTEGER NOT NULL CHECK (candle_count > 0),
    latest_candle_opened_at TEXT NOT NULL,
    source TEXT,
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    CHECK (snapshot_id <> ''),
    CHECK (symbol <> ''),
    CHECK (timeframe <> ''),
    CHECK (closed_at > opened_at)
);
