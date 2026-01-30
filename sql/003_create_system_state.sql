-- =========================================
-- SYSTEM STATE
-- =========================================
CREATE TABLE IF NOT EXISTS system_state (
    id              BIGSERIAL PRIMARY KEY,
    trading_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    reason          TEXT,
    since_ts        TIMESTAMPTZ,
    updated_by      TEXT,
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
