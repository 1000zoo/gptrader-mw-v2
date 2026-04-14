BEGIN;

CREATE TABLE IF NOT EXISTS regime_state (
    symbol_id        VARCHAR(16) PRIMARY KEY,
    timeframe        VARCHAR(20) NOT NULL DEFAULT '1h',
    regime           VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN',
    pending_regime   VARCHAR(20),
    pending_count    INTEGER NOT NULL DEFAULT 0,
    trend_strength   NUMERIC(10, 6) NOT NULL DEFAULT 0,
    range_strength   NUMERIC(10, 6) NOT NULL DEFAULT 0,
    transition_risk  NUMERIC(10, 6) NOT NULL DEFAULT 0,
    adx              NUMERIC(18, 8),
    atr              NUMERIC(18, 8),
    bb_bandwidth     NUMERIC(18, 8),
    ema_gap          NUMERIC(18, 8),
    computed_at      TIMESTAMPTZ,
    confirmed_at     TIMESTAMPTZ,
    attr1            TEXT,
    attr2            TEXT,
    attr3            TEXT,
    attr4            TEXT,
    attr5            TEXT,
    attr6            TEXT,
    attr7            TEXT,
    attr8            TEXT,
    attr9            TEXT,
    attr10           TEXT,
    reg_dt           TIMESTAMPTZ DEFAULT NOW(),
    upd_dt           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_regime_state_regime
    ON regime_state (regime);

COMMIT;
