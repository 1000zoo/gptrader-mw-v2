-- =========================================
-- BACKTEST RESULT
-- =========================================
CREATE TABLE IF NOT EXISTS backtest_result (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    config      JSONB,
    period_start TIMESTAMPTZ,
    period_end   TIMESTAMPTZ,
    pnl_usd     NUMERIC(18, 8),
    sharpe      NUMERIC(18, 8),
    pf          NUMERIC(18, 8),
    mdd         NUMERIC(18, 8),
    trades      INTEGER,
    winrate     NUMERIC(10, 4),
    turnover    NUMERIC(18, 8),
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

commit;
