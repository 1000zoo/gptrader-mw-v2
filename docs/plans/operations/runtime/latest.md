# Runtime Operations Latest Plan

- Source path: runtime composition, process entry points, and deployment manifests across `src`
- Module: Operations
- Status: `ready` for execution-focused implementation
- Governs: steps required to run Gptrader V3 locally, in dry-run mode, on Binance testnet, and eventually in armed live mode.

## Current Plan

The domain, application, infrastructure adapter, and interface boundaries are now broadly in place. The next phase is not another isolated module pass. It is an operational composition phase: build the smallest safe runtime that can be started, inspected, stopped, and rehearsed before any live order is possible.

All old module-progress documents have been archived. New work should be tracked by operational run readiness, not by Module A-T completion.

Important archived snapshots:

- `docs/history/progress/2026-06-11-module-progress-board.md`
- `docs/history/codex/2026-06-11-module-agent-charter.md`
- `docs/plans/interfaces/api/history/2026-06-11-api-controller-boundary-and-runtime-readiness.md`
- `docs/plans/interfaces/websocket/history/2026-06-11-position-listener-boundary.md`
- `docs/plans/interfaces/scheduler/history/2026-06-11-scheduler-operational-follow-up.md`
- `docs/plans/infrastructure/exchange/history/2026-06-11-exchange-runtime-follow-up.md`
- `docs/plans/infrastructure/persistence/history/2026-06-11-operational-persistence-follow-up.md`
- `docs/plans/infrastructure/messaging/history/2026-06-11-notifier-adapter-boundary.md`

## Runtime Principle

Execution must advance through explicit modes:

1. `local`: no external exchange calls; uses fakes or local fixtures.
2. `dry-run`: builds real commands and decisions but cannot submit live orders.
3. `testnet`: uses Binance testnet credentials and real exchange APIs.
4. `live-armed`: live credentials plus a separate explicit arming flag.

No live order path should exist unless the selected mode, credentials, risk settings, symbol filters, persistence recovery, and observability are all ready.

## Required Work Streams

### 1. Runtime Environment

- Standardize commands on Python 3.10 or newer.
- Document test and run commands for Windows PowerShell. Current runbook: `docs/runbooks/local-runtime.md`.
- Ensure `requirements.txt` installs into the same interpreter used to run the app.
- Keep `python -m pytest` green before runtime wiring changes are marked done.

### 2. Composition Root

- Add a runtime package, for example `src/runtime`, that owns object construction.
- Build `BinanceConfig`, exchange adapters, repositories, strategies/generators, risk policy, schedulers, websocket listener, API routers, and notifiers in one explicit place.
- Keep local/dry-run/testnet/live mode selection centralized.
- Validate all required environment variables at startup.

### 3. Configuration

- Define one configuration object for symbol, timeframe, candle limit, leverage, base risk ratio, exposure limits, strategy/generator ids, client order prefix, database path/DSN, and runtime mode.
- Document `.env.example` for local, dry-run, testnet, and live-armed.
- Make live mode require both Binance credentials and a separate arming flag.

### 4. Strategy And Indicator Pipeline

- Add at least one concrete strategy or signal generator that can run outside tests.
- Start with a deliberately simple example strategy implementation under `src/domain/strategy/implementations`, such as a latest-close-vs-moving-average strategy. The goal is not profitability; it is a deterministic runtime smoke path.
- Pair the example strategy with a small indicator fixture or loader so local/dry-run composition can build `StrategyContext` without test fakes.
- Add an indicator loader/calculator for the configured symbol/timeframe.
- Decide whether strategy definitions from persistence instantiate live Python objects or only document runtime configuration for the first run.

### 5. Operational Persistence

- Add current-position and execution-state repositories or a deliberately narrower first-run persistence adapter.
- Persist enough state to restart safely: current position, applied position events, order requests, order results, execution reports, scheduler runs, and stream update errors.
- Add schema bootstrap/migration command for the selected local database.
- Reconcile stored state with Binance execution reports before accepting testnet/live orders.

