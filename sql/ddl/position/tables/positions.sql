CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT NOT NULL PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short')),
    quantity NUMERIC NOT NULL CHECK (quantity >= 0),
    average_entry_price NUMERIC NOT NULL CHECK (average_entry_price > 0),
    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    opened_dt TEXT,
    closed_dt TEXT,
    last_event_id TEXT,
    metadata TEXT,
    reg_ymd TEXT NOT NULL,
    reg_dt TEXT NOT NULL,
    upd_dt TEXT NOT NULL,
    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N')),
    CHECK (position_id <> ''),
    CHECK (symbol <> ''),
    CHECK ((status = 'open' AND quantity > 0) OR (status = 'closed' AND quantity = 0))
);
