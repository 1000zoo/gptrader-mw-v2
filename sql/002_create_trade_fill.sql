-- =========================================
-- TRADE FILL
-- =========================================
CREATE TABLE IF NOT EXISTS trade_fill (
    id              BIGSERIAL PRIMARY KEY,
    signal_log_id   BIGINT,
    symbol_id       VARCHAR(16),
    side            VARCHAR(10),
    entry_order_id  VARCHAR(50),
    entry_price     NUMERIC(18, 8),
    entry_qty       NUMERIC(30, 10),
    entry_fee       NUMERIC(18, 8),
    entry_ts        TIMESTAMPTZ,
    exit_order_id   VARCHAR(50),
    exit_price      NUMERIC(18, 8),
    exit_fee        NUMERIC(18, 8),
    exit_ts         TIMESTAMPTZ,
    pnl_usd         NUMERIC(18, 8),
    pnl_pct         NUMERIC(18, 8),
    r_multiple      NUMERIC(18, 8),
    slippage_est    NUMERIC(18, 8),
    status          VARCHAR(20),
    risk_budget_usd NUMERIC(18, 8),
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

CREATE INDEX IF NOT EXISTS idx_trade_fill_signal_log_id
    ON trade_fill (signal_log_id);

CREATE INDEX IF NOT EXISTS idx_trade_fill_symbol_status
    ON trade_fill (symbol_id, status);

commit;