### 6. API Control Plane

- Start with `/health` and readiness endpoints.
- Expose read-only current runtime status before trade controls.
- Add trade control endpoints only after mode gating, idempotency, and persistence recovery are implemented.
- Keep API controllers as injected-usecase boundaries; composition must not leak into request handlers.

### 7. Scheduler Runner

- Add a process entry point for scheduled trade execution and lifecycle runs.
- Prevent overlapping trade runs for the same symbol/timeframe.
- Define idempotent client order ids for retries and restarts.
- Persist scheduler results and expose the latest result through API readiness/status.

### 8. Websocket Runner

- Wire `BinanceUserDataStreamRuntime` through `PositionListener`.
- Persist every accepted `PositionEvent` and resulting `Position`.
- Define how websocket events and periodic execution-report sync deduplicate the same fill.
- Track connected state, last event time, update count, reconnect count, keepalive failures, ignored event count, and last error.

### 9. Messaging And Observability

- Decide first alert policy: runtime failures first, then trade execution and lifecycle promotion.
- Wire Slack/Telegram notifiers only from composition/runtime code.
- Add structured logs for command creation, exchange calls, order submission, scheduler results, stream lifecycle, and API control actions.

### 10. Exchange Safety

- Add exchange preflight checks for permissions, futures mode, symbol status, balance, and leverage/margin assumptions.
- Load and enforce Binance symbol filters before order submission.
- Run Binance testnet rehearsals for order submit, close, sync, user-data stream, reconnect, keepalive, and shutdown.

### 11. Deployment

- Update Docker/runtime manifests after the first runnable entry point exists.
- Decide process layout: single combined process or separate API, scheduler, and websocket listener processes.
- Add graceful shutdown for API, scheduler, websocket stream, and in-flight command handling.

## Execution Milestones

| Step | Status | Exit Criteria |
|------|--------|---------------|
| OP-1 Runtime environment | `done` | Python 3.10+ command documented, dependencies installed, `python -m pytest` green. |
| OP-2 Local composition root | `done` | App can start with fake/local adapters and report healthy readiness. |
| OP-3 Concrete strategy/indicator path | `done` | An example strategy implementation plus local indicator fixture/loader can produce `ExecuteTradeCommand` inputs. |
| OP-4 Local persistence/recovery | `done` | Position/order/run state can be stored and restored locally. |
| OP-5 API readiness/status | `done` | Health/readiness/status endpoints reflect runtime dependencies. |
| OP-6 Scheduler local runner | `ready` | A scheduled dry-run trade command can execute once without overlap. |
| OP-7 Websocket local runner | `queued` | Position listener can process replay/fake stream events and persist updates. |
| OP-8 Messaging wiring | `queued` | Runtime failure alert can be emitted without breaking the caller. |
| OP-9 Binance testnet preflight | `blocked` | Requires OP-2 through OP-5 plus testnet credentials. |
| OP-10 Binance testnet rehearsal | `blocked` | Requires OP-9 and explicit testnet mode. |
| OP-11 Live readiness review | `blocked` | Requires testnet rehearsal evidence, persistence recovery, observability, and live arming controls. |

## History

- 2026-06-11: Created runtime operations plan and switched progress tracking from module completion to execution readiness.
- 2026-06-12: Added OP-1/OP-2 local runtime skeleton plan details and local runtime runbook.
- 2026-06-12: Added OP-3 example moving-average strategy and local market/indicator context builder.
- 2026-06-12: Added OP-4 SQLite runtime state repository for position, position event, and generic runtime records.
- 2026-06-12: Added OP-5 local `/status` endpoint and runtime status details.

## Follow-Up

- Start with OP-1 and OP-2. Do not add live trade controls before the runtime can start locally, report readiness, and shut down cleanly.
