# Module S Interfaces Scheduler Design

## Goal

Module S adds scheduler entry points that trigger existing application use cases on an external clock without adding business rules, exchange protocol logic, or persistence behavior.

## Approach

Schedulers are framework-neutral Python classes. They receive already-constructed use cases and command factories from the composition root. Each scheduler exposes explicit methods for one scheduled action and returns a small execution record containing the schedule name, command, result, start time, finish time, and success or failure state.

This keeps Module S independent from APScheduler, cron, FastAPI, or deployment settings. A later runtime can call these classes from any scheduling library.

## Components

- `src/interfaces/scheduler/trade_scheduler.py`
  - `TradeScheduler`
  - `ScheduledTradeExecution`
  - `ScheduledPositionClose`
  - `ScheduledPositionSync`
  - calls `ExecuteTradeUseCase.execute`, `ClosePositionUseCase.close`, and `SyncPositionUseCase.sync`

- `src/interfaces/scheduler/strategy_lifecycle_scheduler.py`
  - `StrategyLifecycleScheduler`
  - `ScheduledStrategyLifecycleRun`
  - calls `RunStrategyLifecycleUseCase.execute`

The scheduler classes accept command factory callables rather than raw primitive settings. This avoids duplicating DTO assembly rules in the interface layer.

## Error Handling

Schedulers catch exceptions from command factories and use cases, then return a failed execution record with the exception attached. They do not translate infrastructure-specific exceptions because that belongs to composition or runtime boundaries. Failed records preserve the schedule name and timestamps so the caller can log or alert.

## Testing

Tests verify that each scheduler:

- invokes the correct use case method exactly once,
- passes through the command created by the factory,
- records success metadata and result,
- records factory or use-case failures without swallowing the exception object,
- does not perform domain decisions itself.

