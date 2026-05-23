# Exchange Position Stream

This package is reserved for responsibility-level position stream interfaces.
Exchange-specific implementations live under `src/infrastructure/exchange/<exchange>/position_stream/`, starting with `src/infrastructure/exchange/binance/position_stream/`.

Deferred work:

- Build the Binance user-data stream runtime.
- Add reconnect, heartbeat, and stale stream handling.
- Map stream events into domain position events without exposing vendor payloads.
- Wire the stream into Module T websocket monitoring once Module T exists.
