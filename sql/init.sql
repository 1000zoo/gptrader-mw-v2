--
-- PostgreSQL database dump
--

\restrict 6Ln0sCSjwcJffIl0xhtvmcdaPctdgGvfCi24J79UHcIELKrvXnxq8yqMoCvKQ0j

-- Dumped from database version 14.20 (Homebrew)
-- Dumped by pg_dump version 14.20 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: analyze_action; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.analyze_action (
    id bigint NOT NULL,
    reg_ymd character varying(8),
    batch_id character varying(32),
    symbol_id character varying(16),
    side character varying(10),
    entry_price numeric(18,8),
    tp numeric(18,8),
    sl numeric(18,8),
    confidence numeric(5,2),
    reason text,
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: analyze_action_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.analyze_action_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: analyze_action_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.analyze_action_id_seq OWNED BY public.analyze_action.id;


--
-- Name: analyze_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.analyze_result (
    id bigint NOT NULL,
    batch_id character varying(32),
    prompt_id character varying(32),
    symbol_id character varying(16),
    raw_content text,
    model character varying(100),
    refusal character varying(100),
    finish_reason character varying(100),
    total_tokens integer,
    prompt_tokens integer,
    completion_tokens integer,
    reasoning_tokens integer,
    rejected_prediction_tokens integer,
    latency_ms integer,
    reg_ymd character varying(8),
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: analyze_result_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.analyze_result_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: analyze_result_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.analyze_result_id_seq OWNED BY public.analyze_result.id;


--
-- Name: backtest_result; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backtest_result (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    config jsonb,
    period_start timestamp with time zone,
    period_end timestamp with time zone,
    pnl_usd numeric(18,8),
    sharpe numeric(18,8),
    pf numeric(18,8),
    mdd numeric(18,8),
    trades integer,
    winrate numeric(10,4),
    turnover numeric(18,8),
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: backtest_result_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.backtest_result_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: backtest_result_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.backtest_result_id_seq OWNED BY public.backtest_result.id;


--
-- Name: confidence_calibration; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confidence_calibration (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    c_interval character varying(20),
    symbol_id character varying(16),
    window_n_trades integer,
    bucket_from numeric(4,2),
    bucket_to numeric(4,2),
    trades integer,
    winrate numeric(10,4),
    ev numeric(18,8),
    avg_r numeric(18,8),
    pf numeric(18,8),
    recommended_threshold numeric(10,4),
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: confidence_calibration_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.confidence_calibration_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: confidence_calibration_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.confidence_calibration_id_seq OWNED BY public.confidence_calibration.id;


--
-- Name: execution_anomaly; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.execution_anomaly (
    id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    run_id character varying(64),
    symbol_id character varying(16),
    anomaly_type character varying(50),
    severity character varying(20),
    signal_log_id bigint,
    trade_fill_id bigint,
    order_id character varying(50),
    payload jsonb,
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: execution_anomaly_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.execution_anomaly_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: execution_anomaly_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.execution_anomaly_id_seq OWNED BY public.execution_anomaly.id;


--
-- Name: indicator_parameter; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.indicator_parameter (
    name character varying(32) NOT NULL,
    tail integer,
    col character varying(32),
    ma_fast_w integer,
    ma_slow_w integer,
    ema_fast_w integer,
    ema_slow_w integer,
    std_w integer,
    rsi_w integer,
    macd_signal integer,
    bollinger_k numeric(10,4),
    atr_w integer,
    kd_k_w integer,
    kd_d_w integer,
    roc_w integer,
    momentum_w integer,
    mfi_w integer,
    donchain_w integer,
    keltner_m numeric(10,4),
    linear_regression_slope_w integer,
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: indicators; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.indicators (
    id bigint NOT NULL,
    reg_ymd character varying(8),
    symbol_id character varying(16),
    batch_id character varying(32),
    indicator_parameter_id character varying(32),
    c_interval character varying(20),
    c_limit integer,
    seq_no integer,
    ts timestamp with time zone,
    ma_fast numeric(18,8),
    ma_slow numeric(18,8),
    ema_fast numeric(18,8),
    ema_slow numeric(18,8),
    ema_gap numeric(18,8),
    ema_gap_ratio numeric(18,8),
    rsi numeric(18,8),
    macd_line numeric(18,8),
    macd_signal_line numeric(18,8),
    macd_hist numeric(18,8),
    bollinger_mid numeric(18,8),
    bollinger_upper numeric(18,8),
    bollinger_lower numeric(18,8),
    bollinger_width numeric(18,8),
    true_range numeric(18,8),
    atr numeric(18,8),
    dmi_plus_di numeric(18,8),
    dmi_minus_di numeric(18,8),
    dmi_adx numeric(18,8),
    stochastic_per_k numeric(18,8),
    stochastic_per_d numeric(18,8),
    cci numeric(18,8),
    roc numeric(18,8),
    momentum numeric(18,8),
    obv numeric(30,10),
    mfi numeric(18,8),
    vwap numeric(18,8),
    donchain_upper numeric(18,8),
    donchain_lower numeric(18,8),
    keltner_mid numeric(18,8),
    keltner_upper numeric(18,8),
    keltner_lower numeric(18,8),
    low_linear_regression_slope numeric(18,8),
    low_linear_regression_direction numeric(18,8),
    high_linear_regression_slope numeric(18,8),
    high_linear_regression_direction numeric(18,8),
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: indicators_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.indicators_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: indicators_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.indicators_id_seq OWNED BY public.indicators.id;


--
-- Name: job_run; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_run (
    batch_id character varying(32) NOT NULL,
    job_type character varying(50),
    reg_ymd character varying(8),
    target_interval character varying(40),
    symbol_id character varying(40),
    status character varying(40),
    main_order_id character varying(40),
    tp_order_id character varying(40),
    sl_order_id character varying(40),
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    error_message text,
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: job_run_hist; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.job_run_hist (
    log_no bigint NOT NULL,
    batch_id character varying(32),
    job_type character varying(50),
    reg_ymd character varying(8),
    target_interval character varying(40),
    symbol_id character varying(40),
    status character varying(40),
    main_order_id character varying(40),
    tp_order_id character varying(40),
    sl_order_id character varying(40),
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    error_message text,
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: job_run_hist_log_no_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.job_run_hist_log_no_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: job_run_hist_log_no_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.job_run_hist_log_no_seq OWNED BY public.job_run_hist.log_no;


--
-- Name: ohlcv; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ohlcv (
    id bigint NOT NULL,
    batch_id character varying(32),
    reg_ymd character varying(8),
    symbol_id character varying(16),
    c_interval character varying(20),
    c_limit integer,
    seq_no integer,
    ts timestamp with time zone,
    c_open numeric(18,8),
    c_high numeric(18,8),
    c_low numeric(18,8),
    c_close numeric(18,8),
    volume numeric(30,10),
    quote_volume numeric(30,10),
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: ohlcv_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ohlcv_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ohlcv_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ohlcv_id_seq OWNED BY public.ohlcv.id;


--
-- Name: ohlcv_summary; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ohlcv_summary (
    id bigint NOT NULL,
    batch_id character varying(32),
    reg_ymd character varying(8),
    symbol_id character varying(16),
    c_interval character varying(20),
    c_limit integer,
    start_ts timestamp with time zone,
    end_ts timestamp with time zone,
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: ohlcv_summary_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ohlcv_summary_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ohlcv_summary_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ohlcv_summary_id_seq OWNED BY public.ohlcv_summary.id;


--
-- Name: position_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.position_event (
    id bigint NOT NULL,
    reg_ymd character varying(8),
    batch_id character varying(32),
    symbol_id character varying(16),
    event_type character varying(20),
    side character varying(10),
    qty numeric(30,10),
    price numeric(18,8),
    order_id character varying(50),
    position_side character varying(20),
    order_type character varying(30),
    execution_type character varying(30),
    order_status character varying(30),
    client_order_id character varying(80),
    pnl numeric(18,8),
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: position_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.position_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: position_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.position_event_id_seq OWNED BY public.position_event.id;


--
-- Name: signal_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signal_log (
    id bigint NOT NULL,
    run_id character varying(64),
    job_run_id character varying(32),
    symbol_id character varying(16),
    c_interval character varying(20),
    base_ts timestamp with time zone,
    window_start_ts timestamp with time zone,
    window_end_ts timestamp with time zone,
    n_candles integer,
    indicator_params_version character varying(64),
    prompt_version character varying(64),
    model_name character varying(100),
    model_temperature numeric(6,3),
    raw_position character varying(10),
    raw_confidence numeric(10,4),
    tp_price numeric(18,8),
    sl_price numeric(18,8),
    rationale text,
    gate_allowed boolean,
    gate_rejected_reason text,
    calibrated_confidence numeric(10,4),
    dynamic_threshold_used numeric(10,4),
    final_action character varying(20),
    replay_status character varying(20),
    analyze_result_id bigint,
    analyze_action_id bigint,
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: signal_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.signal_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: signal_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.signal_log_id_seq OWNED BY public.signal_log.id;


--
-- Name: symbols; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.symbols (
    symbol_id character varying(16) NOT NULL,
    symbol_name character varying(16),
    price_precision integer,
    quantity_precision integer,
    tick_size numeric(18,8),
    step_size numeric(18,8),
    min_price numeric(18,8),
    max_price numeric(18,8),
    min_qty numeric(30,10),
    max_qty numeric(30,10),
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: system_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_state (
    id bigint NOT NULL,
    trading_enabled boolean DEFAULT true NOT NULL,
    reason text,
    since_ts timestamp with time zone,
    updated_by text,
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: scheduler; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scheduler (
    id bigint NOT NULL,
    name character varying(100) NOT NULL,
    state character varying(30),
    last_run_dt timestamp with time zone,
    last_run_log text,
    use_yn          VARCHAR(1) NOT NULL DEFAULT 'Y',
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: regime_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.regime_state (
    symbol_id character varying(16) NOT NULL,
    timeframe character varying(20) DEFAULT '1h'::character varying NOT NULL,
    regime character varying(20) DEFAULT 'UNKNOWN'::character varying NOT NULL,
    pending_regime character varying(20),
    pending_count integer DEFAULT 0 NOT NULL,
    trend_strength numeric(10,6) DEFAULT 0 NOT NULL,
    range_strength numeric(10,6) DEFAULT 0 NOT NULL,
    transition_risk numeric(10,6) DEFAULT 0 NOT NULL,
    adx numeric(18,8),
    atr numeric(18,8),
    bb_bandwidth numeric(18,8),
    ema_gap numeric(18,8),
    computed_at timestamp with time zone,
    confirmed_at timestamp with time zone,
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);


--
-- Name: system_state_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.system_state_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: system_state_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.system_state_id_seq OWNED BY public.system_state.id;


--
-- Name: scheduler_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.scheduler_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: scheduler_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.scheduler_id_seq OWNED BY public.scheduler.id;


--
-- Name: trade_fill; Type: TABLE; Schema: public; Owner: -
--
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


CREATE TABLE public.trade_fill (
    id bigint NOT NULL,
    signal_log_id bigint,
    symbol_id character varying(16),
    side character varying(10),
    entry_order_id character varying(50),
    entry_price numeric(18,8),
    entry_qty numeric(30,10),
    entry_fee numeric(18,8),
    entry_ts timestamp with time zone,
    exit_order_id character varying(50),
    exit_price numeric(18,8),
    exit_fee numeric(18,8),
    exit_ts timestamp with time zone,
    pnl_usd numeric(18,8),
    pnl_pct numeric(18,8),
    r_multiple numeric(18,8),
    slippage_est numeric(18,8),
    status character varying(20),
    risk_budget_usd numeric(18,8),
    attr1 text,
    attr2 text,
    attr3 text,
    attr4 text,
    attr5 text,
    attr6 text,
    attr7 text,
    attr8 text,
    attr9 text,
    attr10 text,
    reg_dt timestamp with time zone DEFAULT now(),
    upd_dt timestamp with time zone
);



create table if not exists strategy_timeframe (
    strategy_name              VARCHAR(100) not NULL,
    timeframe     				VARCHAR(10) NOT null,
    primary key (strategy_name, timeframe)
);
--
-- Name: trade_fill_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.trade_fill_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: trade_fill_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.trade_fill_id_seq OWNED BY public.trade_fill.id;


--
-- Name: analyze_action id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyze_action ALTER COLUMN id SET DEFAULT nextval('public.analyze_action_id_seq'::regclass);


--
-- Name: analyze_result id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyze_result ALTER COLUMN id SET DEFAULT nextval('public.analyze_result_id_seq'::regclass);


--
-- Name: backtest_result id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_result ALTER COLUMN id SET DEFAULT nextval('public.backtest_result_id_seq'::regclass);


--
-- Name: confidence_calibration id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confidence_calibration ALTER COLUMN id SET DEFAULT nextval('public.confidence_calibration_id_seq'::regclass);


--
-- Name: execution_anomaly id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_anomaly ALTER COLUMN id SET DEFAULT nextval('public.execution_anomaly_id_seq'::regclass);


--
-- Name: indicators id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.indicators ALTER COLUMN id SET DEFAULT nextval('public.indicators_id_seq'::regclass);


--
-- Name: job_run_hist log_no; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_run_hist ALTER COLUMN log_no SET DEFAULT nextval('public.job_run_hist_log_no_seq'::regclass);


--
-- Name: ohlcv id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ohlcv ALTER COLUMN id SET DEFAULT nextval('public.ohlcv_id_seq'::regclass);


--
-- Name: ohlcv_summary id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ohlcv_summary ALTER COLUMN id SET DEFAULT nextval('public.ohlcv_summary_id_seq'::regclass);


--
-- Name: position_event id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_event ALTER COLUMN id SET DEFAULT nextval('public.position_event_id_seq'::regclass);


--
-- Name: signal_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_log ALTER COLUMN id SET DEFAULT nextval('public.signal_log_id_seq'::regclass);


--
-- Name: scheduler id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduler ALTER COLUMN id SET DEFAULT nextval('public.scheduler_id_seq'::regclass);


--
-- Name: system_state id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_state ALTER COLUMN id SET DEFAULT nextval('public.system_state_id_seq'::regclass);


--
-- Name: trade_fill id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_fill ALTER COLUMN id SET DEFAULT nextval('public.trade_fill_id_seq'::regclass);


--
-- Name: analyze_action analyze_action_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyze_action
    ADD CONSTRAINT analyze_action_pkey PRIMARY KEY (id);


--
-- Name: analyze_result analyze_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.analyze_result
    ADD CONSTRAINT analyze_result_pkey PRIMARY KEY (id);


--
-- Name: backtest_result backtest_result_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backtest_result
    ADD CONSTRAINT backtest_result_pkey PRIMARY KEY (id);


--
-- Name: confidence_calibration confidence_calibration_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confidence_calibration
    ADD CONSTRAINT confidence_calibration_pkey PRIMARY KEY (id);


--
-- Name: execution_anomaly execution_anomaly_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.execution_anomaly
    ADD CONSTRAINT execution_anomaly_pkey PRIMARY KEY (id);


--
-- Name: indicator_parameter indicator_parameter_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.indicator_parameter
    ADD CONSTRAINT indicator_parameter_pkey PRIMARY KEY (name);


--
-- Name: indicators indicators_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.indicators
    ADD CONSTRAINT indicators_pkey PRIMARY KEY (id);


--
-- Name: job_run_hist job_run_hist_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_run_hist
    ADD CONSTRAINT job_run_hist_pkey PRIMARY KEY (log_no);


--
-- Name: job_run job_run_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.job_run
    ADD CONSTRAINT job_run_pkey PRIMARY KEY (batch_id);


--
-- Name: ohlcv ohlcv_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ohlcv
    ADD CONSTRAINT ohlcv_pkey PRIMARY KEY (id);


--
-- Name: ohlcv_summary ohlcv_summary_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ohlcv_summary
    ADD CONSTRAINT ohlcv_summary_pkey PRIMARY KEY (id);


--
-- Name: position_event position_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.position_event
    ADD CONSTRAINT position_event_pkey PRIMARY KEY (id);


--
-- Name: regime_state regime_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.regime_state
    ADD CONSTRAINT regime_state_pkey PRIMARY KEY (symbol_id);


--
-- Name: signal_log signal_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_log
    ADD CONSTRAINT signal_log_pkey PRIMARY KEY (id);


--
-- Name: scheduler scheduler_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduler
    ADD CONSTRAINT scheduler_name_key UNIQUE (name);


--
-- Name: scheduler scheduler_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scheduler
    ADD CONSTRAINT scheduler_pkey PRIMARY KEY (id);


--
-- Name: symbols symbols_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbols
    ADD CONSTRAINT symbols_pkey PRIMARY KEY (symbol_id);


--
-- Name: system_state system_state_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_state
    ADD CONSTRAINT system_state_pkey PRIMARY KEY (id);


--
-- Name: trade_fill trade_fill_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_fill
    ADD CONSTRAINT trade_fill_pkey PRIMARY KEY (id);


--
-- Name: idx_conf_calibration_interval_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_conf_calibration_interval_symbol ON public.confidence_calibration USING btree (c_interval, symbol_id);


--
-- Name: idx_exec_anomaly_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exec_anomaly_run_id ON public.execution_anomaly USING btree (run_id);


--
-- Name: idx_exec_anomaly_signal_log_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exec_anomaly_signal_log_id ON public.execution_anomaly USING btree (signal_log_id);


--
-- Name: idx_exec_anomaly_trade_fill_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_exec_anomaly_trade_fill_id ON public.execution_anomaly USING btree (trade_fill_id);


--
-- Name: idx_scheduler_use_yn; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_scheduler_use_yn ON public.scheduler USING btree (use_yn);


--
-- Name: idx_indicators_symbol_regymd_interval; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_indicators_symbol_regymd_interval ON public.indicators USING btree (symbol_id, reg_ymd, c_interval);


--
-- Name: idx_ohlcv_symbol_regymd_interval; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ohlcv_symbol_regymd_interval ON public.ohlcv USING btree (symbol_id, reg_ymd, c_interval);


--
-- Name: idx_ohlcv_summary_symbol_regymd_interval; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ohlcv_summary_symbol_regymd_interval ON public.ohlcv_summary USING btree (symbol_id, reg_ymd, c_interval);


--
-- Name: idx_regime_state_regime; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_regime_state_regime ON public.regime_state USING btree (regime);


--
-- Name: idx_signal_log_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_signal_log_run_id ON public.signal_log USING btree (run_id);


--
-- Name: idx_signal_log_symbol_interval_base_ts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_signal_log_symbol_interval_base_ts ON public.signal_log USING btree (symbol_id, c_interval, base_ts DESC);


--
-- Name: idx_trade_fill_signal_log_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_fill_signal_log_id ON public.trade_fill USING btree (signal_log_id);


--
-- Name: idx_trade_fill_symbol_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_trade_fill_symbol_status ON public.trade_fill USING btree (symbol_id, status);


--
-- Name: ux_signal_log_decision; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_signal_log_decision ON public.signal_log USING btree (symbol_id, c_interval, base_ts, prompt_version, indicator_params_version);


--
-- PostgreSQL database dump complete
--

-- insert default symbols data
INSERT INTO public.symbols
(symbol_id, symbol_name, price_precision, quantity_precision, tick_size, step_size, min_price, max_price, min_qty, max_qty, attr1, attr2, attr3, attr4, attr5, attr6, attr7, attr8, attr9, attr10, reg_dt, upd_dt)
VALUES('BTCUSDT', 'BTCUSDT', NULL, 8, 0.10000000, 0.00100000, 556.80000000, 4529764.00000000, 0.0010000000, 1000.0000000000, 'Y', '0003', '20260129', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2025-12-18 19:24:31.630', NULL);
INSERT INTO public.symbols
(symbol_id, symbol_name, price_precision, quantity_precision, tick_size, step_size, min_price, max_price, min_qty, max_qty, attr1, attr2, attr3, attr4, attr5, attr6, attr7, attr8, attr9, attr10, reg_dt, upd_dt)
VALUES('ETHUSDT', 'ETHUSDT', NULL, 8, 0.01000000, 0.00100000, 39.86000000, 306177.00000000, 0.0010000000, 10000.0000000000, 'Y', '0003', '20260129', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2025-12-18 19:24:31.637', NULL);
INSERT INTO public.symbols
(symbol_id, symbol_name, price_precision, quantity_precision, tick_size, step_size, min_price, max_price, min_qty, max_qty, attr1, attr2, attr3, attr4, attr5, attr6, attr7, attr8, attr9, attr10, reg_dt, upd_dt)
VALUES('XRPUSDT', 'XRPUSDT', NULL, 8, 0.00010000, 0.10000000, 0.01430000, 100000.00000000, 0.1000000000, 10000000.0000000000, 'Y', '0003', '20260129', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2025-12-18 19:24:31.638', NULL);
INSERT INTO public.symbols
(symbol_id, symbol_name, price_precision, quantity_precision, tick_size, step_size, min_price, max_price, min_qty, max_qty, attr1, attr2, attr3, attr4, attr5, attr6, attr7, attr8, attr9, attr10, reg_dt, upd_dt)
VALUES('SOLUSDT', 'SOLUSDT', NULL, 8, 0.01000000, 0.01000000, 0.42000000, 6857.00000000, 0.0100000000, 1000000.0000000000, 'Y', '0003', '20260129', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2025-12-18 19:24:31.640', NULL);


-- insert default indicator_parameter
INSERT INTO public.indicator_parameter
("name", tail, col, ma_fast_w, ma_slow_w, ema_fast_w, ema_slow_w, std_w, rsi_w, macd_signal, bollinger_k, atr_w, kd_k_w, kd_d_w, roc_w, momentum_w, mfi_w, donchain_w, keltner_m, linear_regression_slope_w, attr1, attr2, attr3, attr4, attr5, attr6, attr7, attr8, attr9, attr10, reg_dt, upd_dt)
VALUES('default', 50, 'close', 20, 60, 20, 60, 20, 14, 9, 2.0000, 14, 14, 14, 14, 14, 14, 20, 2.0000, 20, 'Y', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2025-12-25 05:14:56.853', '2025-12-25 05:14:56.853');
INSERT INTO public.indicator_parameter
("name", tail, col, ma_fast_w, ma_slow_w, ema_fast_w, ema_slow_w, std_w, rsi_w, macd_signal, bollinger_k, atr_w, kd_k_w, kd_d_w, roc_w, momentum_w, mfi_w, donchain_w, keltner_m, linear_regression_slope_w, attr1, attr2, attr3, attr4, attr5, attr6, attr7, attr8, attr9, attr10, reg_dt, upd_dt)
VALUES('default_2', 50, 'close', 20, 60, 20, 60, 20, 14, 9, 2.0000, 14, 14, 14, 14, 14, 14, 20, 2.0000, 150, 'Y', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-01-15 21:15:46.844', '2026-01-15 21:15:46.844');
INSERT INTO public.indicator_parameter
("name", tail, col, ma_fast_w, ma_slow_w, ema_fast_w, ema_slow_w, std_w, rsi_w, macd_signal, bollinger_k, atr_w, kd_k_w, kd_d_w, roc_w, momentum_w, mfi_w, donchain_w, keltner_m, linear_regression_slope_w, attr1, attr2, attr3, attr4, attr5, attr6, attr7, attr8, attr9, attr10, reg_dt, upd_dt)
VALUES('regime_default', 60, 'close', 20, 60, 20, 60, 20, 14, 9, 2.0000, 14, 14, 14, 14, 14, 14, 20, 2.0000, 20, 'Y', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-01-15 21:15:46.845', '2026-01-15 21:15:46.845');


-- insert default strategy
insert into strategy (strategy_name, module_path, module_name, params_id, use_yn) values
('VolatilityBreakoutRegimeStrategy', 'src.strategy.strategies.volatility_breakout_regime_strategy', 'VolatilityBreakoutRegimeStrategy', 'default_2', 'Y');

insert into strategy_timeframe (strategy_name, timeframe) values ('VolatilityBreakoutRegimeStrategy', '1m'); 
insert into strategy_timeframe (strategy_name, timeframe) values ('VolatilityBreakoutRegimeStrategy', '5m');


\unrestrict 6Ln0sCSjwcJffIl0xhtvmcdaPctdgGvfCi24J79UHcIELKrvXnxq8yqMoCvKQ0j
