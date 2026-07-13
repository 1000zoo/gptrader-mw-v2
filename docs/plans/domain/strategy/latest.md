# Strategy Latest Plan

- Source path: `src/domain/strategy`
- Module: D
- Status: `done`
- Governs: strategy protocol, strategy context, and strategy result contract.

## Current Plan

Strategies consume market snapshots and indicator sets through `StrategyContext` and return `StrategyResult` without knowing about persistence, exchange clients, or scheduling. Strategy implementations may live under `src/domain/strategy/implementations` only when they are pure domain logic.

Concrete strategy implementation notes live under `implementations/`. Start with `implementations/README.md`, then read the strategy-specific document before adding code.

## History

- 2026-05-24: Design split for strategy boundaries. See `history/2026-05-24-module-d-strategy-design.md`.
- 2026-05-24: Implementation plan for strategy contract. See `history/2026-05-24-module-d-strategy.md`.

## Follow-Up

The repo now has a code-native catalog for concrete strategy candidates. Catalog entries declare required indicator keys through `StrategySpec.indicator_keys`, and the strategy backtest cycle can build simple moving-average indicators from market snapshots. Live execution still needs runtime composition that supplies real market data, repositories, and scheduler command factories before scheduled decisions can be promoted into operational use.

Current concrete strategy candidates:

- `latest-close-moving-average`: default catalog entry backed by `LatestCloseMovingAverageStrategy`; declares and consumes the `moving_average.period_3` indicator key.
- `session-volume-profile`: default catalog entry backed by `SessionVolumeProfileStrategy`; design notes live in `implementations/session-volume-profile.md` and cover POC, value area, rejection, and breakout behavior.

Indicator wiring status:

- Strategy context validation is implemented at the domain boundary.
- `latest-close-moving-average` depends on an externally supplied moving-average indicator value.
- `session-volume-profile` computes its candle-based profile from market candles and does not require a separate indicator value today.
- `StrategySpec.indicator_keys` records catalog-level indicator requirements.
- The backtest cycle includes a snapshot-based moving-average indicator builder for declared `moving_average.period_N` keys.
- Scheduler/runtime composition still needs to connect real market data and repository adapters to the cataloged strategy cycle.

