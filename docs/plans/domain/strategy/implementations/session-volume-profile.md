# Session Volume Profile Strategy

## Purpose

Add a concrete strategy candidate that uses session volume profile structure to decide whether price is accepting value, rejecting value, or breaking out from a prior auction range.

This document is a strategy explanation and implementation plan. It does not change runtime behavior until the code tasks below are executed.

## What Session Volume Profile Means

Session volume profile groups traded volume by price level for a bounded trading session instead of grouping volume by time. A normal candle chart answers "what happened during each time interval"; a volume profile answers "where did trading concentrate by price during this session."

For each session, the profile produces several important reference levels:

- **Point of Control (POC):** the price level with the highest traded volume. It represents the session's strongest consensus price.
- **Value Area:** the price range that contains a configured share of total session volume, commonly 70%.
- **Value Area High (VAH):** the upper boundary of the value area.
- **Value Area Low (VAL):** the lower boundary of the value area.
- **High Volume Nodes (HVN):** prices or bins with unusually high volume, often treated as acceptance or magnets.
- **Low Volume Nodes (LVN):** prices or bins with unusually low volume, often treated as rejection zones or fast-travel gaps.

The strategy is not trying to predict price from volume alone. It treats volume profile levels as market structure and combines them with the latest candle location, close behavior, and optional trend or volatility filters.

## Trading Interpretation

The first implementation should support three behaviors:

- **Value acceptance:** if price closes inside the value area and near the POC, the market is balanced. The strategy should usually emit `WAIT` because directional edge is weak.
- **Value rejection:** if price probes above VAH or below VAL but closes back inside value, the strategy can fade the failed move. A rejection above VAH creates a short bias; a rejection below VAL creates a long bias.
- **Value breakout:** if price closes outside VAH or VAL with enough volume confirmation, the strategy can follow continuation. A close above VAH creates a long bias; a close below VAL creates a short bias.

The strategy should prefer explicit wait signals when the profile is incomplete, the latest candle sits directly at the POC, or breakout and rejection rules conflict.

## Required Inputs

The current `StrategyContext` contains:

- `context.market.candles`
- `context.market.latest_candle`
- `context.indicators`
- `context.metadata`

The first implementation should keep the strategy pure domain logic and avoid exchange, database, scheduler, or research dependencies.

Required market data:

- A chronological candle set covering exactly one configured session window.
- Candle OHLCV fields, especially `high_price`, `low_price`, `close_price`, and `volume`.
- A timeframe small enough to approximate price-level volume distribution. One-minute or five-minute candles are preferred.

Required configuration:

- `price_bin_size`: Decimal price increment used to group volume.
- `value_area_ratio`: Decimal ratio of session volume included in value area. Default: `0.70`.
- `profile_min_candles`: minimum candles required before generating directional signals.
- `breakout_volume_multiplier`: latest-candle volume threshold relative to average session candle volume.
- `rejection_wick_ratio`: minimum wick share for failed moves back inside value.

## Profile Calculation Approach

The first implementation should build an approximate profile from candles because the domain model does not currently expose tick-level or trade-level volume.

For each candle:

1. Determine all price bins touched by the candle range from `low_price` to `high_price`.
2. Distribute candle volume evenly across those bins.
3. Sum volume per bin across the session.
4. Select the POC as the bin with the highest volume.
5. Build the value area by starting at POC and expanding to neighboring bins with the larger next available volume until cumulative volume reaches `value_area_ratio` of total volume.

This approximation is less precise than true traded-volume-at-price data, but it keeps the first strategy implementable with the existing `Candle` model.

## Signal Rules

### Wait Conditions

Return `Signal.wait(...)` when:

- candle count is below `profile_min_candles`;
- total session volume is zero;
- the computed profile has no bins;
- latest close is inside value and within one `price_bin_size` of POC;
- latest candle overlaps both VAH and VAL, making structure ambiguous;
- breakout and rejection conditions are both true.

### Long Conditions

Return `LONG` when either:

- **Lower rejection:** latest candle trades below VAL, closes back above VAL, and lower wick ratio is at least `rejection_wick_ratio`.
- **Upper breakout:** latest close is above VAH and latest candle volume is at least average session volume multiplied by `breakout_volume_multiplier`.

### Short Conditions

