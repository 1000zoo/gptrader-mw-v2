CREATE TABLE IF NOT EXISTS strategy_evaluation_metrics (
    metric_id TEXT NOT NULL PRIMARY KEY,
    evaluation_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value NUMERIC NOT NULL,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    UNIQUE (evaluation_id, metric_name),
    FOREIGN KEY (evaluation_id) REFERENCES strategy_evaluations (evaluation_id),
    CHECK (metric_id <> ''),
    CHECK (metric_name <> '')
);
