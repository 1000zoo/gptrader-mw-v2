from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.domain.indicator import IndicatorSet
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.market_feature import (
    MARKET_FEATURES_METADATA_KEY,
    MarketFeatureSet,
    MarketFeatureValue,
)
from src.domain.signal import Signal, SignalDirection, SignalReason
from src.domain.strategy import Strategy, StrategyContext, StrategyResult
from src.domain.strategy.implementations import (
    FlowConfirmedBreakoutStrategy,
    FlowExhaustionReversalStrategy,
    MicrostructureRegimeRouterStrategy,
    MultiTimeframeTrendPullbackStrategy,
    PremiumFundingReversionStrategy,
    SessionOpeningRangeStrategy,
)
from src.domain.strategy.implementations.microstructure_alpha_strategy import (
    _countertrend_pullback_depths,
)


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")
START = datetime(2026, 1, 2, tzinfo=timezone.utc)


def _candle(
    index: int,
    *,
    open_price: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal = Decimal("100"),
) -> Candle:
    opened_at = START + timedelta(minutes=index)
    return Candle(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=1),
        open_price=open_price,
        high_price=high,
        low_price=low,
        close_price=close,
        volume=volume,
    )


def _series(returns: list[Decimal], start: Decimal = Decimal("100")) -> tuple[Candle, ...]:
    candles = []
    price = start
    for index, change in enumerate(returns):
        close = price * (Decimal("1") + change)
        candles.append(
            _candle(
                index,
                open_price=price,
                high=max(price, close) * Decimal("1.0005"),
                low=min(price, close) * Decimal("0.9995"),
                close=close,
            )
        )
        price = close
    return tuple(candles)


def _flat(count: int, price: Decimal = Decimal("100")) -> tuple[Candle, ...]:
    return tuple(
        _candle(
            index,
            open_price=price,
            high=price * Decimal("1.001"),
            low=price * Decimal("0.999"),
            close=price,
        )
        for index in range(count)
    )


def _in_timezone(
    candles: tuple[Candle, ...], offset: timedelta
) -> tuple[Candle, ...]:
    local_timezone = timezone(offset)
    return tuple(
        Candle(
            symbol=candle.symbol,
            timeframe=candle.timeframe,
            opened_at=candle.opened_at.astimezone(local_timezone),
            closed_at=candle.closed_at.astimezone(local_timezone),
            open_price=candle.open_price,
            high_price=candle.high_price,
            low_price=candle.low_price,
            close_price=candle.close_price,
            volume=candle.volume,
        )
        for candle in candles
    )


def _feature(name: str, value: str, source: str, measured_at: datetime) -> MarketFeatureValue:
    return MarketFeatureValue(
        name=name,
        value=Decimal(value),
        source=source,
        observed_at=measured_at,
        available_at=measured_at,
    )


def _context(
    candles: tuple[Candle, ...],
    feature_values: tuple[tuple[str, str, str], ...] = (),
    unavailable_sources: tuple[str, ...] = (),
) -> StrategyContext:
    measured_at = candles[-1].closed_at
    metadata = {}
    if feature_values or unavailable_sources:
        metadata[MARKET_FEATURES_METADATA_KEY] = MarketFeatureSet(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            measured_at=measured_at,
            values=tuple(
                _feature(name, value, source, measured_at)
                for name, value, source in feature_values
            ),
            unavailable_sources=unavailable_sources,
        )
    return StrategyContext(
        market=MarketSnapshot(candles),
        indicators=IndicatorSet(SYMBOL, TIMEFRAME, measured_at, ()),
        metadata=metadata,
    )


FLOW_LONG = (
    ("taker_imbalance", "0.35", "klines"),
    ("cvd_delta", "12", "aggTrades"),
    ("trade_intensity", "180", "aggTrades"),
)
FLOW_SHORT = (
    ("taker_imbalance", "-0.35", "klines"),
    ("cvd_delta", "-12", "aggTrades"),
    ("trade_intensity", "180", "aggTrades"),
)