Return `SHORT` when either:

- **Upper rejection:** latest candle trades above VAH, closes back below VAH, and upper wick ratio is at least `rejection_wick_ratio`.
- **Lower breakout:** latest close is below VAL and latest candle volume is at least average session volume multiplied by `breakout_volume_multiplier`.

## Confidence Model

Confidence should stay bounded and explainable:

- Base rejection confidence: `0.45`.
- Base breakout confidence: `0.50`.
- Add up to `0.25` for distance from VAH or VAL measured in bins.
- Add up to `0.20` for latest volume relative to average session volume.
- Cap confidence at `1.00`.
- Floor directional confidence at `0.10`.

The exact formula should be deterministic and covered by unit tests.

## Result Metadata

`StrategyResult.metadata` should include:

- `price_bin_size`
- `value_area_ratio`
- `poc`
- `value_area_high`
- `value_area_low`
- `total_volume`
- `profile_bin_count`
- `decision_type`: one of `wait`, `lower_rejection`, `upper_rejection`, `upper_breakout`, `lower_breakout`

Each emitted `SignalReason` should include the same key profile levels that justified the decision.

## Edge Cases

- Decimal arithmetic must avoid float conversion.
- Candle ranges can span many bins; tests should include multi-bin and single-bin candles.
- Equal-volume POC ties should resolve deterministically by choosing the lower price bin.
- Value-area expansion ties should expand lower first, then upper, to keep results stable.
- If `price_bin_size <= 0`, strategy construction should raise `ValueError`.
- If `value_area_ratio` is not within `(0, 1]`, strategy construction should raise `ValueError`.

## Implementation Plan

### Task 1: Add Profile Model and Calculator

Files:

- Create `src/domain/strategy/implementations/session_volume_profile.py`
- Create `tests/domain/strategy/test_session_volume_profile_strategy.py`

Implementation:

- Add an immutable `SessionVolumeProfile` dataclass with `poc`, `value_area_high`, `value_area_low`, `total_volume`, and `volume_by_price`.
- Add a private `_build_profile(candles, price_bin_size, value_area_ratio)` helper.
- Test profile construction for POC, VAH, VAL, total volume, deterministic ties, and invalid configuration.

### Task 2: Add Strategy Shell

Files:

- Modify `src/domain/strategy/implementations/session_volume_profile.py`
- Modify `src/domain/strategy/implementations/__init__.py`
- Modify `tests/domain/strategy/test_session_volume_profile_strategy.py`

Implementation:

- Add `SessionVolumeProfileStrategy` as a frozen dataclass.
- Expose `name = "session-volume-profile"`.
- Validate configuration in `__post_init__`.
- Return `WAIT` for insufficient candles, zero volume, and balanced value acceptance.

### Task 3: Implement Rejection Signals

Files:

- Modify `src/domain/strategy/implementations/session_volume_profile.py`
- Modify `tests/domain/strategy/test_session_volume_profile_strategy.py`

Implementation:

- Add upper rejection short rule.
- Add lower rejection long rule.
- Include profile levels and wick ratio in `SignalReason.metadata`.
- Test both directions and the ambiguous-conflict wait path.

### Task 4: Implement Breakout Signals

Files:

- Modify `src/domain/strategy/implementations/session_volume_profile.py`
- Modify `tests/domain/strategy/test_session_volume_profile_strategy.py`

Implementation:

- Add upper breakout long rule.
- Add lower breakout short rule.
- Require latest candle volume confirmation against average session candle volume.
- Test confirmed breakouts, unconfirmed breakout waits, and confidence cap behavior.

### Task 5: Verify Strategy Integration

Files:

- Modify `tests/domain/strategy/test_session_volume_profile_strategy.py`

Implementation:

- Assert the strategy satisfies the `Strategy` protocol.
- Assert result names, metadata keys, signal direction, confidence, and reason codes.
- Run `pytest tests/domain/strategy -v`.
- Run the full test suite with `pytest`.

## Open Design Notes

The candle-based profile is an approximation. If the project later adds trade-level or aggregated volume-at-price data, the profile calculator should become a separate domain service or indicator so multiple strategies can reuse exact profile levels.

The first implementation should not add persistence schema. Store strategy output through the existing signal and strategy result paths only.
