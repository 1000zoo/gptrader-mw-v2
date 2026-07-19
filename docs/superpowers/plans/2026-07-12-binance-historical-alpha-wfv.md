# Binance Historical Alpha WFV Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add timestamp-safe Binance historical market features, build structurally new entry alpha families, and produce strict 6-month-train/1-month-OOS walk-forward results.

**Architecture:** Candle data and non-candle features remain separate ports. Binance archive/API rows are normalized into immutable minute feature sets, injected by `ExecuteTradeUseCase` at the latest closed-candle timestamp, and replayed through the existing scheduler-driven backtest. The candidate universe is frozen before OOS ranking.

**Tech Stack:** Python 3.14, dataclasses, Decimal, urllib/zipfile/csv, pytest, Binance USD-M Futures public archives/REST, existing scheduler-driven research runner.

---

### Task 1: Typed Market Feature Contract

**Files:**
- Create: `src/domain/market_feature/market_feature_value.py`
- Create: `src/domain/market_feature/market_feature_set.py`
- Create: `src/domain/market_feature/__init__.py`
- Create: `src/domain/ports/market_feature_provider_port.py`
- Modify: `src/domain/ports/__init__.py`
- Test: `tests/domain/market_feature/test_market_feature_set.py`

- [ ] **Step 1: Write failing domain tests**

```python
def test_feature_set_rejects_future_available_value():
    measured_at = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    value = MarketFeatureValue(
        name="taker_imbalance",
        value=Decimal("0.2"),
        source="binance_klines",
        observed_at=measured_at,
        available_at=measured_at + timedelta(microseconds=1),
    )
    with pytest.raises(ValueError, match="available_at"):
        MarketFeatureSet(SYMBOL, TIMEFRAME, measured_at, (value,), ())


def test_missing_source_is_not_represented_as_zero():
    features = MarketFeatureSet(SYMBOL, TIMEFRAME, MEASURED_AT, (), ("open_interest",))
    assert features.get("open_interest") is None
    assert "open_interest" in features.unavailable_sources
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\domain\market_feature\test_market_feature_set.py -q`

Expected: import failure because `src.domain.market_feature` does not exist.

- [ ] **Step 3: Implement immutable types and provider protocol**

```python
@dataclass(frozen=True)
class MarketFeatureValue:
    name: str
    value: Decimal
    source: str
    observed_at: datetime
    available_at: datetime


@dataclass(frozen=True)
class MarketFeatureSet:
    symbol: Symbol
    timeframe: Timeframe
    measured_at: datetime
    values: tuple[MarketFeatureValue, ...]
    unavailable_sources: tuple[str, ...] = ()

    def get(self, name: str) -> MarketFeatureValue | None:
        return next((value for value in self.values if value.name == name), None)
```

Validate unique names, timezone-aware timestamps, `observed_at <= available_at <= measured_at`, and immutable normalized tuples. Add runtime-checkable `MarketFeatureProviderPort.load_features(symbol, timeframe, as_of)`.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `.\.venv\Scripts\python.exe -m pytest tests\domain\market_feature\test_market_feature_set.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1 files only**

```powershell
git add src/domain/market_feature src/domain/ports/market_feature_provider_port.py src/domain/ports/__init__.py tests/domain/market_feature
git commit -m "Add timestamp-safe market feature contract"
```

### Task 2: Scheduler Use-Case Feature Injection

**Files:**
- Modify: `src/domain/strategy/strategy_context.py`
- Modify: `src/application/usecases/trade/execute_trade_usecase.py`
- Modify: `src/application/usecases/trade/manage_open_position_usecase.py`
- Create: `src/infrastructure/market_feature/empty_market_feature_provider.py`
- Create: `src/infrastructure/market_feature/in_memory_market_feature_provider.py`
- Test: `tests/domain/strategy/test_strategy_context.py`
- Test: `tests/application/usecases/trade/test_execute_trade_usecase.py`
- Test: `tests/application/usecases/trade/test_manage_open_position_usecase.py`
- Test: `tests/infrastructure/market_feature/test_in_memory_market_feature_provider.py`

- [ ] **Step 1: Write failing alignment and injection tests**

```python
def test_execute_uses_latest_closed_candle_as_feature_cutoff():
    usecase = build_usecase(market_feature_provider=recording_provider)
    usecase.execute(command)
    assert recording_provider.requested_as_of == market.latest_candle.closed_at
    assert generator.context.market_features is recording_provider.result
