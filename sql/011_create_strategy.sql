-- =========================================
-- STRATEGY
-- =========================================
CREATE TABLE IF NOT EXISTS strategy (
    id              BIGSERIAL PRIMARY KEY,
    strategy_name   VARCHAR(100) NOT NULL,
    module_path     VARCHAR(255) NOT NULL,
    module_name     VARCHAR(100) NOT NULL,
    use_yn          VARCHAR(1) NOT NULL DEFAULT 'Y',
    description     TEXT,
    params_id       VARCHAR(20),
    params          JSONB,
    version         VARCHAR(32),
    priority        INTEGER DEFAULT 100,
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

CREATE UNIQUE INDEX IF NOT EXISTS ux_strategy_name
    ON strategy (strategy_name);

CREATE INDEX IF NOT EXISTS idx_strategy_use_yn
    ON strategy (use_yn);

 

create table if not exists strategy_timeframe (
    strategy_name              VARCHAR(100) not NULL,
    timeframe     				VARCHAR(10) NOT null,
    lookback					integer default 1,
    primary key (strategy_name, timeframe)
);


insert into strategy (strategy_name, module_path, module_name, params_id, use_yn) values
('VolatilityBreakoutRegimeStrategy', 'src.strategy.strategies.volatility_breakout_regime_strategy', 'VolatilityBreakoutRegimeStrategy', 'default_2', 'Y');

insert into strategy_timeframe (strategy_name, timeframe) values ('VolatilityBreakoutRegimeStrategy', '5m');
insert into strategy_timeframe (strategy_name, timeframe) values ('VolatilityBreakoutRegimeStrategy', '1m'); 

commit;



