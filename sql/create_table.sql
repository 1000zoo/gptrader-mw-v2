-- =========================================
-- SYMBOL
-- =========================================
CREATE TABLE symbols (
    symbol_id           varchar(16) PRIMARY KEY,          -- ex) 'BTCUSDT'
    symbol_name         varchar(16),
    price_precision     INTEGER,
    quantity_precision  INTEGER,
    tick_size           NUMERIC(18, 8),
    step_size           NUMERIC(18, 8),
    min_price           NUMERIC(18, 8),
    max_price           NUMERIC(18, 8),
    min_qty             NUMERIC(30, 10),
    max_qty             NUMERIC(30, 10),
    attr1               TEXT,
    attr2               TEXT,
    attr3               TEXT,
    attr4               TEXT,
    attr5               TEXT,
    attr6               TEXT,
    attr7               TEXT,
    attr8               TEXT,
    attr9               TEXT,
    attr10              TEXT,
    reg_dt              TIMESTAMPTZ DEFAULT NOW(),
    upd_dt              TIMESTAMPTZ
);

commit;


-- =========================================
-- JOB RUN (batch_id 마스터)
-- =========================================
CREATE table job_run (
    batch_id        VARCHAR(32) PRIMARY KEY,    -- ex) 'BTCUSDT202512100001'
    job_type        VARCHAR(50),
    reg_ymd         VARCHAR(8),                -- '20251210'
    target_interval VARCHAR(40),
    symbol_id       VARCHAR(40),
    status          VARCHAR(40),               -- 'SUCCESS', 'FAIL', 'RUNNING',
    main_order_id	VARCHAR(40),
    tp_order_id		VARCHAR(40),               
    sl_order_id		VARCHAR(40),               
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error_message   TEXT,
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
CREATE table job_run_hist (
	log_no			BIGSERIAL PRIMARY KEY,
    batch_id        VARCHAR(32),    -- ex) 'BTCUSDT202512100001'
    job_type        VARCHAR(50),
    reg_ymd         VARCHAR(8),                -- '20251210'
    target_interval VARCHAR(40),
    symbol_id       VARCHAR(40),
    status          VARCHAR(40),               -- 'SUCCESS', 'FAIL', 'RUNNING',
    main_order_id	VARCHAR(40),
    tp_order_id		VARCHAR(40),               
    sl_order_id		VARCHAR(40),               
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    error_message   TEXT,
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
commit;
-- =========================================
-- OHLCV
-- =========================================
CREATE TABLE ohlcv (
    id              BIGSERIAL PRIMARY KEY,
    batch_id        VARCHAR(32),
    reg_ymd         VARCHAR(8),
    symbol_id       varchar(16),
    c_interval      VARCHAR(20),
   	c_limit         INTEGER,
    seq_no          INTEGER,
    ts              TIMESTAMPTZ,
	c_open	        NUMERIC(18, 8),
    c_high          NUMERIC(18, 8),
    c_low           NUMERIC(18, 8),
    c_close         NUMERIC(18, 8),
    volume          NUMERIC(30, 10),
    quote_volume    NUMERIC(30, 10),
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


-- =========================================
-- INDICATOR PARAMETER
-- =========================================
-- indparams 기준:
-- tail, col, ma_fast_w, ma_slow_w, ema_fast_w, ema_slow_w, std_w,
-- rsi_w, macd_signal, bollinger_k, atr_w, kd_k_w, kd_d_w,
-- roc_w, momentum_w, mfi_w, donchain_w, keltner_m, linear_regression_slope_w
CREATE TABLE indicator_parameter (
    name						varchar(32) primary key,
    tail                        INTEGER,        -- 최근 n개 tail
    col                         varchar(32),           -- 'close' 등
    ma_fast_w                   INTEGER,
    ma_slow_w                   INTEGER,
    ema_fast_w                  INTEGER,
    ema_slow_w                  INTEGER,
    std_w                       INTEGER,
    rsi_w                       INTEGER,
    macd_signal                 INTEGER,
    bollinger_k                 NUMERIC(10, 4),
    atr_w                       INTEGER,
    kd_k_w                      INTEGER,
    kd_d_w                      INTEGER,
    roc_w                       INTEGER,
    momentum_w                  INTEGER,
    mfi_w                       INTEGER,
    donchain_w                  INTEGER,
    keltner_m                   NUMERIC(10, 4),
    linear_regression_slope_w   INTEGER,
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

-- =========================================
-- INDICATOR (지표 값)
-- =========================================
-- indicator dict 기준:
-- timestamp, ma_fast, ma_slow, ema_fast, ema_slow, rsi,
-- macd_line, macd_signal_line, macd_hist,
-- bollinger_mid, bollinger_upper, bollinger_lower, bollinger_width,
-- true_range, atr,
-- dmi_plus_di, dmi_minus_di, dmi_adx,
-- stochastic_per_k, stochastic_per_d,
-- cci, roc, momentum, obv, mfi, vwap,
-- donchain_upper, donchain_lower,
-- keltner_mid, keltner_upper, keltner_lower,
-- linear_regression_slope, linear_regression_direction
CREATE TABLE indicators (
    id                          BIGSERIAL PRIMARY KEY,
    reg_ymd                     VARCHAR(8),
    symbol_id                   varchar(16),
    batch_id                    VARCHAR(32),
    indicator_parameter_id      varchar(32),
    c_interval                  VARCHAR(20),
    c_limit                     INTEGER,
    seq_no                      INTEGER,
    ts                          TIMESTAMPTZ,
    ma_fast                     NUMERIC(18, 8),
    ma_slow                     NUMERIC(18, 8),
    ema_fast                    NUMERIC(18, 8),
    ema_slow                    NUMERIC(18, 8),
    rsi                         NUMERIC(18, 8),
    macd_line                   NUMERIC(18, 8),
    macd_signal_line            NUMERIC(18, 8),
    macd_hist                   NUMERIC(18, 8),
    bollinger_mid               NUMERIC(18, 8),
    bollinger_upper             NUMERIC(18, 8),
    bollinger_lower             NUMERIC(18, 8),
    bollinger_width             NUMERIC(18, 8),
    true_range                  NUMERIC(18, 8),
    atr                         NUMERIC(18, 8),
    dmi_plus_di                 NUMERIC(18, 8),
    dmi_minus_di                NUMERIC(18, 8),
    dmi_adx                     NUMERIC(18, 8),
    stochastic_per_k            NUMERIC(18, 8),
    stochastic_per_d            NUMERIC(18, 8),
    cci                         NUMERIC(18, 8),
    roc                         NUMERIC(18, 8),
    momentum                    NUMERIC(18, 8),
    obv                         NUMERIC(30, 10),
    mfi                         NUMERIC(18, 8),
    vwap                        NUMERIC(18, 8),
    donchain_upper              NUMERIC(18, 8),
    donchain_lower              NUMERIC(18, 8),
    keltner_mid                 NUMERIC(18, 8),
    keltner_upper               NUMERIC(18, 8),
    keltner_lower               NUMERIC(18, 8),
    low_linear_regression_slope     NUMERIC(18, 8),
    low_linear_regression_direction NUMERIC(18, 8),
    high_linear_regression_slope     NUMERIC(18, 8),
    high_linear_regression_direction NUMERIC(18, 8),
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


-- =========================================
-- ANALYZE RESULT (GPT RAW 응답)
-- =========================================
CREATE TABLE analyze_result (
    id                  BIGSERIAL PRIMARY KEY,
    batch_id            VARCHAR(32),
    prompt_id           VARCHAR(32),
    symbol_id           varchar(16),
    raw_content         TEXT,
    model               VARCHAR(100),
    refusal				VARCHAR(100),
    finish_reason		VARCHAR(100),
    total_tokens        INTEGER,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    reasoning_tokens	INTEGER,
    rejected_prediction_tokens 	INTEGER,
    latency_ms          INTEGER,
    reg_ymd             VARCHAR(8),
    attr1               TEXT,
    attr2               TEXT,
    attr3               TEXT,
    attr4               TEXT,
    attr5               TEXT,
    attr6               TEXT,
    attr7               TEXT,
    attr8               TEXT,
    attr9               TEXT,
    attr10              TEXT,
    reg_dt              TIMESTAMPTZ DEFAULT NOW(),
    upd_dt              TIMESTAMPTZ
);

-- =========================================
-- ANALYZE ACTION (최종 GPT 추천 액션)
-- =========================================
CREATE TABLE analyze_action (
    id          BIGSERIAL PRIMARY KEY,
    reg_ymd     VARCHAR(8),
    batch_id    VARCHAR(32),
    symbol_id   varchar(16),
    side        VARCHAR(10),         -- 'LONG', 'SHORT', 'NONE'
    entry_price NUMERIC(18, 8),
    tp		    NUMERIC(18, 8),
    sl		    NUMERIC(18, 8),
    confidence  NUMERIC(5, 2),
    reason      TEXT,
    attr1       TEXT,
    attr2       TEXT,
    attr3       TEXT,
    attr4       TEXT,
    attr5       TEXT,
    attr6       TEXT,
    attr7       TEXT,
    attr8       TEXT,
    attr9       TEXT,
    attr10      TEXT,
    reg_dt      TIMESTAMPTZ DEFAULT NOW(),
    upd_dt      TIMESTAMPTZ
);



-- =========================================
-- POSITION EVENT (포지션 오픈/종료/청산 로그)
-- =========================================
CREATE TABLE position_event (
    id              BIGSERIAL PRIMARY KEY,
    reg_ymd         VARCHAR(8),
    batch_id        VARCHAR(32),
    symbol_id       varchar(16),
    event_type      VARCHAR(20),     -- 'OPEN', 'CLOSE', 'PARTIAL_CLOSE', 'LIQUIDATION', ...
    side            VARCHAR(10),     -- 'LONG', 'SHORT'
    qty             NUMERIC(30, 10),
    price           NUMERIC(18, 8),
    order_id        VARCHAR(50),
    position_side   VARCHAR(20),     -- 'BOTH', 'LONG', 'SHORT'
    order_type      VARCHAR(30),     -- 'LIMIT', 'MARKET'
    execution_type  VARCHAR(30),     -- 'TAKE_PROFIT', ...
    order_status	VARCHAR(30), 	 -- 'FILLED',...
    client_order_id VARCHAR(80),
    pnl             NUMERIC(18, 8),
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
commit;
