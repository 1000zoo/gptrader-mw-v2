-- =========================================
-- SIGNAL LOG
-- =========================================
CREATE TABLE IF NOT EXISTS signal_log (
    id                      BIGSERIAL PRIMARY KEY,
    run_id                  VARCHAR(64),
    job_run_id              VARCHAR(32),
    symbol_id               VARCHAR(16),
    c_interval              VARCHAR(20),
    base_ts                 TIMESTAMPTZ,
    window_start_ts         TIMESTAMPTZ,
    window_end_ts           TIMESTAMPTZ,
    n_candles               INTEGER,
    indicator_params_version VARCHAR(64),
    prompt_version          VARCHAR(64),
    model_name              VARCHAR(100),
    model_temperature       NUMERIC(6, 3),
    raw_position            VARCHAR(10),
    raw_confidence          NUMERIC(10, 4),
    tp_price                NUMERIC(18, 8),
    sl_price                NUMERIC(18, 8),
    rationale               TEXT,
    gate_allowed            BOOLEAN,
    gate_rejected_reason    TEXT,
    calibrated_confidence   NUMERIC(10, 4),
    dynamic_threshold_used  NUMERIC(10, 4),
    final_action            VARCHAR(20),
    analyze_result_id       BIGINT,
    analyze_action_id       BIGINT,
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

CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_log_decision
    ON signal_log (symbol_id, c_interval, base_ts, prompt_version, indicator_params_version);

CREATE INDEX IF NOT EXISTS idx_signal_log_symbol_interval_base_ts
    ON signal_log (symbol_id, c_interval, base_ts DESC);

CREATE INDEX IF NOT EXISTS idx_signal_log_run_id
    ON signal_log (run_id);


commit;

