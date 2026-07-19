CREATE TABLE IF NOT EXISTS order_results (
    order_id TEXT NOT NULL PRIMARY KEY,
    request_id TEXT,
    client_order_id TEXT NOT NULL,
    exchange_order_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'rejected', 'filled', 'partially_filled', 'canceled')),
    executed_quantity NUMERIC,
    average_price NUMERIC,
    failure_reason TEXT,
    payload TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    FOREIGN KEY (request_id) REFERENCES order_requests (request_id),
    CHECK (order_id <> ''),
    CHECK (client_order_id <> ''),
    CHECK (
        (status = 'rejected' AND failure_reason IS NOT NULL AND failure_reason <> '' AND executed_quantity IS NULL AND average_price IS NULL)
        OR (status IN ('filled', 'partially_filled') AND executed_quantity > 0 AND average_price > 0 AND failure_reason IS NULL)
        OR (status IN ('accepted', 'canceled') AND executed_quantity IS NULL AND average_price IS NULL AND failure_reason IS NULL)
    )
);