```

Add tests rejecting feature-set symbol/timeframe/measured-at mismatches and proving a row at `T+1us` is invisible at decision time `T`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\domain\strategy\test_strategy_context.py tests\application\usecases\trade\test_execute_trade_usecase.py tests\application\usecases\trade\test_manage_open_position_usecase.py tests\infrastructure\market_feature\test_in_memory_market_feature_provider.py -q`

Expected: constructor/property failures for missing feature integration.

- [ ] **Step 3: Inject the feature provider below the scheduler**

```python
features = self._market_feature_provider.load_features(
    symbol=market.symbol,
    timeframe=market.timeframe,
    as_of=market.latest_candle.closed_at,
)
context = StrategyContext(
    market=market,
    indicators=command.indicators,
    metadata={MARKET_FEATURES_METADATA_KEY: features},
)
```

Use `EmptyMarketFeatureProvider` as the backward-compatible default. Implement `InMemoryMarketFeatureProvider` with `bisect_right` on `available_at`; never choose a future row.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit Task 2 files only**

```powershell
git add src/domain/strategy/strategy_context.py src/application/usecases/trade src/infrastructure/market_feature tests/domain/strategy/test_strategy_context.py tests/application/usecases/trade tests/infrastructure/market_feature
git commit -m "Inject market features into scheduler trade contexts"
```

### Task 3: Binance Historical Feature Loader

**Files:**
- Modify: `.gitignore`
- Create: `src/infrastructure/exchange/binance/research_data/historical_feature_loader.py`
- Create: `src/infrastructure/exchange/binance/research_data/__init__.py`
- Create: `scripts/build_binance_feature_cache.py`
- Test: `tests/infrastructure/exchange/test_binance_historical_feature_loader.py`
- Test: `tests/test_build_binance_feature_cache.py`

- [ ] **Step 1: Write failing parser and leakage tests**

```python
def test_kline_row_exposes_taker_flow_without_losing_timestamp():
    row = parse_kline_feature_row(CSV_ROW, symbol="BTCUSDT")
    assert row.features["taker_buy_base_volume"] == Decimal("7")
    assert row.features["taker_sell_base_volume"] == Decimal("3")
    assert row.features["taker_imbalance"] == Decimal("0.4")
    assert row.available_at == row.minute_end


def test_aggtrade_is_assigned_to_minute_only_after_trade_time():
    rows = aggregate_aggtrades([trade_at("00:01:00.001")])
    assert "2026-01-01T00:00:00+00:00" not in rows
```

Also test mark/index/premium alignment, funding publication timestamps, duplicate conflict rejection, and unavailable-source coverage.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\infrastructure\exchange\test_binance_historical_feature_loader.py tests\test_build_binance_feature_cache.py -q`

Expected: import failures for the new loader.

- [ ] **Step 3: Implement archive/API loading and deterministic cache**

Use Binance monthly archive templates:

```python
ARCHIVE_PATHS = {
    "klines": "data/futures/um/monthly/klines/{symbol}/1m/{symbol}-1m-{ym}.zip",
    "aggTrades": "data/futures/um/monthly/aggTrades/{symbol}/{symbol}-aggTrades-{ym}.zip",
    "mark": "data/futures/um/monthly/markPriceKlines/{symbol}/1m/{symbol}-1m-{ym}.zip",
    "index": "data/futures/um/monthly/indexPriceKlines/{symbol}/1m/{symbol}-1m-{ym}.zip",
    "premium": "data/futures/um/monthly/premiumIndexKlines/{symbol}/1m/{symbol}-1m-{ym}.zip",
}
```

Download archives to a temporary file, validate ZIP/CSV structure, aggregate aggTrades while streaming, and persist only compact minute JSONL plus a SHA-256 manifest. Page `/fapi/v1/fundingRate` using `startTime`, `endTime`, and `limit=1000`. Treat HTTP 404 as unavailable source; retry rate limits with the existing Binance REST policy.

Use `.research-data/binance-usdm/raw/{source}/{symbol}` and `.research-data/binance-usdm/features/{symbol}/1m` as canonical ignored caches. Verify Binance `.CHECKSUM` sidecars before atomic rename. Use monthly archives for closed months and daily archive fallback for the current partial month. Month iteration is end-exclusive so monthly and daily rows cannot overlap accidentally.

The base 1m kline already contains trade count and taker-buy volume. Build the first broad matrix from these compact fields plus mark/index/premium/funding. Add raw aggTrades only for the same period when archive size remains within the configured byte budget; export coverage either way.

- [ ] **Step 4: Run parser/cache tests and confirm GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Run a one-day BTC cache smoke test**

Run: `.\.venv\Scripts\python.exe scripts\build_binance_feature_cache.py --symbol BTCUSDT --start 2026-01-01 --end 2026-01-02 --sources klines,mark,index,premium,funding`

Expected: cache JSONL and manifest contain 1m rows with no feature available after its decision minute.

- [ ] **Step 6: Commit Task 3 files only**

```powershell
git add .gitignore src/infrastructure/exchange/binance/research_data scripts/build_binance_feature_cache.py tests/infrastructure/exchange/test_binance_historical_feature_loader.py tests/test_build_binance_feature_cache.py
git commit -m "Add Binance historical research feature loader"
```

### Task 4: New Microstructure and MTF Entry Alpha

**Files:**
- Create: `src/domain/strategy/implementations/microstructure_alpha_strategy.py`
- Modify: `src/domain/strategy/implementations/__init__.py`
- Test: `tests/domain/strategy/test_microstructure_alpha_strategy.py`

- [ ] **Step 1: Write one failing signal test per family**

```python
def test_flow_breakout_requires_price_break_and_positive_aggression():
    context = context_with_features(
        taker_imbalance="0.35",
        cvd_slope="0.20",
        trade_intensity_ratio="1.8",
    )
    assert FlowConfirmedBreakoutStrategy().evaluate(context).signal.direction is SignalDirection.LONG


