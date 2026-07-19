CREATE TABLE IF NOT EXISTS market_snapshot_candles (
    snapshot_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    PRIMARY KEY (snapshot_id, sequence_no),
    UNIQUE (snapshot_id, symbol, timeframe, opened_at),
    FOREIGN KEY (snapshot_id) REFERENCES market_snapshots (snapshot_id),
    FOREIGN KEY (symbol, timeframe, opened_at) REFERENCES candles (symbol, timeframe, opened_at),
    CHECK (symbol <> ''),
    CHECK (timeframe <> '')
);
