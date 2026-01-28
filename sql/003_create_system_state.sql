-- =========================================
-- SYSTEM STATE
-- =========================================
CREATE TABLE IF NOT EXISTS system_state (
    id              BIGSERIAL PRIMARY KEY,
    trading_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    reason          TEXT,
    since_ts        TIMESTAMPTZ,
    updated_by      TEXT,
    reg_dt          TIMESTAMPTZ DEFAULT NOW(),
    upd_dt          TIMESTAMPTZ
);

commit;
