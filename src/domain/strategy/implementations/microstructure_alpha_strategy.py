from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import ClassVar, Mapping

from src.domain.market import Candle
from src.domain.market_feature import MarketFeatureSet
from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import Strategy, StrategyContext, StrategyResult


ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class _Bar:
    opened_at: datetime
    closed_at: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal


def _validated_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("name must be a str")
    normalized = value.strip()
    if not normalized:
        raise ValueError("name is required")
    return normalized


def _positive_int(value: int, name: str, *, minimum: int = 1) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} must be an integer greater than or equal to {minimum}")


def _decimal_at_least(value: Decimal, name: str, minimum: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < minimum:
        raise ValueError(f"{name} must be a finite Decimal greater than or equal to {minimum}")


def _ratio(value: Decimal, name: str) -> None:
    _decimal_at_least(value, name, ZERO)
    if value > ONE:
        raise ValueError(f"{name} must be less than or equal to one")


def _percentage(
    value: Decimal,
    name: str,
    *,
    minimum: Decimal = ZERO,
) -> None:
    _decimal_at_least(value, name, minimum)
    if value >= ONE:
        raise ValueError(f"{name} must be less than one")


def _sources(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise TypeError(f"{name} must be a tuple of source names")
    normalized = tuple(source.strip() for source in values)
    if not normalized or any(not source for source in normalized):
        raise ValueError(f"{name} must contain source names")
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} must not contain duplicates")
    return normalized


def _return_ratio(current: Decimal, previous: Decimal) -> Decimal:
    return (current - previous) / previous if previous != ZERO else ZERO


def _wait(name: str, reason: str, **metadata: object) -> StrategyResult:
    details = {"reason": reason, **metadata}
    return StrategyResult(name=name, signal=Signal.wait(details), metadata=details)


def _signal(
    name: str,
    direction: SignalDirection,
    confidence: Decimal,
    metadata: Mapping[str, object],
) -> StrategyResult:
    return StrategyResult(
        name=name,
        signal=Signal(direction=direction, confidence=confidence, metadata=metadata),
        metadata=metadata,
    )


def _feature_metadata(
    features: MarketFeatureSet | None,
    requirements: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, Decimal] | None, dict[str, object]]:
    found: dict[str, Decimal] = {}
    missing = []
    invalid_sources: dict[str, str] = {}
    for name, accepted_sources in requirements.items():
        value = features.get(name) if features is not None else None
        if value is None:
            missing.append(name)
        elif value.source not in accepted_sources:
            missing.append(name)
            invalid_sources[name] = value.source
        else:
            found[name] = value.value

    if not missing:
        return found, {}

    unavailable = set(features.unavailable_sources if features is not None else ())
    missing_sources = tuple(
        source
        for source in dict.fromkeys(
            source
            for name in missing
            for source in requirements[name]
            if source in unavailable
        )
    )
    metadata: dict[str, object] = {
        "missing_features": tuple(missing),
        "missing_sources": missing_sources,
    }
    if len(missing_sources) == 1:
        metadata["missing_source"] = missing_sources[0]
    if invalid_sources:
        metadata["invalid_feature_sources"] = invalid_sources
    return None, metadata


def _require_features(
    context: StrategyContext,
    name: str,
    requirements: Mapping[str, tuple[str, ...]],
) -> tuple[dict[str, Decimal] | None, StrategyResult | None]:
    values, metadata = _feature_metadata(context.market_features, requirements)
    if values is not None:
        return values, None
    return None, _wait(name, "missing_market_features", **metadata)


def _bucket_start(value: datetime, minutes: int) -> datetime:
    utc = value.astimezone(timezone.utc)
    minute_of_day = utc.hour * 60 + utc.minute
    aligned = minute_of_day - minute_of_day % minutes
    return utc.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=aligned)


