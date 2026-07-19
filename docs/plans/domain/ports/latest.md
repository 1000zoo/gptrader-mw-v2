# Ports Latest Plan

- Source path: `src/domain/ports`
- Module: J
- Status: `done`
- Governs: application-facing contracts for market data, account, order execution, strategy repository, and signal log repository.

## Current Plan

Ports are domain/application contracts. Infrastructure implements them; application use cases depend on them. Ports must not expose vendor SDK payloads, database driver types, or framework objects.

## History

- 2026-05-24: Initial ports plan. See `history/2026-05-24-module-j-ports.md`.

## Follow-Up

When new infrastructure is needed, define the narrow port first or reuse an existing one. Do not widen ports for a single adapter convenience.

