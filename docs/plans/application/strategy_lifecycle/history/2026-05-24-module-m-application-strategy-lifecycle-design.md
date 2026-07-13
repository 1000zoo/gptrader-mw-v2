# Module M Application Strategy Lifecycle Design

**Goal:** Define application usecases that connect registered lifecycle definitions, research evaluations, and promotion decisions.

## Scope

Module M owns `src/application/usecases/strategy_lifecycle`.

It adds usecases for:

- registering `StrategyDefinition` and `SignalGeneratorDefinition`
- promoting an existing `StrategyEvaluation` through `PromotionPolicy`
- running the lifecycle promotion boundary for an existing target

It does not run backtests, send notifications, register schedulers, or implement persistence adapters.

## Architecture

The module depends on `StrategyRepositoryPort` from `src/domain/ports` and lifecycle domain models from `src/domain/lifecycle`.

`RegisterStrategyUseCase` stores either a strategy definition or a signal generator definition and returns the saved definition. It does not validate implementation imports or strategy graph semantics beyond the lifecycle model invariants.

`PromoteStrategyUseCase` loads evaluations for a target, finds the requested evaluation, applies `PromotionPolicy`, and saves a new promoted evaluation when the policy passes. Failed promotion returns a rejected result instead of raising, because failing a threshold is an expected business outcome.

`RunStrategyLifecycleUseCase` provides a thin operational boundary for interfaces and schedulers. It selects the latest evaluation for a target unless a specific evaluation id is provided, delegates promotion to `PromoteStrategyUseCase`, and returns the promotion result.

## Data Flow

1. Interface code passes a command DTO into a strategy lifecycle usecase.
2. The usecase reads or writes lifecycle models through `StrategyRepositoryPort`.
3. Promotion decisions use `PromotionPolicy` and never inspect metrics directly in application code.
4. A successful promotion is represented by saving a new `StrategyEvaluation` with `StrategyLifecycleStatus.PROMOTED`.

## Error Handling

Blank ids and invalid DTO inputs raise `ValueError` during command construction.

Missing targets or evaluations return result DTOs with `promoted=False` and a reason string. Policy rejection also returns `promoted=False`. Repository failures are not caught here; infrastructure adapters should expose failures in their own layer.

## Testing

Tests use an in-memory fake `StrategyRepositoryPort`. Coverage should prove registration saves definitions, promotion saves a promoted evaluation when policy passes, policy rejection does not save, missing evaluations are reported, and lifecycle execution delegates to the promotion path.