def _closed_bars(candles: tuple[Candle, ...], minutes: int, as_of: datetime) -> tuple[_Bar, ...]:
    buckets: dict[datetime, list[Candle]] = {}
    for candle in candles:
        start = _bucket_start(candle.opened_at, minutes)
        if start + timedelta(minutes=minutes) <= as_of.astimezone(timezone.utc):
            buckets.setdefault(start, []).append(candle)

    bars = []
    one_minute = timedelta(minutes=1)
    for start, bucket in sorted(buckets.items()):
        expected_opens = tuple(start + index * one_minute for index in range(minutes))
        actual_opens = tuple(candle.opened_at.astimezone(timezone.utc) for candle in bucket)
        if len(bucket) != minutes or actual_opens != expected_opens:
            continue
        if any(candle.closed_at.astimezone(timezone.utc) != expected_opens[index] + one_minute for index, candle in enumerate(bucket)):
            continue
        bars.append(
            _Bar(
                opened_at=start,
                closed_at=start + timedelta(minutes=minutes),
                open_price=bucket[0].open_price,
                high_price=max(candle.high_price for candle in bucket),
                low_price=min(candle.low_price for candle in bucket),
                close_price=bucket[-1].close_price,
                volume=sum((candle.volume for candle in bucket), ZERO),
            )
        )
    return tuple(bars)


def _recent_bars_are_contiguous(
    bars: tuple[_Bar, ...],
    *,
    minutes: int,
    count: int,
    decision_boundary: datetime,
) -> bool:
    if len(bars) < count:
        return False
    interval = timedelta(minutes=minutes)
    expected_latest_close = _bucket_start(decision_boundary, minutes)
    recent = bars[-count:]
    expected_closes = tuple(
        expected_latest_close - interval * offset
        for offset in range(count - 1, -1, -1)
    )
    return tuple(bar.closed_at for bar in recent) == expected_closes


def _rejection_ratios(candle: Candle) -> tuple[Decimal, Decimal]:
    width = candle.high_price - candle.low_price
    if width <= ZERO:
        return ZERO, ZERO
    lower = (min(candle.open_price, candle.close_price) - candle.low_price) / width
    upper = (candle.high_price - max(candle.open_price, candle.close_price)) / width
    return lower, upper


def _countertrend_pullback_depths(
    candles: tuple[Candle, ...],
) -> tuple[bool, Decimal, bool, Decimal]:
    if len(candles) < 2:
        return False, ZERO, False, ZERO

    long_depth = ZERO
    short_depth = ZERO
    for index, anchor in enumerate(candles[:-1]):
        tail = candles[index + 1 :]
        lowest_close = min(candle.close_price for candle in tail)
        if lowest_close < anchor.close_price and anchor.close_price > ZERO:
            lowest_price = min(
                min(candle.close_price, candle.low_price) for candle in tail
            )
            long_depth = max(
                long_depth,
                (anchor.high_price - lowest_price) / anchor.high_price,
            )

        highest_close = max(candle.close_price for candle in tail)
        if highest_close > anchor.close_price and anchor.low_price > ZERO:
            highest_price = max(
                max(candle.close_price, candle.high_price) for candle in tail
            )
            short_depth = max(
                short_depth,
                (highest_price - anchor.low_price) / anchor.low_price,
            )
    has_long_pullback = long_depth > ZERO
    has_short_pullback = short_depth > ZERO
    return has_long_pullback, long_depth, has_short_pullback, short_depth


