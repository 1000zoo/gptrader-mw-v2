# Lifecycle Latest Plan

- Source path: `src/domain/lifecycle`
- Module: I
- Status: `done`
- Governs: strategy definitions, generator definitions, evaluations, and promotion policies.

## Current Plan

Lifecycle models define how strategies and signal generators are registered, evaluated, and promoted. Promotion policies compare evaluation metrics against configured thresholds and avoid selecting already-promoted evaluations by default.

## History

- 2026-05-24: Lifecycle design plan. See `history/2026-05-24-module-i-lifecycle-design.md`.
- 2026-05-24: Lifecycle implementation plan. See `history/2026-05-24-module-i-lifecycle.md`.

## Follow-Up

Operational lifecycle scheduling and API exposure should reference this plan but live under `interfaces`.

