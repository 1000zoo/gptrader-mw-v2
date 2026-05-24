CREATE TABLE IF NOT EXISTS signal_generator_strategy_links (
    generator_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    PRIMARY KEY (generator_id, strategy_id),
    UNIQUE (generator_id, sequence_no),
    FOREIGN KEY (generator_id) REFERENCES signal_generator_definitions (generator_id),
    FOREIGN KEY (strategy_id) REFERENCES strategy_definitions (strategy_id)
);