@dataclass(frozen=True)
class MultiTimeframeTrendPullbackStrategy:
    name: str = "multi-timeframe-trend-pullback"
    trend_bars_15m: int = 2
    momentum_bars_5m: int = 2
    pullback_lookback: int = 3
    min_15m_trend_return: Decimal = Decimal("0.002")
    min_5m_momentum_return: Decimal = Decimal("0.0005")
    min_pullback_depth: Decimal = Decimal("0.0005")
    min_reclaim_return: Decimal = Decimal("0.0002")
    confidence: Decimal = Decimal("0.72")
    route: ClassVar[str] = "trend"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _validated_name(self.name))
        _positive_int(self.trend_bars_15m, "trend_bars_15m", minimum=2)
        _positive_int(self.momentum_bars_5m, "momentum_bars_5m", minimum=2)
        _positive_int(self.pullback_lookback, "pullback_lookback", minimum=2)
        for field in (
            "min_15m_trend_return",
            "min_5m_momentum_return",
            "min_pullback_depth",
            "min_reclaim_return",
        ):
            _percentage(getattr(self, field), field)
        _ratio(self.confidence, "confidence")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        if context.market.timeframe.duration_seconds != 60:
            return _wait(self.name, "requires_1m_candles")
        bars_5m = _closed_bars(candles, 5, candles[-1].closed_at)
        bars_15m = _closed_bars(candles, 15, candles[-1].closed_at)
        metadata: dict[str, object] = {
            "closed_5m_at": bars_5m[-1].closed_at.isoformat() if bars_5m else None,
            "closed_15m_at": bars_15m[-1].closed_at.isoformat() if bars_15m else None,
        }
        if len(bars_5m) < self.momentum_bars_5m or len(bars_15m) < self.trend_bars_15m:
            return _wait(self.name, "insufficient_closed_higher_timeframe_bars", **metadata)
        if not _recent_bars_are_contiguous(
            bars_5m,
            minutes=5,
            count=self.momentum_bars_5m,
            decision_boundary=candles[-1].closed_at,
        ) or not _recent_bars_are_contiguous(
            bars_15m,
            minutes=15,
            count=self.trend_bars_15m,
            decision_boundary=candles[-1].closed_at,
        ):
            return _wait(
                self.name,
                "stale_or_gapped_higher_timeframe_bars",
                **metadata,
            )
        if len(candles) < self.pullback_lookback + 1:
            return _wait(self.name, "insufficient_pullback_candles", **metadata)

        trend = _return_ratio(
            bars_15m[-1].close_price,
            bars_15m[-self.trend_bars_15m].close_price,
        )
        momentum = _return_ratio(
            bars_5m[-1].close_price,
            bars_5m[-self.momentum_bars_5m].close_price,
        )
        latest = candles[-1]
        prior = candles[-self.pullback_lookback - 1 : -1]
        (
            has_long_pullback,
            long_depth,
            has_short_pullback,
            short_depth,
        ) = _countertrend_pullback_depths(prior)
        reclaim = _return_ratio(latest.close_price, candles[-2].close_price)
        metadata.update(
            {
                "trend_15m": str(trend),
                "momentum_5m": str(momentum),
                "long_pullback_depth": str(long_depth),
                "short_pullback_depth": str(short_depth),
                "reclaim_1m": str(reclaim),
            }
        )
        if (
            trend >= self.min_15m_trend_return
            and momentum >= self.min_5m_momentum_return
            and has_long_pullback
            and long_depth >= self.min_pullback_depth
            and reclaim >= self.min_reclaim_return
            and latest.close_price > latest.open_price
        ):
            return _signal(self.name, SignalDirection.LONG, self.confidence, metadata)
        if (
            trend <= -self.min_15m_trend_return
            and momentum <= -self.min_5m_momentum_return
            and has_short_pullback
            and short_depth >= self.min_pullback_depth
            and reclaim <= -self.min_reclaim_return
            and latest.close_price < latest.open_price
        ):
            return _signal(self.name, SignalDirection.SHORT, self.confidence, metadata)
        return _wait(self.name, "conditions_not_met", **metadata)


