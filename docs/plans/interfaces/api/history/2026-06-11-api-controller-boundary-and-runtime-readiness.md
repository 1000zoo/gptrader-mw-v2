# API Interfaces Latest Plan

- Source path: `src/interfaces/api`
- Module: R
- Status: `done` for controller/router boundary, `follow-up required` for operational composition and live controls.
- Governs: HTTP or external API entry points for application use cases.

## Current Plan

Module R provides the first API controller boundary for Gptrader V3. API work exposes application use cases without duplicating business rules or constructing vendor-specific infrastructure inline.

The first API surface should be operational rather than research-heavy:

- health/readiness checks for process, dependency, exchange, persistence, scheduler, and stream status;
- trade controls for dry-run/armed live mode, manual trade trigger, close-position trigger, and position sync trigger;
- strategy lifecycle controls for registering, evaluating, and promoting strategies already supported by application use cases;
- read-only operational views for current position, last trade run, last scheduler run, last stream update, and recent errors.

The initial implementation provides FastAPI app/router factories and controller boundaries for strategy, trade, and position operations. Controllers receive use cases and command factories through constructor/factory injection. This keeps domain object construction and runtime adapter wiring in the future composition root, while API handlers only validate dependency presence, call the injected boundary, and serialize responses.

The API should be backed by an explicit composition root before live use. That composition root should build infrastructure adapters, repositories, concrete strategies/generators, risk settings, scheduler entry points, and websocket listeners, then inject them into the interface layer. API handlers must not import Binance payload shapes or call low-level REST/websocket helpers directly.

## Runtime Readiness Checklist

Before the system is actually run against Binance, complete the items below.

### Runtime Environment

- Standardize on Python 3.10 or newer and make local/test/deploy commands use that interpreter. The current default `python` on one workstation resolved to Python 3.9, which cannot import the current type-hint syntax.
- Install dependencies from `requirements.txt` into the same Python runtime used by tests and runners.
- Keep `tests/__init__.py` so full test collection resolves shared helpers such as `tests.domain...` from the local repository.
- Add documented commands for unit tests, integration tests, local dry-run, scheduler runner, websocket listener, and API server.

### Composition Root

- Add a concrete composition root that creates `BinanceConfig.from_env()`, `BinanceMarketDataAdapter`, `BinanceAccountAdapter`, `BinanceOrderExecutionAdapter`, `BinanceUserDataStreamRuntime`, persistence repositories, strategy/generator implementations, `RiskPolicy`, `PositionSizer`, `TradeScheduler`, `StrategyLifecycleScheduler`, and `PositionListener`.
- Keep mode selection explicit: local fake, Binance testnet, and Binance live must be separate runtime modes.
- Add startup validation that required environment variables exist for the selected mode.
- Add a single place to configure symbol, timeframe, candle limit, risk ratio, leverage, exposure limits, strategy/generator ids, and client order id prefixes.

### Strategy And Indicator Pipeline

- Add at least one concrete strategy or signal generator that can run without test fakes. `src/domain/strategy/implementations` is currently empty.
- Add indicator calculation or loading for the configured timeframe so `ExecuteTradeCommand.indicators` can be built outside tests.
- Define how strategy/generator definitions in persistence are converted into live Python strategy/generator objects.

### Operational Persistence

- Implement repository ports/adapters for current `Position`, `PositionEvent`, `OrderRequest`, `OrderResult`, `ExecutionReport`, and `trade_runs`, or explicitly choose a narrower first-run storage scope.
- Add migrations or schema bootstrap for the deployment database. DDL exists under `sql/ddl`, but operational adapters for the priority trading state are still missing.
- Define restart recovery: load the latest open position, replay unapplied position events if needed, and reconcile with exchange execution reports before accepting live orders.
- Persist scheduler runs, websocket stream updates, and failed event applications enough to debug production incidents.

### Exchange Safety

- Run Binance testnet integration before live trading. Test order submission, close orders, execution report sync, user-data stream events, reconnect, listen-key keepalive, and shutdown.
- Add exchange preflight checks for account permissions, futures account mode, leverage/margin expectations, symbol availability, and balances.
- Cache and enforce Binance symbol filters from exchange info before submitting orders: quantity step size, min quantity, min notional, price tick size, and order type constraints.
- Make live mode require an explicit arming flag in addition to credentials.

### Scheduler Runner

- Add an operational runner around `src/interfaces/scheduler` using APScheduler, cron, or a simple managed loop.
- Ensure scheduled trade execution cannot overlap for the same symbol/timeframe unless explicitly allowed.
- Define idempotency and client order id policy for retries, process restarts, and duplicate scheduler fires.
- Decide whether scheduler failures are only logged, persisted, alerted, or exposed through API health status.

### Websocket Listener

- Wire `PositionListener` to `BinanceUserDataStreamRuntime` in the composition root.
- Provide an update handler that persists `PositionEvent` and the resulting `Position`.
- Decide how websocket updates and periodic `SyncPositionUseCase` reconciliation interact when both see the same fill.
- Add stream observability: connected state, last event time, update count, reconnect count, keepalive failures, dropped/ignored event counts, and last error.

### API Surface

- Add minimal FastAPI app under `src/interfaces/api` with health/readiness first.
- Add safe control endpoints only after runtime mode, persistence, and idempotency rules are fixed.
- Return domain/application DTOs or API DTOs derived from them; do not expose infrastructure payloads.
- Add authentication or network boundary assumptions before any live trading endpoint exists.

### Messaging And Observability

- Decide Module Q scope for first run: runtime failure alerts, trade execution alerts, lifecycle promotion alerts, or all of them.
- Add structured logs for command creation, order submission, position updates, scheduler results, stream lifecycle, and API control actions.
- Add metrics or persisted counters for operational dashboards.

### Deployment

- Update Docker and runtime manifests once the API/runner entry point exists.
- Document `.env` variables for testnet and live separately.
- Add process supervision expectations: API process, scheduler process, websocket listener process, or a single combined process.
- Add graceful shutdown for websocket close, scheduler stop, and in-flight order handling.

## History

- 2026-06-11: Selected the first API surface as the operational control plane and added the runtime readiness checklist.
- 2026-06-11: Added FastAPI app/router factories for health, strategy, trade, and position controller boundaries.
- 2026-06-11: Added `tests/__init__.py` so full `python -m pytest` collection resolves local test helper imports.

## Follow-Up

- Implement health/readiness and composition-root scaffolding before exposing trade controls.
- Keep scheduler runner and websocket listener wiring aligned with the runtime readiness checklist above.