def test_missing_required_flow_feature_waits_instead_of_using_zero():
    context = context_with_unavailable("aggTrades")
    result = FlowConfirmedBreakoutStrategy().evaluate(context)
    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["missing_source"] == "aggTrades"
```

Cover MTF trend pullback, flow breakout, flow exhaustion, premium/funding reversion, session opening range, and the feature-availability router. Include mirrored long/short cases and incomplete 5m/15m rejection.

- [ ] **Step 2: Run tests and confirm RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\domain\strategy\test_microstructure_alpha_strategy.py -q`

Expected: import failure for the new strategies.

- [ ] **Step 3: Implement six strategies with declared feature requirements**

```python
class FlowConfirmedBreakoutStrategy:
    name = "flow-confirmed-breakout"
    required_features = ("taker_imbalance", "cvd_slope", "trade_intensity_ratio")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        features = _require_features(context, self.required_features)
        if features is None:
            return _wait(self.name, reason="missing_market_features")
        # Price breakout and aggression must agree; no feature substitutes for another.
```

Keep parameters interpretable and bounded. The router delegates to standalone strategies and disables only legs whose required sources are unavailable.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit Task 4 files only**

```powershell
git add src/domain/strategy/implementations/microstructure_alpha_strategy.py src/domain/strategy/implementations/__init__.py tests/domain/strategy/test_microstructure_alpha_strategy.py
git commit -m "Add Binance feature driven entry alpha families"
```

### Task 5: Scheduler Backtest Candidate Matrix

**Files:**
- Modify: `scripts/scheduler_driven_scalping_backtest.py`
- Modify: `scripts/incremental_walk_forward_runner.py`
- Test: `tests/test_scheduler_driven_scalping_backtest.py`
- Test: `tests/test_incremental_walk_forward_runner.py`

- [ ] **Step 1: Write failing matrix and cutoff tests**