@dataclass(frozen=True)
class FlowConfirmedBreakoutStrategy:
    name: str = "flow-confirmed-breakout"
    range_lookback: int = 20
    breakout_buffer: Decimal = Decimal("0")
    min_taker_imbalance: Decimal = Decimal("0.20")
    min_cvd_delta: Decimal = Decimal("0")
    min_trade_intensity: Decimal = Decimal("100")
    taker_imbalance_sources: tuple[str, ...] = ("klines", "aggTrades")
    cvd_delta_sources: tuple[str, ...] = ("aggTrades",)
    trade_intensity_sources: tuple[str, ...] = ("aggTrades",)
    confidence: Decimal = Decimal("0.70")
    route: ClassVar[str] = "breakout"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _validated_name(self.name))
        _positive_int(self.range_lookback, "range_lookback", minimum=2)
        _percentage(self.breakout_buffer, "breakout_buffer")
        for field in ("min_taker_imbalance", "min_cvd_delta", "min_trade_intensity"):
            _decimal_at_least(getattr(self, field), field, ZERO)
        _ratio(self.min_taker_imbalance, "min_taker_imbalance")
        _ratio(self.confidence, "confidence")
        for field in ("taker_imbalance_sources", "cvd_delta_sources", "trade_intensity_sources"):
            object.__setattr__(self, field, _sources(getattr(self, field), field))

    @property
    def required_features(self) -> Mapping[str, tuple[str, ...]]:
        return {
            "taker_imbalance": self.taker_imbalance_sources,
            "cvd_delta": self.cvd_delta_sources,
            "trade_intensity": self.trade_intensity_sources,
        }

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        values, wait = _require_features(context, self.name, self.required_features)
        if wait is not None:
            return wait
        candles = context.market.candles
        if len(candles) < self.range_lookback + 1:
            return _wait(self.name, "insufficient_candles")
        latest = candles[-1]
        prior = candles[-self.range_lookback - 1 : -1]
        high = max(candle.high_price for candle in prior)
        low = min(candle.low_price for candle in prior)
        metadata = {"range_high": str(high), "range_low": str(low), "flow_sources": tuple(sorted({context.market_features.require(key).source for key in self.required_features}))}
        assert values is not None
        if (
            latest.close_price > high * (ONE + self.breakout_buffer)
            and values["taker_imbalance"] >= self.min_taker_imbalance
            and values["cvd_delta"] >= self.min_cvd_delta
            and values["trade_intensity"] >= self.min_trade_intensity
        ):
            return _signal(self.name, SignalDirection.LONG, self.confidence, metadata)
        if (
            latest.close_price < low * (ONE - self.breakout_buffer)
            and values["taker_imbalance"] <= -self.min_taker_imbalance
            and values["cvd_delta"] <= -self.min_cvd_delta
            and values["trade_intensity"] >= self.min_trade_intensity
        ):
            return _signal(self.name, SignalDirection.SHORT, self.confidence, metadata)
        return _wait(self.name, "conditions_not_met", **metadata)


@dataclass(frozen=True)
class FlowExhaustionReversalStrategy:
    name: str = "flow-exhaustion-reversal"
    extreme_lookback: int = 20
    min_rejection_wick_ratio: Decimal = Decimal("0.35")
    min_taker_imbalance: Decimal = Decimal("0.15")
    min_cvd_delta: Decimal = Decimal("0")
    taker_imbalance_sources: tuple[str, ...] = ("klines", "aggTrades")
    cvd_delta_sources: tuple[str, ...] = ("aggTrades",)
    confidence: Decimal = Decimal("0.68")
    route: ClassVar[str] = "reversion"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _validated_name(self.name))
        _positive_int(self.extreme_lookback, "extreme_lookback", minimum=2)
        _percentage(self.min_rejection_wick_ratio, "min_rejection_wick_ratio")
        _ratio(self.min_taker_imbalance, "min_taker_imbalance")
        _decimal_at_least(self.min_cvd_delta, "min_cvd_delta", ZERO)
        _ratio(self.confidence, "confidence")
        object.__setattr__(self, "taker_imbalance_sources", _sources(self.taker_imbalance_sources, "taker_imbalance_sources"))
        object.__setattr__(self, "cvd_delta_sources", _sources(self.cvd_delta_sources, "cvd_delta_sources"))

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        requirements = {
            "taker_imbalance": self.taker_imbalance_sources,
            "cvd_delta": self.cvd_delta_sources,
        }
        values, wait = _require_features(context, self.name, requirements)
        if wait is not None:
            return wait
        candles = context.market.candles
        if len(candles) < self.extreme_lookback + 1:
            return _wait(self.name, "insufficient_candles")
        latest = candles[-1]
        prior = candles[-self.extreme_lookback - 1 : -1]
        prior_high = max(candle.high_price for candle in prior)
        prior_low = min(candle.low_price for candle in prior)
        lower_wick, upper_wick = _rejection_ratios(latest)
        metadata = {
            "prior_high": str(prior_high),
            "prior_low": str(prior_low),
            "lower_wick_ratio": str(lower_wick),
            "upper_wick_ratio": str(upper_wick),
        }
        assert values is not None
        if (
            latest.low_price < prior_low
            and latest.close_price > latest.open_price
            and lower_wick >= self.min_rejection_wick_ratio
            and values["taker_imbalance"] >= self.min_taker_imbalance
            and values["cvd_delta"] >= self.min_cvd_delta
        ):
            return _signal(self.name, SignalDirection.LONG, self.confidence, metadata)
        if (
            latest.high_price > prior_high
            and latest.close_price < latest.open_price
            and upper_wick >= self.min_rejection_wick_ratio
            and values["taker_imbalance"] <= -self.min_taker_imbalance
            and values["cvd_delta"] <= -self.min_cvd_delta
        ):
            return _signal(self.name, SignalDirection.SHORT, self.confidence, metadata)
        return _wait(self.name, "conditions_not_met", **metadata)


