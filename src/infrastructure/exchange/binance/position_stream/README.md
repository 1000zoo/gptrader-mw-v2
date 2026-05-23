# Binance Position Stream

This package is reserved for the authenticated Binance position/user-data stream.

Deferred work:

- Build the Binance user-data stream runtime.
- Add reconnect, heartbeat, and stale stream handling.
- Map stream events into domain position events without exposing vendor payloads.
- Wire the stream into Module T websocket monitoring once Module T exists.
