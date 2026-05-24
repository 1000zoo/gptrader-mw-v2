CREATE TABLE IF NOT EXISTS signal_reasons (
    reason_id TEXT NOT NULL PRIMARY KEY,
    signal_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    UNIQUE (signal_id, sequence_no),
    FOREIGN KEY (signal_id) REFERENCES signals (signal_id),
    CHECK (reason_id <> ''),
    CHECK (code <> ''),
    CHECK (message <> '')
);
