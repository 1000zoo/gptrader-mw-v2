# Execution Latest Plan

- Source path: `src/domain/execution`
- Module: H
- Status: `done`
- Governs: order requests, order results, and execution reports.

## Current Plan

Execution domain objects define exchange-neutral order and fill semantics. Execution reports convert filled order results into position events, including reduce-only safeguards.

## History

- 2026-05-24: Initial execution domain plan. See `history/2026-05-24-module-h-execution.md`.

## Follow-Up

Exchange adapters must map vendor responses into these objects and handle vendor-specific errors outside the domain.

