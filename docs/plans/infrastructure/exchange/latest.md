# Exchange Infrastructure Latest Plan

- Source path: `src/infrastructure/exchange`
- Module: N
- Status: `done` for first adapter boundary, `follow-up required` for live Binance readiness.
- Governs: exchange-specific adapters, mappers, and position stream infrastructure.

## Current Plan

Exchange infrastructure is split by exchange first, then responsibility: `binance/market_data`, `binance/account`, `binance/order_execution`, and `binance/position_stream`. Vendor payloads must be mapped into domain objects before crossing the port boundary.

The latest architectural change is to reduce over-injection in Binance adapters. Because these adapters already live under `infrastructure/exchange/binance`, callers should not have to inject raw Binance-shaped clients. Binance code should own one internal API boundary through configuration plus a project-owned gateway/factory. Tests may use that gateway seam, but application/interface code must not know Binance SDK method names.

## History

- 2026-05-24: Initial Binance exchange adapter plan. See `history/2026-05-24-module-n-infrastructure-exchange.md`.
- 2026-05-26: Added `Task 5: Binance Client Ownership Refactor` to move raw client ownership behind a project-owned Binance gateway/factory.

## Follow-Up

- Refactor Binance adapters to accept `BinanceConfig` and optional internal gateway rather than raw vendor clients.
- Align the gateway with the actual selected Binance SDK or direct REST API.
- Add retry, timeout, rate-limit, and exchange error translation.
- Implement authenticated user-data/position stream runtime with reconnect and heartbeat handling.

