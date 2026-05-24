CREATE TABLE IF NOT EXISTS signal_generator_regime_routes (
    route_id TEXT NOT NULL PRIMARY KEY,
    generator_id TEXT NOT NULL,
    regime TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    metadata_key TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    UNIQUE (generator_id, regime),
    FOREIGN KEY (generator_id) REFERENCES signal_generator_definitions (generator_id),
    FOREIGN KEY (strategy_id) REFERENCES strategy_definitions (strategy_id),
    CHECK (route_id <> ''),
    CHECK (regime <> ''),
    CHECK (strategy_id <> '')
);