```python
def test_microstructure_candidate_universe_is_frozen_at_thirty_six():
    candidates = microstructure_alpha_candidates()
    assert len(candidates) == 36
    assert len({candidate.candidate_id for candidate in candidates}) == 36


def test_backtest_never_exposes_feature_after_cursor_close():
    result = run_scheduler_driven_backtest(
        market,
        start_at=START,
        end_at=END,
        candidate=recording_candidate,
        market_feature_provider=provider_with_row_at(T_PLUS_ONE_US),
    )
    assert result["future_feature_access_count"] == 0
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `.\.venv\Scripts\python.exe -m pytest tests\test_scheduler_driven_scalping_backtest.py tests\test_incremental_walk_forward_runner.py -q`

Expected: missing candidate group/provider arguments.

- [ ] **Step 3: Add the frozen matrix and feature-aware runner**

Create 36 fixed candidates: six families × two signal-strength variants × three shared exit profiles. Do not add a second guard grid. Add `--candidate-group microstructure`, `--feature-cache`, and source-coverage fields. Pass the same in-memory provider through every train/test call.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run the Step 2 command. Expected: all tests pass.

- [ ] **Step 5: Commit Task 5 files only**

```powershell
git add scripts/scheduler_driven_scalping_backtest.py scripts/incremental_walk_forward_runner.py tests/test_scheduler_driven_scalping_backtest.py tests/test_incremental_walk_forward_runner.py
git commit -m "Add feature aware scheduler WFV candidates"
```

### Task 6: Build Data and Run Strict Walk Forward

**Files:**
- Generate: `docs/backtests/cache/binance-features/BTCUSDT/*.jsonl`
- Generate: `docs/backtests/binance-microstructure-*.rows.jsonl`
- Generate: `docs/backtests/binance-microstructure-strict-wfv-2026h1.json`
- Generate: `docs/backtests/binance-microstructure-strict-wfv-2026h1.md`
- Create: `docs/backtests/binance-microstructure-alpha-research-summary.md`

- [ ] **Step 1: Freeze and hash the candidate universe**

Run: `.\.venv\Scripts\python.exe scripts\scheduler_driven_scalping_backtest.py --candidate-group microstructure --list-candidates --manifest-path docs\backtests\binance-microstructure-candidate-manifest.json`

Expected: exactly 36 unique candidates and a SHA-256 manifest written before OOS execution.

- [ ] **Step 2: Build July 2025 through June 2026 BTC feature cache**

Run: `.\.venv\Scripts\python.exe scripts\build_binance_feature_cache.py --symbol BTCUSDT --start 2025-07-01 --end 2026-07-01 --sources klines,mark,index,premium,funding,aggTrades`

Expected: per-source coverage and hashes; unavailable sources explicitly listed.

- [ ] **Step 3: Generate the 12-month candidate matrix in disjoint shards**

Run six family-specific incremental runners in parallel, each writing a separate JSONL. Expected total: `36 candidates × 12 months = 432` unique candidate-month rows.

- [ ] **Step 4: Run strict train-selected WFV**

Run: `.\.venv\Scripts\python.exe scripts\evaluate_train_selected_walk_forward.py --rows-path docs\backtests\binance-microstructure-matrix.rows.jsonl --symbol BTCUSDT --train-months 6 --top-k 3 --min-train-trades 30 --start 2026-01 --end 2026-07 --payload-path docs\backtests\binance-microstructure-strict-wfv-2026h1.json --summary-path docs\backtests\binance-microstructure-strict-wfv-2026h1.md`

Expected: six OOS folds, candidate/source hashes, zero unavailable OOS months, and no test-month selection leakage.

- [ ] **Step 5: Apply promotion gate**

Promote only candidates with positive trade-weighted OOS expectancy, positive compounded OOS return, at least four positive OOS months, and worst monthly drawdown below 15%. If none pass, record rejection and do not mine 2021-2026 for a winner.

- [ ] **Step 6: Run long WFV only for promoted candidates**

For passing candidates, build 2021-2026 features, run monthly WFV, then test neighboring parameter values. If no candidate passes Step 5, mark this step `not applicable` in the summary.

- [ ] **Step 7: Write the result summary**

Record folds, trades/day, win rate, net expectancy, return, MDD, feature coverage, costs, and every excluded Binance source with its reason.

### Task 7: Final Verification

**Files:**
- Verify all files changed by Tasks 1-6

- [ ] **Step 1: Run focused feature and strategy tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\domain\market_feature tests\domain\strategy\test_microstructure_alpha_strategy.py tests\infrastructure\exchange\test_binance_historical_feature_loader.py tests\test_build_binance_feature_cache.py -q`

- [ ] **Step 2: Run scheduler/WFV regression tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests\application\usecases\trade tests\test_scheduler_driven_scalping_backtest.py tests\test_incremental_walk_forward_runner.py tests\test_evaluate_train_selected_walk_forward.py -q`

- [ ] **Step 3: Verify artifact integrity**

Recompute unique candidate-month keys, source hashes, six fold boundaries, selected train windows, and result summaries from raw JSONL. Expected: no duplicates or conflicts.

- [ ] **Step 4: Review the complete diff**

Run: `git diff --check` and inspect `git status --short`. Do not stage or alter unrelated user changes.

---

The live depth/bookTicker/liquidation collector is intentionally a second implementation plan. Those sources cannot improve this historical WFV until authentic event history has been recorded.
