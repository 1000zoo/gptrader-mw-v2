CREATE TABLE IF NOT EXISTS trade_decisions (
    decision_id TEXT NOT NULL PRIMARY KEY,
    signal_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('enter_long', 'enter_short', 'exit', 'hold')),
    generated_signal_id TEXT,
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    FOREIGN KEY (signal_id) REFERENCES signals (signal_id),
    FOREIGN KEY (generated_signal_id) REFERENCES generated_signals (generated_signal_id),
    CHECK (decision_id <> '')
);
