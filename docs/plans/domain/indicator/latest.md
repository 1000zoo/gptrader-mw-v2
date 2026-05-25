# Indicator Latest Plan

- Source path: `src/domain/indicator`
- Module: B
- Status: `done`
- Governs: indicator values, indicator sets, and calculator contracts.

## Current Plan

Indicators are timestamped domain values aligned with a market snapshot. Indicator sets enforce duplicate-key prevention and measured-at consistency; calculation remains a contract, not an infrastructure implementation.

## History

- 2026-05-24: Initial indicator module plan. See `history/2026-05-24-module-b-indicator.md`.

## Follow-Up

Concrete indicator calculation libraries or data pipelines should be planned under infrastructure or application composition, while keeping this module exchange-neutral.

