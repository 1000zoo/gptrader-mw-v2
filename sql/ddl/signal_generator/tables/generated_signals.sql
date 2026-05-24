CREATE TABLE IF NOT EXISTS generated_signals (
    generated_signal_id TEXT NOT NULL PRIMARY KEY,
    generator_id TEXT,
    signal_id TEXT NOT NULL,
    strategy_result_count INTEGER NOT NULL CHECK (strategy_result_count >= 0),
    context_snapshot_id TEXT,
    indicator_set_id TEXT,
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    FOREIGN KEY (generator_id) REFERENCES signal_generator_definitions (generator_id),
    FOREIGN KEY (signal_id) REFERENCES signals (signal_id),
    FOREIGN KEY (context_snapshot_id) REFERENCES market_snapshots (snapshot_id),
    FOREIGN KEY (indicator_set_id) REFERENCES indicator_sets (indicator_set_id),
    CHECK (generated_signal_id <> '')
);
