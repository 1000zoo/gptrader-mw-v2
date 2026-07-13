-- =========================================
-- CONFIDENCE CALIBRATION
-- =========================================
CREATE TABLE IF NOT EXISTS confidence_calibration (
    id                  BIGSERIAL PRIMARY KEY,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    c_interval          VARCHAR(20),
    symbol_id           VARCHAR(16),
    window_n_trades     INTEGER,
    bucket_from         NUMERIC(4, 2),
    bucket_to           NUMERIC(4, 2),
    trades              INTEGER,
    winrate             NUMERIC(10, 4),
    ev                  NUMERIC(18, 8),
    avg_r               NUMERIC(18, 8),
    pf                  NUMERIC(18, 8),
    recommended_threshold NUMERIC(10, 4),
    attr1                       TEXT,
    attr2                       TEXT,
    attr3                       TEXT,
    attr4                       TEXT,
    attr5                       TEXT,
    attr6                       TEXT,
    attr7                       TEXT,
    attr8                       TEXT,
    attr9                       TEXT,
    attr10                      TEXT,
    reg_dt                      TIMESTAMPTZ DEFAULT NOW(),
    upd_dt                      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_conf_calibration_interval_symbol
    ON confidence_calibration (c_interval, symbol_id);

commit;