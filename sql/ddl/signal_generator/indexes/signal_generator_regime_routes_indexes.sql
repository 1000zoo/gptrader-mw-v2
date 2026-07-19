CREATE INDEX IF NOT EXISTS idx_signal_generator_regime_routes_generator
    ON signal_generator_regime_routes (generator_id, reg_ymd, regime);
