-- =========================================
-- EXECUTION ANOMALY
-- =========================================
CREATE TABLE IF NOT EXISTS execution_anomaly (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    run_id          VARCHAR(64),
    symbol_id       VARCHAR(16),
    anomaly_type    VARCHAR(50),
    severity        VARCHAR(20),
    signal_log_id   BIGINT,
    trade_fill_id   BIGINT,
    order_id        VARCHAR(50),
    payload         JSONB,
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

CREATE INDEX IF NOT EXISTS idx_exec_anomaly_run_id
    ON execution_anomaly (run_id);

CREATE INDEX IF NOT EXISTS idx_exec_anomaly_signal_log_id
    ON execution_anomaly (signal_log_id);

CREATE INDEX IF NOT EXISTS idx_exec_anomaly_trade_fill_id
    ON execution_anomaly (trade_fill_id);

commit;
