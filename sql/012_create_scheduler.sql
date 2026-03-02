-- =========================================
-- SCHEDULER
-- =========================================
CREATE TABLE IF NOT EXISTS scheduler (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    state           VARCHAR(30),
    last_run_dt     TIMESTAMPTZ,
    last_run_log    TEXT,
    use_yn          BOOLEAN DEFAULT TRUE,
    attr1           TEXT,
    attr2           TEXT,
    attr3           TEXT,
    attr4           TEXT,
    attr5           TEXT,
    attr6           TEXT,
    attr7           TEXT,
    attr8           TEXT,
    attr9           TEXT,
    attr10          TEXT,
    reg_dt          TIMESTAMPTZ DEFAULT NOW(),
    upd_dt          TIMESTAMPTZ,
    UNIQUE (name)
);

CREATE INDEX IF NOT EXISTS idx_scheduler_use_yn
    ON scheduler (use_yn);

commit;
