# Module I Lifecycle Design

## Goal

Define the pure domain language for strategy lifecycle management from registration through evaluation and promotion eligibility.

## Scope

Module I owns only `src/domain/lifecycle` and `tests/domain/lifecycle`.
It does not implement backtesting, persistence, scheduling, exchange calls, or application orchestration.

## Recommended Approach

Use a minimal immutable domain model:

- `StrategyDefinition` stores a stable strategy identity and implementation reference.
- `SignalGeneratorDefinition` stores a named composition of strategy definitions and optional regime routing.
- `StrategyEvaluation` stores measured evaluation results and lifecycle status.
- `PromotionPolicy` decides whether an evaluation is eligible for promotion.

This keeps lifecycle state available to Module J ports, Module L research flows, Module M strategy lifecycle use cases, and Module O persistence without pulling lower-layer concerns into the domain.

## Data Model

`StrategyDefinition` uses string identifiers, an implementation path, version, and metadata.
`SignalGeneratorDefinition` references strategy ids and optional regime-to-strategy-id routing.
`StrategyEvaluation` uses `Decimal` metrics and a lifecycle status enum.
`PromotionPolicy` uses required metric thresholds and allowed statuses.

## Rules

- Strategy ids, names, implementation references, versions, and generator ids are required after trimming.
- Definition metadata and parameter mappings are defensively copied.
- Signal generator definitions require at least one strategy id.
- Regime routing can only reference strategy ids included in the generator definition.
- Evaluations store immutable metric mappings and expose metric lookup by name.
- Promotion requires an allowed evaluation status and all configured metric thresholds to be met.
- Missing required metrics make promotion fail rather than raising.

## Testing

Use TDD with focused tests for:

- strategy definition normalization and defensive copies
- signal generator strategy references and invalid regime routes
- evaluation metric lookup and immutable metrics
- promotion policy pass/fail behavior for status, missing metrics, and thresholds
