# Exchange Infrastructure Latest Plan

- Source path: `src/infrastructure/exchange`
- Module: N
- Status: `done` for first adapter boundary and first Binance REST/stream runtime hardening, `follow-up required` for Module T integration and production tuning.
- Governs: exchange-specific adapters, mappers, and position stream infrastructure.

## Current Plan

Exchange infrastructure is split by exchange first, then responsibility: `binance/market_data`, `binance/account`, `binance/order_execution`, and `binance/position_stream`. Vendor payloads must be mapped into domain objects before crossing the port boundary.

The latest architectural change is to reduce over-injection in Binance adapters. Because these adapters already live under `infrastructure/exchange/binance`, callers should not have to inject raw Binance-shaped clients. Binance code should own one internal API boundary through configuration plus a project-owned gateway/factory. Tests may use that gateway seam, but application/interface code must not know Binance SDK method names.

Development reference: [`binance-usdm-futures-api-spec-2026.md`](binance-usdm-futures-api-spec-2026.md) summarizes the Binance USD-M Futures endpoints currently expected by Gptrader V3.

## Binance Runtime Configuration

`BinanceConfig.default()` targets live USD-M Futures at `https://fapi.binance.com`. `BinanceConfig.from_env()` reads credentials and runtime settings from environment variables:

- `BINANCE_API_KEY` / `BINANCE_API_SECRET`: credentials for signed endpoints.
- `BINANCE_TESTNET=true`: selects the USD-M Futures testnet REST base URL, `https://testnet.binancefuture.com`.
- `BINANCE_BASE_URL`: explicit base URL override. This takes precedence over `BINANCE_TESTNET`.
- `BINANCE_TIMEOUT` and `BINANCE_RECV_WINDOW`: request timeout and signed request receive window.
- `BINANCE_RETRY_ATTEMPTS` and `BINANCE_RETRY_DELAY`: retry count and delay for transient network/rate-limit errors.

`request_json()` now retries transient network failures and Binance rate-limit responses. Rate-limit responses with `Retry-After` take precedence over the configured retry delay. HTTP error classification still distinguishes generic REST failures, rate limits, and unknown execution status responses so order reconciliation can treat ambiguous order submission separately.

## Binance User Data Stream Runtime

`src/infrastructure/exchange/binance/position_stream` owns the authenticated Binance User Data Stream runtime:

- `start_user_data_stream_api`, `keepalive_user_data_stream_api`, and `close_user_data_stream_api` manage `/fapi/v1/listenKey` through API-key-only REST calls.
- `BinanceUserDataStreamRuntime.consume()` connects to the listen-key websocket URL, keeps the listen key alive, reconnects after stream connection failures, and emits mapped domain `PositionEvent` objects through a caller-provided handler.
- Raw Binance `ORDER_TRADE_UPDATE` payloads are mapped inside infrastructure and do not cross into application or interfaces code.

## Documentation Placement

Exchange infrastructure plans and design notes must stay under `docs/plans/infrastructure/exchange/`.

- Current exchange guidance belongs in `docs/plans/infrastructure/exchange/latest.md`.
- Exchange implementation histories belong in `docs/plans/infrastructure/exchange/history/`.
- Binance API reference documents belong in `docs/plans/infrastructure/exchange/`.
- Do not place exchange-specific plans directly under `docs/plans/`.

## History

- 2026-05-24: Initial Binance exchange adapter plan. See `history/2026-05-24-module-n-infrastructure-exchange.md`.
- 2026-05-26: Added `Task 5: Binance Client Ownership Refactor` to move raw client ownership behind a project-owned Binance gateway/factory.
- 2026-05-26: Added Binance USD-M Futures API development reference spec for live adapter implementation.
- 2026-05-26: Added Binance direct REST design and implementation plan under `history/`.

## Follow-Up

- Module R operational composition should connect `BinanceUserDataStreamRuntime` through `PositionListener` to application/domain position update flows without exposing Binance payloads.
- Add production observability around reconnect counts, listen-key keepalive failures, and dropped/ignored stream event types.
- Add exchange preflight checks and Binance exchange-info filter enforcement before live order submission, as tracked in `docs/plans/interfaces/api/latest.md`.
- Add broader integration tests against Binance testnet before live trading.
