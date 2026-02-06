-- =========================================
-- SLACK SETTING
-- =========================================
CREATE TABLE slack_setting (
    id              BIGSERIAL PRIMARY KEY,
    process_name    VARCHAR(32) NOT NULL,
    channel_name    VARCHAR(100) NOT NULL,
    webhook_url     TEXT NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
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
    upd_dt          TIMESTAMPTZ
);

CREATE INDEX idx_slack_setting_process_active
    ON slack_setting (process_name, is_active);

commit;
