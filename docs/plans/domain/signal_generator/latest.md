# Signal Generator Latest Plan

- Source path: `src/domain/signal_generator`
- Module: E
- Status: `done`
- Governs: generated signals, composite generation, and regime routing.

## Current Plan

Signal generators compose one or more strategies into one generated signal while preserving strategy outputs and metadata. Regime routing delegates to configured strategies based on context metadata without depending on infrastructure.

## History

- 2026-05-24: Design for generator composition. See `history/2026-05-24-module-e-signal-generator-design.md`.
- 2026-05-24: Implementation plan for generator contracts. See `history/2026-05-24-module-e-signal-generator.md`.

## Follow-Up

Operational generator selection and concrete strategy registration belong in application/interface composition plans.

