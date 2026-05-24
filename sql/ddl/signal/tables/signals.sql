CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT NOT NULL PRIMARY KEY,
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short', 'wait')),
    confidence NUMERIC NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    CHECK (signal_id <> '')
);
