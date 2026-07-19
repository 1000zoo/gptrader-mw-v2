CREATE TABLE IF NOT EXISTS strategy_results (
    result_id TEXT NOT NULL PRIMARY KEY,
    generated_signal_id TEXT,
    target_id TEXT,
    strategy_name TEXT NOT NULL,
    signal_id TEXT NOT NULL,
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    FOREIGN KEY (generated_signal_id) REFERENCES generated_signals (generated_signal_id),
    FOREIGN KEY (signal_id) REFERENCES signals (signal_id),
    CHECK (result_id <> ''),
    CHECK (strategy_name <> '')
);