@pytest.mark.parametrize(
    ("direction", "expected"),
    ((Decimal("1"), SignalDirection.LONG), (Decimal("-1"), SignalDirection.SHORT)),
)
def test_mtf_trend_pullback_emits_mirrored_signals(direction, expected) -> None:
    trend = Decimal("0.001") * direction
    returns = [trend] * 41 + [Decimal("-0.001") * direction] * 3 + [Decimal("0.003") * direction]

    result = MultiTimeframeTrendPullbackStrategy(
        pullback_lookback=5,
        min_15m_trend_return=Decimal("0.001"),
        min_5m_momentum_return=Decimal("0.0001"),
        min_pullback_depth=Decimal("0.0005"),
        min_reclaim_return=Decimal("0.001"),
    ).evaluate(_context(_series(returns)))

    assert result.signal.direction is expected
    assert result.metadata["closed_5m_at"] == "2026-01-02T00:45:00+00:00"
    assert result.metadata["closed_15m_at"] == "2026-01-02T00:45:00+00:00"


def test_mtf_ignores_partial_5m_and_15m_bars() -> None:
    candles = _series(
        [Decimal("0.001")] * 41
        + [Decimal("-0.001")] * 3
        + [Decimal("0.003"), Decimal("0.001"), Decimal("0.001")]
    )

    result = MultiTimeframeTrendPullbackStrategy(
        pullback_lookback=5,
        min_15m_trend_return=Decimal("0.001"),
        min_5m_momentum_return=Decimal("0.0001"),
        min_pullback_depth=Decimal("0"),
        min_reclaim_return=Decimal("0.0001"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.LONG
    assert result.metadata["closed_5m_at"] == "2026-01-02T00:45:00+00:00"
    assert result.metadata["closed_15m_at"] == "2026-01-02T00:45:00+00:00"


def test_mtf_waits_when_required_complete_buckets_have_a_gap() -> None:
    candles = _series(
        [Decimal("0.001")] * 41
        + [Decimal("-0.001")] * 3
        + [Decimal("0.003")]
    )
    candles_with_gap = tuple(
        candle for candle in candles if candle.opened_at != START + timedelta(minutes=20)
    )

    result = MultiTimeframeTrendPullbackStrategy(
        min_15m_trend_return=Decimal("0.001"),
        min_5m_momentum_return=Decimal("0.0001"),
        min_pullback_depth=Decimal("0.0005"),
        min_reclaim_return=Decimal("0.001"),
    ).evaluate(_context(candles_with_gap))

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["reason"] == "stale_or_gapped_higher_timeframe_bars"


@pytest.mark.parametrize("direction", (Decimal("1"), Decimal("-1")))
def test_mtf_monotonic_continuation_is_not_a_pullback(direction) -> None:
    candles = _series([Decimal("0.001") * direction] * 45)

    result = MultiTimeframeTrendPullbackStrategy(
        min_15m_trend_return=Decimal("0.001"),
        min_5m_momentum_return=Decimal("0.0001"),
        min_pullback_depth=Decimal("0"),
        min_reclaim_return=Decimal("0.0001"),
    ).evaluate(_context(candles))

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["reason"] == "conditions_not_met"


def test_pullback_depth_uses_symmetric_price_extreme_denominators() -> None:
    long_anchor = _candle(
        0,
        open_price=Decimal("105"),
        high=Decimal("110"),
        low=Decimal("104"),
        close=Decimal("108"),
    )
    long_pullback = _candle(
        1,
        open_price=Decimal("108"),
        high=Decimal("109"),
        low=Decimal("98"),
        close=Decimal("100"),
    )
    short_anchor = _candle(
        2,
        open_price=Decimal("95"),
        high=Decimal("96"),
        low=Decimal("90"),
        close=Decimal("92"),
    )
    short_pullback = _candle(
        3,
        open_price=Decimal("92"),
        high=Decimal("102"),
        low=Decimal("91"),
        close=Decimal("100"),
    )

    has_long, long_depth, _, _ = _countertrend_pullback_depths(
        (long_anchor, long_pullback)
    )
    _, _, has_short, short_depth = _countertrend_pullback_depths(
        (short_anchor, short_pullback)
    )

    assert has_long is True
    assert long_depth == (Decimal("110") - Decimal("98")) / Decimal("110")
    assert has_short is True
    assert short_depth == (Decimal("102") - Decimal("90")) / Decimal("90")


@pytest.mark.parametrize(
    ("direction", "features", "expected"),
    ((Decimal("1"), FLOW_LONG, SignalDirection.LONG), (Decimal("-1"), FLOW_SHORT, SignalDirection.SHORT)),
)
def test_flow_breakout_emits_mirrored_signals(direction, features, expected) -> None:
    candles = _flat(12)
    latest = _candle(
        12,
        open_price=Decimal("100"),
        high=Decimal("102.2") if direction > 0 else Decimal("100.2"),
        low=Decimal("99.8") if direction > 0 else Decimal("97.8"),
        close=Decimal("102") if direction > 0 else Decimal("98"),
    )

    result = FlowConfirmedBreakoutStrategy(
        range_lookback=10,
        min_taker_imbalance=Decimal("0.2"),
        min_cvd_delta=Decimal("5"),
        min_trade_intensity=Decimal("100"),
    ).evaluate(_context(candles + (latest,), features))

    assert result.signal.direction is expected


def test_flow_breakout_waits_for_missing_required_feature_and_source() -> None:
    result = FlowConfirmedBreakoutStrategy(range_lookback=3).evaluate(
        _context(_flat(5), FLOW_LONG[:1], unavailable_sources=("aggTrades",))
    )

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["missing_features"] == ("cvd_delta", "trade_intensity")
    assert result.metadata["missing_sources"] == ("aggTrades",)


@pytest.mark.parametrize(
    ("long_side", "features", "expected"),
    ((True, FLOW_LONG, SignalDirection.LONG), (False, FLOW_SHORT, SignalDirection.SHORT)),
)
def test_flow_exhaustion_emits_mirrored_reversals(long_side, features, expected) -> None:
    candles = _flat(12)
    latest = _candle(
        12,
        open_price=Decimal("98.5") if long_side else Decimal("101.5"),
        high=Decimal("100.1") if long_side else Decimal("103"),
        low=Decimal("97") if long_side else Decimal("99.9"),
        close=Decimal("99.8") if long_side else Decimal("100.2"),
    )

    result = FlowExhaustionReversalStrategy(
        extreme_lookback=10,
        min_taker_imbalance=Decimal("0.2"),
        min_cvd_delta=Decimal("5"),
        min_rejection_wick_ratio=Decimal("0.3"),
    ).evaluate(_context(candles + (latest,), features))

    assert result.signal.direction is expected


def test_flow_exhaustion_waits_without_current_cvd() -> None:
    result = FlowExhaustionReversalStrategy(extreme_lookback=3).evaluate(
        _context(_flat(5), FLOW_LONG[:1])
    )

    assert result.signal.direction is SignalDirection.WAIT
    assert "cvd_delta" in result.metadata["missing_features"]


@pytest.mark.parametrize(
    ("long_side", "features", "expected"),
    (
        (True, FLOW_LONG + (("premium_index", "-0.0012", "premiumIndexKlines"),), SignalDirection.LONG),
        (False, FLOW_SHORT + (("premium_index", "0.0012", "premiumIndexKlines"),), SignalDirection.SHORT),
    ),
)
def test_premium_reversion_emits_mirrored_signals_without_funding(long_side, features, expected) -> None:
    candles = _flat(4)
    latest = _candle(
        4,
        open_price=Decimal("98.5") if long_side else Decimal("101.5"),
        high=Decimal("100") if long_side else Decimal("102.5"),
        low=Decimal("97.5") if long_side else Decimal("100"),
        close=Decimal("99.8") if long_side else Decimal("100.2"),
    )

    result = PremiumFundingReversionStrategy(
        min_abs_premium=Decimal("0.001"),
        min_rejection_wick_ratio=Decimal("0.25"),
        min_taker_imbalance=Decimal("0.2"),
        min_cvd_delta=Decimal("5"),
    ).evaluate(_context(candles + (latest,), features, unavailable_sources=("fundingRate",)))

    assert result.signal.direction is expected
    assert result.metadata["funding_enhanced"] is False


def test_premium_reversion_can_use_mark_index_basis_and_reports_missing_context() -> None:
    basis_features = FLOW_SHORT + (
        ("mark_price", "101", "markPriceKlines"),
        ("index_price", "100", "indexPriceKlines"),
    )
    candles = _flat(4) + (
        _candle(4, open_price=Decimal("101.5"), high=Decimal("102.5"), low=Decimal("100"), close=Decimal("100.2")),
    )
    strategy = PremiumFundingReversionStrategy(min_abs_basis=Decimal("0.005"))

    assert strategy.evaluate(_context(candles, basis_features)).signal.direction is SignalDirection.SHORT
    missing = strategy.evaluate(_context(candles, FLOW_SHORT)).metadata
    assert set(missing["missing_features"]) == {"premium_index", "mark_price", "index_price"}


@pytest.mark.parametrize(
    ("long_side", "premium", "aligned_funding", "opposing_funding", "expected"),
    (
        (True, "-0.0012", "-0.0002", "0.0002", SignalDirection.LONG),
        (False, "0.0012", "0.0002", "-0.0002", SignalDirection.SHORT),
    ),
)
def test_optional_funding_only_boosts_aligned_reversion(
    long_side, premium, aligned_funding, opposing_funding, expected
) -> None:
    flow = FLOW_LONG if long_side else FLOW_SHORT
    latest = _candle(
        4,
        open_price=Decimal("98.5") if long_side else Decimal("101.5"),
        high=Decimal("100") if long_side else Decimal("102.5"),
        low=Decimal("97.5") if long_side else Decimal("100"),
        close=Decimal("99.8") if long_side else Decimal("100.2"),
    )
    candles = _flat(4) + (latest,)
    strategy = PremiumFundingReversionStrategy(
        min_abs_premium=Decimal("0.001"),
        min_abs_funding=Decimal("0.0001"),
        min_cvd_delta=Decimal("5"),
    )

    aligned = strategy.evaluate(
        _context(
            candles,
            flow
            + (
                ("premium_index", premium, "premiumIndexKlines"),
                ("funding_rate", aligned_funding, "fundingRate"),
            ),
        )
    )
    opposing = strategy.evaluate(
        _context(
            candles,
            flow
            + (
                ("premium_index", premium, "premiumIndexKlines"),
                ("funding_rate", opposing_funding, "fundingRate"),
            ),
        )
    )

    assert aligned.signal.direction is expected
    assert opposing.signal.direction is expected
    assert aligned.metadata["funding_enhanced"] is True
    assert opposing.metadata["funding_enhanced"] is False
    assert aligned.signal.confidence > opposing.signal.confidence


@pytest.mark.parametrize(
    ("long_side", "features", "expected"),
    ((True, FLOW_LONG, SignalDirection.LONG), (False, FLOW_SHORT, SignalDirection.SHORT)),
)
def test_session_opening_range_emits_mirrored_signals(long_side, features, expected) -> None:
    opening_range = _flat(15)
    latest = _candle(
        15,
        open_price=Decimal("100"),
        high=Decimal("101.5") if long_side else Decimal("100.2"),
        low=Decimal("99.8") if long_side else Decimal("98.5"),
        close=Decimal("101.2") if long_side else Decimal("98.8"),
    )

    result = SessionOpeningRangeStrategy(
        opening_range_minutes=15,
        min_mtf_return=Decimal("0.001"),
        min_taker_imbalance=Decimal("0.2"),
        min_cvd_delta=Decimal("5"),
        min_trade_intensity=Decimal("100"),
    ).evaluate(_context(opening_range + (latest,), features))

    assert result.signal.direction is expected
    assert result.metadata["session"] == "asia"
    assert result.metadata["session_open_at"] == "2026-01-02T00:00:00+00:00"


def test_session_opening_range_waits_for_flow_without_using_wall_clock() -> None:
    result = SessionOpeningRangeStrategy(opening_range_minutes=3).evaluate(
        _context(_flat(5), unavailable_sources=("aggTrades",))
    )

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["missing_sources"] == ("aggTrades",)
    assert result.metadata["session"] == "asia"


def test_session_opening_range_waits_when_latest_complete_5m_bucket_is_stale() -> None:
    candles = _flat(20)
    candles = tuple(
        candle for candle in candles if candle.opened_at != START + timedelta(minutes=18)
    ) + (
        _candle(
            20,
            open_price=Decimal("100"),
            high=Decimal("101.5"),
            low=Decimal("99.8"),
            close=Decimal("101.2"),
        ),
    )

    result = SessionOpeningRangeStrategy(
        min_mtf_return=Decimal("0.001"),
        min_cvd_delta=Decimal("5"),
    ).evaluate(_context(candles, FLOW_LONG))

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["reason"] == "stale_or_gapped_higher_timeframe_bars"


@pytest.mark.parametrize("malformation", ("duplicate", "missing", "prior-date"))
def test_session_opening_range_requires_exact_session_minute_opens(malformation) -> None:
    opening = _flat(15)
    if malformation == "duplicate":
        opening = opening[:-1] + (opening[-2],)
    elif malformation == "missing":
        opening = tuple(candle for index, candle in enumerate(opening) if index != 7)
    else:
        prior = opening[0]
        opening = (
            Candle(
                symbol=prior.symbol,
                timeframe=prior.timeframe,
                opened_at=prior.opened_at - timedelta(days=1),
                closed_at=prior.closed_at - timedelta(days=1),
                open_price=prior.open_price,
                high_price=prior.high_price,
                low_price=prior.low_price,
                close_price=prior.close_price,
                volume=prior.volume,
            ),
        ) + opening[1:]
    latest = _candle(
        15,
        open_price=Decimal("100"),
        high=Decimal("101.5"),
        low=Decimal("99.8"),
        close=Decimal("101.2"),
    )

    result = SessionOpeningRangeStrategy(
        min_mtf_return=Decimal("0.001"),
        min_cvd_delta=Decimal("5"),
    ).evaluate(_context(opening + (latest,), FLOW_LONG))

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["reason"] == "opening_range_incomplete"


def test_session_opening_range_uses_utc_for_non_utc_candles() -> None:
    candles = _flat(15) + (
        _candle(
            15,
            open_price=Decimal("100"),
            high=Decimal("101.5"),
            low=Decimal("99.8"),
            close=Decimal("101.2"),
        ),
    )
    kst_candles = _in_timezone(candles, timedelta(hours=9))

    result = SessionOpeningRangeStrategy(
        min_mtf_return=Decimal("0.001"),
        min_cvd_delta=Decimal("5"),
    ).evaluate(_context(kst_candles, FLOW_LONG))

    assert result.signal.direction is SignalDirection.LONG
    assert result.metadata["session"] == "asia"
    assert result.metadata["session_open_at"] == "2026-01-02T00:00:00+00:00"


def test_session_opening_range_accepts_exact_utc_minutes_across_midnight() -> None:
    opening = tuple(
        _candle(
            index,
            open_price=Decimal("100"),
            high=Decimal("100.1"),
            low=Decimal("99.9"),
            close=Decimal("100"),
        )
        for index in range(23 * 60, 24 * 60 + 30)
    )
    latest = _candle(
        24 * 60 + 30,
        open_price=Decimal("100"),
        high=Decimal("101.5"),
        low=Decimal("99.8"),
        close=Decimal("101.2"),
    )

    result = SessionOpeningRangeStrategy(
        opening_range_minutes=90,
        asia_open_minute=60,
        europe_open_minute=7 * 60,
        us_open_minute=23 * 60,
        min_mtf_return=Decimal("0.001"),
        min_cvd_delta=Decimal("5"),
    ).evaluate(_context(opening + (latest,), FLOW_LONG))

    assert result.signal.direction is SignalDirection.LONG
    assert result.metadata["session"] == "us"
    assert result.metadata["session_open_at"] == "2026-01-02T23:00:00+00:00"


@pytest.mark.parametrize(
    "arguments",
    (
        {"opening_range_minutes": 420},
        {"europe_open_minute": 0},
        {
            "europe_open_minute": 13 * 60 + 30,
            "us_open_minute": 7 * 60,
        },
    ),
)
def test_session_opening_range_rejects_crossing_or_unsorted_sessions(arguments) -> None:
    with pytest.raises(ValueError):
        SessionOpeningRangeStrategy(**arguments)


@dataclass(frozen=True)
class _Child:
    name: str
    route: str
    result: StrategyResult

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        return self.result


@dataclass(frozen=True)
class _NamelessChild:
    result: StrategyResult

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        return self.result


def _child(name: str, route: str) -> _Child:
    return _Child(name, route, StrategyResult(name, Signal.wait()))


def test_router_rejects_strategy_child_without_a_name() -> None:
    child = _NamelessChild(StrategyResult("nameless-result", Signal.wait()))

    assert isinstance(child, Strategy)
    with pytest.raises(TypeError, match="name"):
        MicrostructureRegimeRouterStrategy(children=(child,))


@pytest.mark.parametrize(
    ("children", "message"),
    (
        (
            (_Child(" ", "trend", StrategyResult("blank-name", Signal.wait())),),
            "name",
        ),
        ((_child("unknown", "other"),), "route"),
        (
            (
                _child("duplicate-name", "trend"),
                _child(" duplicate-name ", "breakout"),
            ),
            "duplicate",
        ),
    ),
)
def test_router_rejects_invalid_contract_values(children, message) -> None:
    with pytest.raises(ValueError, match=message):
        MicrostructureRegimeRouterStrategy(children=children)


def test_router_default_children_include_all_standalone_families() -> None:
    router = MicrostructureRegimeRouterStrategy()

    assert tuple(type(child) for child in router.children) == (
        MultiTimeframeTrendPullbackStrategy,
        FlowConfirmedBreakoutStrategy,
        SessionOpeningRangeStrategy,
        FlowExhaustionReversalStrategy,
        PremiumFundingReversionStrategy,
    )


def test_router_allows_same_route_and_selects_first_eligible_child() -> None:
    waiting = _Child(
        "waiting-breakout",
        "breakout",
        StrategyResult("waiting-breakout", Signal.wait()),
    )
    first_eligible = _Child(
        "first-breakout",
        "breakout",
        StrategyResult(
            "first-breakout",
            Signal(SignalDirection.LONG, Decimal("0.71")),
        ),
    )
    later_eligible = _Child(
        "later-breakout",
        "breakout",
        StrategyResult(
            "later-breakout",
            Signal(SignalDirection.SHORT, Decimal("0.69")),
        ),
    )

    result = MicrostructureRegimeRouterStrategy(
        children=(waiting, first_eligible, later_eligible),
        regime_lookback=10,
    ).evaluate(_context(_flat(25)))

    assert result.signal.direction is SignalDirection.LONG
    assert result.metadata["route"] == "breakout"
    assert result.metadata["child"] == "first-breakout"


def test_router_falls_through_ineligible_leg_and_returns_route_metadata() -> None:
    missing = _Child(
        "flow-leg",
        "breakout",
        StrategyResult("flow-leg", Signal.wait(), {"missing_sources": ("aggTrades",)}),
    )
    eligible = _Child(
        "price-leg",
        "trend",
        StrategyResult("price-leg", Signal(SignalDirection.LONG, Decimal("0.7"))),
    )
    candles = _series([Decimal("0.001")] * 25)

    result = MicrostructureRegimeRouterStrategy(
        children=(missing, eligible),
        regime_lookback=10,
        trend_threshold=Decimal("0.002"),
    ).evaluate(_context(candles, unavailable_sources=("aggTrades",)))

    assert isinstance(MicrostructureRegimeRouterStrategy(children=(eligible,)), Strategy)
    assert result.signal.direction is SignalDirection.LONG
    assert result.name == "microstructure-regime-router"
    assert result.metadata["route"] == "trend"
    assert result.metadata["child"] == "price-leg"
    assert result.metadata["disabled_legs"] == ("flow-leg",)


def test_router_preserves_child_signal_contract_and_namespaces_result_metadata() -> None:
    reason = SignalReason(
        code="child_reason",
        message="child selected the signal",
        metadata={"evidence": "kept"},
    )
    child_signal = Signal(
        SignalDirection.LONG,
        Decimal("0.73"),
        reasons=(reason,),
        metadata={"route": "child-signal-route", "payload": "kept"},
    )
    child = _Child(
        "contract-child",
        "trend",
        StrategyResult(
            "contract-child",
            child_signal,
            {"route": "child-result-route", "detail": "kept"},
        ),
    )

    result = MicrostructureRegimeRouterStrategy(
        children=(child,),
        regime_lookback=10,
        trend_threshold=Decimal("0.002"),
    ).evaluate(_context(_series([Decimal("0.001")] * 25)))

    assert result.signal.reasons == (reason,)
    assert result.signal.metadata == child_signal.metadata
    assert result.metadata["route"] == "trend"
    assert result.metadata["child_metadata"] == {
        "route": "child-result-route",
        "detail": "kept",
    }


STRATEGY_FACTORIES = (
    MultiTimeframeTrendPullbackStrategy,
    FlowConfirmedBreakoutStrategy,
    FlowExhaustionReversalStrategy,
    PremiumFundingReversionStrategy,
    SessionOpeningRangeStrategy,
    MicrostructureRegimeRouterStrategy,
)


@pytest.mark.parametrize("factory", STRATEGY_FACTORIES)
def test_microstructure_strategies_are_frozen_dataclasses(factory) -> None:
    strategy = factory()

    with pytest.raises(FrozenInstanceError):
        strategy.name = "changed"


@pytest.mark.parametrize("factory", STRATEGY_FACTORIES)
def test_microstructure_strategies_satisfy_strategy_protocol_and_api(factory) -> None:
    strategy = factory()
    context = _context(
        _flat(45),
        FLOW_LONG + (("premium_index", "-0.0012", "premiumIndexKlines"),),
    )

    result = strategy.evaluate(context)

    assert isinstance(strategy, Strategy)
    assert isinstance(result, StrategyResult)
    assert result.name
    assert isinstance(result.signal, Signal)


@pytest.mark.parametrize("factory", STRATEGY_FACTORIES)
def test_microstructure_strategies_are_stateless_across_repeated_evaluation(factory) -> None:
    strategy = factory()
    context = _context(
        _flat(45),
        FLOW_LONG + (("premium_index", "-0.0012", "premiumIndexKlines"),),
    )

    first = strategy.evaluate(context)
    second = strategy.evaluate(context)

    assert second == first


def test_flow_breakout_waits_when_required_features_have_wrong_sources() -> None:
    wrong_sources = tuple((name, value, "wrong-source") for name, value, _ in FLOW_LONG)

    result = FlowConfirmedBreakoutStrategy(range_lookback=3).evaluate(
        _context(_flat(5), wrong_sources)
    )

    assert result.signal.direction is SignalDirection.WAIT
    assert result.metadata["missing_features"] == (
        "taker_imbalance",
        "cvd_delta",
        "trade_intensity",
    )
    assert result.metadata["invalid_feature_sources"] == {
        "taker_imbalance": "wrong-source",
        "cvd_delta": "wrong-source",
        "trade_intensity": "wrong-source",
    }


@pytest.mark.parametrize(
    "factory",
    (
        lambda: MultiTimeframeTrendPullbackStrategy(
            min_15m_trend_return=Decimal("0.999"),
            min_5m_momentum_return=Decimal("0.999"),
            min_pullback_depth=Decimal("0.999"),
            min_reclaim_return=Decimal("0.999"),
            confidence=Decimal("0"),
        ),
        lambda: FlowConfirmedBreakoutStrategy(
            breakout_buffer=Decimal("0.999"),
            min_taker_imbalance=Decimal("1"),
            confidence=Decimal("1"),
        ),
        lambda: FlowExhaustionReversalStrategy(
            min_rejection_wick_ratio=Decimal("0.999"),
            min_taker_imbalance=Decimal("1"),
            confidence=Decimal("1"),
        ),
        lambda: PremiumFundingReversionStrategy(
            min_abs_premium=Decimal("0.999"),
            min_abs_basis=Decimal("0.999"),
            min_abs_funding=Decimal("0.999"),
            min_rejection_wick_ratio=Decimal("0.999"),
            min_taker_imbalance=Decimal("1"),
            confidence=Decimal("1"),
            funding_confidence_boost=Decimal("0"),
        ),
        lambda: SessionOpeningRangeStrategy(
            breakout_buffer=Decimal("0.999"),
            min_mtf_return=Decimal("0.999"),
            min_taker_imbalance=Decimal("1"),
            confidence=Decimal("1"),
        ),
        lambda: MicrostructureRegimeRouterStrategy(
            trend_threshold=Decimal("0.999"),
            volatility_threshold=Decimal("0.999"),
        ),
    ),
)
def test_decimal_validation_accepts_valid_equality_and_near_one_edges(factory) -> None:
    factory()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: MultiTimeframeTrendPullbackStrategy(
            min_15m_trend_return=Decimal("1")
        ),
        lambda: MultiTimeframeTrendPullbackStrategy(
            min_pullback_depth=Decimal("1")
        ),
        lambda: FlowConfirmedBreakoutStrategy(breakout_buffer=Decimal("1")),
        lambda: FlowConfirmedBreakoutStrategy(min_taker_imbalance=Decimal("1.01")),
        lambda: FlowExhaustionReversalStrategy(
            min_rejection_wick_ratio=Decimal("1")
        ),
        lambda: PremiumFundingReversionStrategy(min_abs_premium=Decimal("1")),
        lambda: PremiumFundingReversionStrategy(min_abs_basis=Decimal("1")),
        lambda: PremiumFundingReversionStrategy(min_abs_funding=Decimal("1")),
        lambda: PremiumFundingReversionStrategy(
            min_rejection_wick_ratio=Decimal("1")
        ),
        lambda: SessionOpeningRangeStrategy(breakout_buffer=Decimal("1")),
        lambda: SessionOpeningRangeStrategy(min_mtf_return=Decimal("1")),
        lambda: MicrostructureRegimeRouterStrategy(trend_threshold=Decimal("1")),
        lambda: MicrostructureRegimeRouterStrategy(
            volatility_threshold=Decimal("1")
        ),
    ),
)
def test_decimal_validation_rejects_oversized_ratios(factory) -> None:
    with pytest.raises(ValueError):
        factory()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: MultiTimeframeTrendPullbackStrategy(
            min_5m_momentum_return=Decimal("NaN")
        ),
        lambda: FlowConfirmedBreakoutStrategy(min_cvd_delta=Decimal("Infinity")),
        lambda: FlowExhaustionReversalStrategy(min_cvd_delta=Decimal("NaN")),
        lambda: PremiumFundingReversionStrategy(
            min_abs_funding=Decimal("Infinity")
        ),
        lambda: SessionOpeningRangeStrategy(
            min_trade_intensity=Decimal("NaN")
        ),
        lambda: MicrostructureRegimeRouterStrategy(
            volatility_threshold=Decimal("Infinity")
        ),
    ),
)
def test_decimal_validation_rejects_non_finite_values(factory) -> None:
    with pytest.raises(ValueError):
        factory()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: MultiTimeframeTrendPullbackStrategy(min_pullback_depth=Decimal("-0.1")),
        lambda: FlowConfirmedBreakoutStrategy(range_lookback=1),
        lambda: FlowExhaustionReversalStrategy(min_rejection_wick_ratio=Decimal("1.1")),
        lambda: PremiumFundingReversionStrategy(min_abs_premium=Decimal("0")),
        lambda: SessionOpeningRangeStrategy(opening_range_minutes=0),
        lambda: MicrostructureRegimeRouterStrategy(regime_lookback=1),
        lambda: FlowConfirmedBreakoutStrategy(name=" "),
    ),
)
def test_strategy_parameters_are_strictly_validated(factory) -> None:
    with pytest.raises(ValueError):
        factory()