@dataclass(frozen=True)
class PremiumFundingReversionStrategy:
    name: str = "premium-funding-reversion"
    min_abs_premium: Decimal = Decimal("0.0008")
    min_abs_basis: Decimal = Decimal("0.0008")
    min_abs_funding: Decimal = Decimal("0.0001")
    min_rejection_wick_ratio: Decimal = Decimal("0.25")
    min_taker_imbalance: Decimal = Decimal("0.15")
    min_cvd_delta: Decimal = Decimal("0")
    premium_sources: tuple[str, ...] = ("premiumIndexKlines",)
    mark_sources: tuple[str, ...] = ("markPriceKlines",)
    index_sources: tuple[str, ...] = ("indexPriceKlines",)
    funding_sources: tuple[str, ...] = ("fundingRate",)
    taker_imbalance_sources: tuple[str, ...] = ("klines", "aggTrades")
    cvd_delta_sources: tuple[str, ...] = ("aggTrades",)
    confidence: Decimal = Decimal("0.70")
    funding_confidence_boost: Decimal = Decimal("0.05")
    route: ClassVar[str] = "reversion"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _validated_name(self.name))
        for field in ("min_abs_premium", "min_abs_basis", "min_abs_funding"):
            _percentage(
                getattr(self, field),
                field,
                minimum=Decimal("0.000000000000000001"),
            )
        _percentage(self.min_rejection_wick_ratio, "min_rejection_wick_ratio")
        _ratio(self.min_taker_imbalance, "min_taker_imbalance")
        _decimal_at_least(self.min_cvd_delta, "min_cvd_delta", ZERO)
        _ratio(self.confidence, "confidence")
        _ratio(self.funding_confidence_boost, "funding_confidence_boost")
        if self.confidence + self.funding_confidence_boost > ONE:
            raise ValueError("confidence plus funding_confidence_boost must not exceed one")
        for field in ("premium_sources", "mark_sources", "index_sources", "funding_sources", "taker_imbalance_sources", "cvd_delta_sources"):
            object.__setattr__(self, field, _sources(getattr(self, field), field))

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        flow_requirements = {
            "taker_imbalance": self.taker_imbalance_sources,
            "cvd_delta": self.cvd_delta_sources,
        }
        flow, wait = _require_features(context, self.name, flow_requirements)
        if wait is not None:
            return wait
        features = context.market_features
        assert features is not None and flow is not None
        premium_row = features.get("premium_index")
        premium = premium_row.value if premium_row is not None and premium_row.source in self.premium_sources else None
        mark_row = features.get("mark_price")
        index_row = features.get("index_price")
        basis = None
        if (
            mark_row is not None
            and index_row is not None
            and mark_row.source in self.mark_sources
            and index_row.source in self.index_sources
            and index_row.value != ZERO
        ):
            basis = (mark_row.value - index_row.value) / index_row.value
        if premium is None and basis is None:
            missing = tuple(
                name
                for name, present in (
                    ("premium_index", premium_row is not None and premium_row.source in self.premium_sources),
                    ("mark_price", mark_row is not None and mark_row.source in self.mark_sources),
                    ("index_price", index_row is not None and index_row.source in self.index_sources),
                )
                if not present
            )
            requirements = {
                "premium_index": self.premium_sources,
                "mark_price": self.mark_sources,
                "index_price": self.index_sources,
            }
            _, source_metadata = _feature_metadata(features, requirements)
            source_metadata["missing_features"] = missing
            return _wait(self.name, "missing_premium_or_basis", **source_metadata)

        extreme = premium if premium is not None and abs(premium) >= self.min_abs_premium else None
        context_kind = "premium"
        if extreme is None and basis is not None and abs(basis) >= self.min_abs_basis:
            extreme = basis
            context_kind = "basis"
        if extreme is None:
            return _wait(self.name, "premium_or_basis_not_extreme")

        funding_row = features.get("funding_rate")
        funding = funding_row.value if funding_row is not None and funding_row.source in self.funding_sources else None
        funding_enhanced = funding is not None and abs(funding) >= self.min_abs_funding and funding * extreme > ZERO
        latest = context.market.latest_candle
        lower_wick, upper_wick = _rejection_ratios(latest)
        metadata = {
            "context": context_kind,
            "extreme_value": str(extreme),
            "funding_enhanced": funding_enhanced,
        }
        confidence = self.confidence + (self.funding_confidence_boost if funding_enhanced else ZERO)
        if (
            extreme <= -self.min_abs_premium if context_kind == "premium" else extreme <= -self.min_abs_basis
        ) and latest.close_price > latest.open_price and lower_wick >= self.min_rejection_wick_ratio and flow["taker_imbalance"] >= self.min_taker_imbalance and flow["cvd_delta"] >= self.min_cvd_delta:
            return _signal(self.name, SignalDirection.LONG, confidence, metadata)
        if (
            extreme >= self.min_abs_premium if context_kind == "premium" else extreme >= self.min_abs_basis
        ) and latest.close_price < latest.open_price and upper_wick >= self.min_rejection_wick_ratio and flow["taker_imbalance"] <= -self.min_taker_imbalance and flow["cvd_delta"] <= -self.min_cvd_delta:
            return _signal(self.name, SignalDirection.SHORT, confidence, metadata)
        return _wait(self.name, "conditions_not_met", **metadata)


