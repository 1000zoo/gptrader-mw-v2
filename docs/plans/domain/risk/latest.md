# Risk Latest Plan

- Source path: `src/domain/risk`
- Module: F
- Status: `done`
- Governs: exposure limits, risk checks, and position sizing.

## Current Plan

Risk calculates whether an entry is allowed and how large the resulting position should be. It owns exposure math and rejects exhausted exposure before order request construction.

## History

- 2026-05-24: Design for risk policy and sizing. See `history/2026-05-24-module-f-risk-design.md`.
- 2026-05-24: Implementation plan for risk domain. See `history/2026-05-24-module-f-risk.md`.

## Follow-Up

Future exchange-specific margin details should be translated before entering this domain model.

