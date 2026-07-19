# Binance Position Stream

This package contains the authenticated Binance User Data Stream runtime.

Implemented:

- listen-key start, keepalive, and close calls through `/fapi/v1/listenKey`.
- websocket URL construction for production, testnet, and custom base URLs.
- async runtime with reconnect delay and listen-key keepalive task.
- `ORDER_TRADE_UPDATE` mapping into domain `PositionEvent` values.

Deferred work:

- Wire the stream into Module T websocket monitoring once Module T exists.
- Add production metrics/logging for reconnects, keepalive failures, and ignored events.