@dataclass(frozen=True)
class SessionOpeningRangeStrategy:
    name: str = "session-opening-range"
    opening_range_minutes: int = 15
    asia_open_minute: int = 0
    europe_open_minute: int = 7 * 60
    us_open_minute: int = 13 * 60 + 30
    breakout_buffer: Decimal = Decimal("0")
    min_mtf_return: Decimal = Decimal("0.0005")
    min_taker_imbalance: Decimal = Decimal("0.15")
    min_cvd_delta: Decimal = Decimal("0")
    min_trade_intensity: Decimal = Decimal("100")
    taker_imbalance_sources: tuple[str, ...] = ("klines", "aggTrades")
    cvd_delta_sources: tuple[str, ...] = ("aggTrades",)
    trade_intensity_sources: tuple[str, ...] = ("aggTrades",)
    confidence: Decimal = Decimal("0.69")
    route: ClassVar[str] = "breakout"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _validated_name(self.name))
        _positive_int(self.opening_range_minutes, "opening_range_minutes")
        for field in ("asia_open_minute", "europe_open_minute", "us_open_minute"):
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < 1440:
                raise ValueError(f"{field} must be a UTC minute of day")
        session_starts = (
            self.asia_open_minute,
            self.europe_open_minute,
            self.us_open_minute,
        )
        if len(set(session_starts)) != len(session_starts):
            raise ValueError("session open minutes must be distinct")
        if session_starts != tuple(sorted(session_starts)):
            raise ValueError("session open minutes must be ordered Asia, Europe, US")
        session_gaps = (
            self.europe_open_minute - self.asia_open_minute,
            self.us_open_minute - self.europe_open_minute,
            1440 - self.us_open_minute + self.asia_open_minute,
        )
        if self.opening_range_minutes >= min(session_gaps):
            raise ValueError("opening_range_minutes must end before the next UTC session")
        _percentage(self.breakout_buffer, "breakout_buffer")
        _percentage(self.min_mtf_return, "min_mtf_return")
        for field in ("min_taker_imbalance", "min_cvd_delta", "min_trade_intensity"):
            _decimal_at_least(getattr(self, field), field, ZERO)
        _ratio(self.min_taker_imbalance, "min_taker_imbalance")
        _ratio(self.confidence, "confidence")
        for field in ("taker_imbalance_sources", "cvd_delta_sources", "trade_intensity_sources"):
            object.__setattr__(self, field, _sources(getattr(self, field), field))

    def _session(self, at: datetime) -> tuple[str, datetime]:
        utc = at.astimezone(timezone.utc)
        midnight = utc.replace(hour=0, minute=0, second=0, microsecond=0)
        candidates = []
        for day in (midnight - timedelta(days=1), midnight):
            candidates.extend(
                (day + timedelta(minutes=minute), name)
                for name, minute in (
                    ("asia", self.asia_open_minute),
                    ("europe", self.europe_open_minute),
                    ("us", self.us_open_minute),
                )
            )
        start, name = max((item for item in candidates if item[0] <= utc), key=lambda item: item[0])
        return name, start

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        latest = context.market.latest_candle
        session, session_start = self._session(latest.opened_at)
        session_metadata = {"session": session, "session_open_at": session_start.isoformat()}
        requirements = {
            "taker_imbalance": self.taker_imbalance_sources,
            "cvd_delta": self.cvd_delta_sources,
            "trade_intensity": self.trade_intensity_sources,
        }
        flow, wait = _require_features(context, self.name, requirements)
        if wait is not None:
            missing_metadata = {
                key: value for key, value in wait.metadata.items() if key != "reason"
            }
            return _wait(
                self.name,
                "missing_market_features",
                **session_metadata,
                **missing_metadata,
            )
        range_end = session_start + timedelta(minutes=self.opening_range_minutes)
        opening = tuple(
            candle
            for candle in context.market.candles
            if session_start <= candle.opened_at.astimezone(timezone.utc) < range_end
            and candle.closed_at.astimezone(timezone.utc) <= range_end
        )
        expected_opens = tuple(
            session_start + timedelta(minutes=index)
            for index in range(self.opening_range_minutes)
        )
        actual_opens = tuple(
            candle.opened_at.astimezone(timezone.utc) for candle in opening
        )
        if (
            latest.opened_at.astimezone(timezone.utc) < range_end
            or actual_opens != expected_opens
        ):
            return _wait(self.name, "opening_range_incomplete", **session_metadata)
        bars_5m = _closed_bars(context.market.candles, 5, latest.closed_at)
        eligible_5m = tuple(bar for bar in bars_5m if bar.closed_at <= latest.opened_at.astimezone(timezone.utc))
        if not eligible_5m:
            return _wait(self.name, "missing_closed_5m_confirmation", **session_metadata)
        if not _recent_bars_are_contiguous(
            eligible_5m,
            minutes=5,
            count=1,
            decision_boundary=latest.opened_at,
        ):
            return _wait(
                self.name,
                "stale_or_gapped_higher_timeframe_bars",
                **session_metadata,
            )
        reference = eligible_5m[-1].close_price
        mtf_return = _return_ratio(latest.close_price, reference)
        high = max(candle.high_price for candle in opening)
        low = min(candle.low_price for candle in opening)
        metadata = {
            **session_metadata,
            "range_high": str(high),
            "range_low": str(low),
            "closed_5m_at": eligible_5m[-1].closed_at.isoformat(),
            "mtf_return": str(mtf_return),
        }
        assert flow is not None
        if (
            latest.close_price > high * (ONE + self.breakout_buffer)
            and mtf_return >= self.min_mtf_return
            and flow["taker_imbalance"] >= self.min_taker_imbalance
            and flow["cvd_delta"] >= self.min_cvd_delta
            and flow["trade_intensity"] >= self.min_trade_intensity
        ):
            return _signal(self.name, SignalDirection.LONG, self.confidence, metadata)
        if (
            latest.close_price < low * (ONE - self.breakout_buffer)
            and mtf_return <= -self.min_mtf_return
            and flow["taker_imbalance"] <= -self.min_taker_imbalance
            and flow["cvd_delta"] <= -self.min_cvd_delta
            and flow["trade_intensity"] >= self.min_trade_intensity
        ):
            return _signal(self.name, SignalDirection.SHORT, self.confidence, metadata)
        return _wait(self.name, "conditions_not_met", **metadata)


