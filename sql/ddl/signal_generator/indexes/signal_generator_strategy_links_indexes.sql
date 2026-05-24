CREATE INDEX IF NOT EXISTS idx_signal_generator_strategy_links_strategy
    ON signal_generator_strategy_links (strategy_id, reg_ymd, reg_dt);
