# Exchange Infrastructure Latest Plan

- Source path: `src/infrastructure/exchange`
- Module: N
- Status: `done` for first adapter boundary, `follow-up required` for live Binance readiness.
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

- Refactor Binance adapters to accept `BinanceConfig` and optional internal gateway rather than raw vendor clients.
- Align the gateway with the actual selected Binance SDK or direct REST API.
- Add retry, timeout, rate-limit, and exchange error translation.
- Implement authenticated user-data/position stream runtime with reconnect and heartbeat handling.