@dataclass(frozen=True)
class MicrostructureRegimeRouterStrategy:
    name: str = "microstructure-regime-router"
    children: tuple[Strategy, ...] = ()
    regime_lookback: int = 20
    trend_threshold: Decimal = Decimal("0.004")
    volatility_threshold: Decimal = Decimal("0.003")
    _routed_children: tuple[tuple[str, str, Strategy], ...] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _ROUTES: ClassVar[tuple[str, ...]] = ("trend", "breakout", "reversion")

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _validated_name(self.name))
        _positive_int(self.regime_lookback, "regime_lookback", minimum=2)
        _percentage(self.trend_threshold, "trend_threshold")
        _percentage(self.volatility_threshold, "volatility_threshold")
        children = tuple(self.children)
        if not children:
            children = (
                MultiTimeframeTrendPullbackStrategy(),
                FlowConfirmedBreakoutStrategy(),
                SessionOpeningRangeStrategy(),
                FlowExhaustionReversalStrategy(),
                PremiumFundingReversionStrategy(),
            )
        routed_children = []
        seen_names = set()
        for child in children:
            if not isinstance(child, Strategy):
                raise TypeError("children must contain Strategy-compatible objects")
            if not hasattr(child, "name"):
                raise TypeError("each child must define a name")
            child_name = getattr(child, "name")
            if not isinstance(child_name, str):
                raise TypeError("child name must be a str")
            child_name = child_name.strip()
            if not child_name:
                raise ValueError("child name is required")
            if child_name in seen_names:
                raise ValueError(f"duplicate child name: {child_name}")
            seen_names.add(child_name)
            if not hasattr(child, "route"):
                raise TypeError("each child must define a route")
            route = getattr(child, "route")
            if not isinstance(route, str):
                raise TypeError("child route must be a str")
            route = route.strip()
            if route not in self._ROUTES:
                raise ValueError(f"unknown child route: {route}")
            routed_children.append((route, child_name, child))
        object.__setattr__(self, "children", children)
        object.__setattr__(self, "_routed_children", tuple(routed_children))

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        if len(candles) < self.regime_lookback + 1:
            return _wait(self.name, "insufficient_regime_candles")
        window = candles[-self.regime_lookback :]
        trend = _return_ratio(candles[-1].close_price, candles[-self.regime_lookback - 1].close_price)
        volatility = sum(
            ((candle.high_price - candle.low_price) / candle.close_price for candle in window if candle.close_price > ZERO),
            ZERO,
        ) / Decimal(len(window))
        if abs(trend) >= self.trend_threshold:
            regime = "trend"
            route_order = ("trend", "breakout", "reversion")
        elif volatility >= self.volatility_threshold:
            regime = "volatile"
            route_order = ("breakout", "reversion", "trend")
        else:
            regime = "quiet"
            route_order = ("reversion", "breakout", "trend")

        evaluated = []
        for route, child_name, child in self._routed_children:
            result = child.evaluate(context)
            if not isinstance(result, StrategyResult):
                raise TypeError(
                    f"child {child_name} evaluate() must return StrategyResult"
                )
            evaluated.append((route, child_name, result))
        disabled = tuple(
            child_name
            for _, child_name, result in evaluated
            if result.signal.direction is SignalDirection.WAIT
            and (result.metadata.get("missing_features") or result.metadata.get("missing_sources"))
        )
        for route in route_order:
            for child_route, _, result in evaluated:
                if child_route != route or result.signal.direction is SignalDirection.WAIT:
                    continue
                metadata = {
                    "regime": regime,
                    "route": route,
                    "child": result.name,
                    "disabled_legs": disabled,
                    "trend": str(trend),
                    "volatility": str(volatility),
                    "child_metadata": dict(result.metadata),
                }
                delegated_signal = Signal(
                    direction=result.signal.direction,
                    confidence=result.signal.confidence,
                    reasons=result.signal.reasons,
                    metadata=result.signal.metadata,
                )
                return StrategyResult(
                    name=self.name,
                    signal=delegated_signal,
                    metadata=metadata,
                )
        return _wait(
            self.name,
            "no_eligible_child_signal",
            regime=regime,
            disabled_legs=disabled,
            trend=str(trend),
            volatility=str(volatility),
        )


__all__ = [
    "FlowConfirmedBreakoutStrategy",
    "FlowExhaustionReversalStrategy",
    "MicrostructureRegimeRouterStrategy",
    "MultiTimeframeTrendPullbackStrategy",
    "PremiumFundingReversionStrategy",
    "SessionOpeningRangeStrategy",
]
