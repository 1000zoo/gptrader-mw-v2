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
    turnover    NUMERIC(18, 8)
);

commit;
