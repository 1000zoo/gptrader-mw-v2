# Websocket Interfaces Latest Plan

- Source path: `src/interfaces/websocket`
- Module: T
- Status: `done` for framework-neutral position listener, `follow-up required` for operational wiring.
- Governs: live websocket entry points and position/event monitoring.

## Current Plan

Module T will provide a framework-neutral websocket entry point for live position event handling.

The first implementation is a position listener that receives already-mapped domain `PositionEvent` values from an injected stream runtime, applies each event to the current domain `Position`, and returns an immutable run record. Infrastructure remains responsible for websocket protocol details, listen-key management, reconnects, and Binance payload mapping.

`src/interfaces/websocket` owns only the interface-level orchestration:

- `event_mapper.py`: applies a domain `PositionEvent` to a domain `Position` and returns an immutable update record.
- `position_listener.py`: consumes a stream runtime, keeps the latest in-memory position for the run, captures errors, and optionally calls an injected update handler for persistence, notification, or application composition.

The listener must not import Binance payload shapes or websocket protocol APIs. It may depend on domain `Position`/`PositionEvent` types and on a protocol describing a runtime with `consume(handler, max_reconnects=...)`.

## History

- 2026-06-11: Added first Module T implementation plan for a framework-neutral live position listener.

## Follow-Up

- Connect the listener to a composition root that builds `BinanceUserDataStreamRuntime`, initial position state, persistence adapters, and operational update handlers.
- Add production observability around stream run duration, update counts, failed event application, reconnect counts, keepalive failures, and ignored event types.
- Add Binance testnet integration coverage before live trading.
- Align operational websocket wiring with the runtime readiness checklist in `docs/plans/interfaces/api/latest.md`.

