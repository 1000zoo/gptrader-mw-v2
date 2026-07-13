from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import StrategyContext
from src.domain.strategy.strategy_result import StrategyResult


@dataclass(frozen=True)
class RegimeRouterScalperStrategy:
    name: str = "regime-router-scalper"
    trend_params: Mapping[str, object] | None = None
    range_params: Mapping[str, object] | None = None
    burst_params: Mapping[str, object] | None = None
    impulse_pullback_params: Mapping[str, object] | None = None
    breakout_retest_params: Mapping[str, object] | None = None
    volatility_expansion_params: Mapping[str, object] | None = None
    liquidity_sweep_params: Mapping[str, object] | None = None
    volume_dryup_breakout_params: Mapping[str, object] | None = None
    three_push_exhaustion_params: Mapping[str, object] | None = None
    router_order: tuple[str, ...] = ("trend", "burst", "range")
    max_abs_trend_for_range: Decimal = Decimal("0.008")
    range_regime_period: int = 240
    trend_regime_period: int = 240

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.range_regime_period, self.trend_regime_period) + 2
        if len(candles) < required:
            return _wait(self.name)

        latest = candles[-1]
        trend_base = candles[-self.trend_regime_period - 1].close_price
        trend = _return_ratio(latest.close_price, trend_base)
        strategies = {
            "trend": TrendPullbackScalper(**dict(self.trend_params or {})),
            "burst": MomentumBurstScalper(**dict(self.burst_params or {})),
            "range": RangeEdgeReversionScalper(**dict(self.range_params or {})),
            "impulse_pullback": ImpulsePullbackContinuationScalper(**dict(self.impulse_pullback_params or {})),
            "breakout_retest": BreakoutRetestContinuationScalper(**dict(self.breakout_retest_params or {})),
            "volatility_expansion": VolatilityExpansionContinuationScalper(**dict(self.volatility_expansion_params or {})),
            "liquidity_sweep": LiquiditySweepReversalScalper(**dict(self.liquidity_sweep_params or {})),
            "volume_dryup_breakout": VolumeDryUpBreakoutScalper(**dict(self.volume_dryup_breakout_params or {})),
            "three_push_exhaustion": ThreePushExhaustionReversalScalper(**dict(self.three_push_exhaustion_params or {})),
        }
        for key in self.router_order:
            if key == "range" and abs(trend) > self.max_abs_trend_for_range:
                continue
            result = strategies[key].evaluate(context)
            if result.signal.direction is not SignalDirection.WAIT:
                return StrategyResult(name=self.name, signal=result.signal)
        return _wait(self.name)


@dataclass(frozen=True)
class TrendPullbackScalper:
    name: str = "trend-pullback-scalper"
    trend_period: int = 60
    pullback_period: int = 5
    trigger_period: int = 1
    min_trend_return: Decimal = Decimal("0.002")
    min_pullback: Decimal = Decimal("0.0006")
    min_trigger_return: Decimal = Decimal("0.0002")
    min_range_ratio: Decimal = Decimal("0.0008")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.trend_period, self.pullback_period, self.trigger_period) + 2
        if len(candles) < required:
            return _wait(self.name)
        latest = candles[-1]
        trend_base = candles[-self.trend_period - 1].close_price
        trigger_base = candles[-self.trigger_period - 1].close_price
        trend_return = _return_ratio(latest.close_price, trend_base)
        trigger_return = _return_ratio(latest.close_price, trigger_base)
        pullback_window = candles[-self.pullback_period - 1 : -1]
        if _range_ratio(pullback_window) < self.min_range_ratio:
            return _wait(self.name)
        high = max(candle.high_price for candle in pullback_window)
        low = min(candle.low_price for candle in pullback_window)

        if trend_return >= self.min_trend_return:
            pullback = (high - latest.close_price) / latest.close_price
            if pullback >= self.min_pullback and trigger_return >= self.min_trigger_return:
                return _signal(self.name, SignalDirection.LONG, Decimal("0.72"))
        if trend_return <= -self.min_trend_return:
            pullback = (latest.close_price - low) / latest.close_price
            if pullback >= self.min_pullback and trigger_return <= -self.min_trigger_return:
                return _signal(self.name, SignalDirection.SHORT, Decimal("0.72"))
        return _wait(self.name)


@dataclass(frozen=True)
class MomentumBurstScalper:
    name: str = "momentum-burst-scalper"
    breakout_period: int = 12
    impulse_period: int = 1
    volume_period: int = 20
    min_impulse_return: Decimal = Decimal("0.0008")
    min_volume_ratio: Decimal = Decimal("1.0")
    breakout_buffer: Decimal = Decimal("0.0000")
    mode: str = "fade"

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.breakout_period, self.impulse_period, self.volume_period) + 2
        if len(candles) < required:
            return _wait(self.name)
        latest = candles[-1]
        prior = candles[-self.breakout_period - 1 : -1]
        high = max(candle.high_price for candle in prior)
        low = min(candle.low_price for candle in prior)
        impulse_base = candles[-self.impulse_period - 1].close_price
        impulse = _return_ratio(latest.close_price, impulse_base)
        average_volume = _average(
            candle.volume for candle in candles[-self.volume_period - 1 : -1]
        )
        volume_ratio = latest.volume / average_volume if average_volume > Decimal("0") else Decimal("0")

        if (
            impulse >= self.min_impulse_return
            and volume_ratio >= self.min_volume_ratio
            and latest.close_price > high * (Decimal("1") + self.breakout_buffer)
        ):
            direction = SignalDirection.SHORT if self.mode == "fade" else SignalDirection.LONG
            return _signal(self.name, direction, Decimal("0.64"))
        if (
            impulse <= -self.min_impulse_return
            and volume_ratio >= self.min_volume_ratio
            and latest.close_price < low * (Decimal("1") - self.breakout_buffer)
        ):
            direction = SignalDirection.LONG if self.mode == "fade" else SignalDirection.SHORT
            return _signal(self.name, direction, Decimal("0.64"))
        return _wait(self.name)


@dataclass(frozen=True)
class RangeEdgeReversionScalper:
    name: str = "range-edge-reversion-scalper"
    range_period: int = 45
    edge_ratio: Decimal = Decimal("0.18")
    min_reversal_body_ratio: Decimal = Decimal("0.15")
    min_range_ratio: Decimal = Decimal("0.0015")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        if len(candles) < self.range_period + 2:
            return _wait(self.name)
        latest = candles[-1]
        window = candles[-self.range_period - 1 : -1]
        low = min(candle.low_price for candle in window)
        high = max(candle.high_price for candle in window)
        width = high - low
        if low <= Decimal("0") or width / low < self.min_range_ratio:
            return _wait(self.name)
        candle_range = latest.high_price - latest.low_price
        if candle_range <= Decimal("0"):
            return _wait(self.name)
        body = latest.close_price - latest.open_price
        body_ratio = abs(body) / candle_range
        close_position = (latest.close_price - low) / width
        if (
            close_position <= self.edge_ratio
            and body > Decimal("0")
            and body_ratio >= self.min_reversal_body_ratio
        ):
            return _signal(self.name, SignalDirection.LONG, Decimal("0.68"))
        if (
            close_position >= Decimal("1") - self.edge_ratio
            and body < Decimal("0")
            and body_ratio >= self.min_reversal_body_ratio
        ):
            return _signal(self.name, SignalDirection.SHORT, Decimal("0.68"))
        return _wait(self.name)


@dataclass(frozen=True)
class ImpulsePullbackContinuationScalper:
    name: str = "impulse-pullback-continuation-scalper"
    impulse_period: int = 1
    pullback_period: int = 4
    trigger_period: int = 1
    min_impulse_return: Decimal = Decimal("0.006")
    min_pullback: Decimal = Decimal("0.002")
    min_resume_return: Decimal = Decimal("0.0015")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = self.impulse_period + self.pullback_period + self.trigger_period + 2
        if len(candles) < required:
            return _wait(self.name)
        impulse = candles[-self.pullback_period - self.trigger_period - 1]
        impulse_base = candles[-self.pullback_period - self.trigger_period - self.impulse_period - 1]
        latest = candles[-1]
        trigger_base = candles[-self.trigger_period - 1]
        impulse_return = _return_ratio(impulse.close_price, impulse_base.close_price)
        resume_return = _return_ratio(latest.close_price, trigger_base.close_price)
        pullback_window = candles[-self.pullback_period - self.trigger_period : -self.trigger_period]

        if impulse_return >= self.min_impulse_return:
            pullback_low = min(candle.low_price for candle in pullback_window)
            pullback = (impulse.close_price - pullback_low) / impulse.close_price
            if pullback >= self.min_pullback and resume_return >= self.min_resume_return:
                return _signal(self.name, SignalDirection.LONG, Decimal("0.70"))
        if impulse_return <= -self.min_impulse_return:
            pullback_high = max(candle.high_price for candle in pullback_window)
            pullback = (pullback_high - impulse.close_price) / impulse.close_price
            if pullback >= self.min_pullback and resume_return <= -self.min_resume_return:
                return _signal(self.name, SignalDirection.SHORT, Decimal("0.70"))
        return _wait(self.name)


@dataclass(frozen=True)
class BreakoutRetestContinuationScalper:
    name: str = "breakout-retest-continuation-scalper"
    breakout_period: int = 60
    retest_period: int = 3
    breakout_buffer: Decimal = Decimal("0.0015")
    retest_tolerance: Decimal = Decimal("0.002")
    min_reclaim_return: Decimal = Decimal("0.001")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = self.breakout_period + self.retest_period + 1
        if len(candles) < required:
            return _wait(self.name)
        base_window = candles[-self.breakout_period - self.retest_period - 1 : -self.retest_period - 1]
        breakout = candles[-self.retest_period - 1]
        retest_window = candles[-self.retest_period : -1]
        latest = candles[-1]
        high = max(candle.high_price for candle in base_window)
        low = min(candle.low_price for candle in base_window)
        if high <= Decimal("0") or low <= Decimal("0"):
            return _wait(self.name)

        reclaimed_up = _return_ratio(latest.close_price, candles[-2].close_price) >= self.min_reclaim_return
        reclaimed_down = _return_ratio(latest.close_price, candles[-2].close_price) <= -self.min_reclaim_return
        if (
            breakout.close_price > high * (Decimal("1") + self.breakout_buffer)
            and min(candle.low_price for candle in retest_window) <= high * (Decimal("1") + self.retest_tolerance)
            and latest.close_price > high
            and reclaimed_up
        ):
            return _signal(self.name, SignalDirection.LONG, Decimal("0.72"))
        if (
            breakout.close_price < low * (Decimal("1") - self.breakout_buffer)
            and max(candle.high_price for candle in retest_window) >= low * (Decimal("1") - self.retest_tolerance)
            and latest.close_price < low
            and reclaimed_down
        ):
            return _signal(self.name, SignalDirection.SHORT, Decimal("0.72"))
        return _wait(self.name)


@dataclass(frozen=True)
class VolatilityExpansionContinuationScalper:
    name: str = "volatility-expansion-continuation-scalper"
    range_period: int = 20
    volume_period: int = 20
    min_range_expansion: Decimal = Decimal("2.0")
    min_volume_ratio: Decimal = Decimal("1.8")
    min_body_ratio: Decimal = Decimal("0.55")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.range_period, self.volume_period) + 2
        if len(candles) < required:
            return _wait(self.name)
        latest = candles[-1]
        range_window = candles[-self.range_period - 1 : -1]
        volume_window = candles[-self.volume_period - 1 : -1]
        average_range = _average(candle.high_price - candle.low_price for candle in range_window)
        average_volume = _average(candle.volume for candle in volume_window)
        latest_range = latest.high_price - latest.low_price
        if average_range <= Decimal("0") or average_volume <= Decimal("0") or latest_range <= Decimal("0"):
            return _wait(self.name)
        body = latest.close_price - latest.open_price
        body_ratio = abs(body) / latest_range
        if latest_range / average_range < self.min_range_expansion:
            return _wait(self.name)
        if latest.volume / average_volume < self.min_volume_ratio:
            return _wait(self.name)
        if body_ratio < self.min_body_ratio:
            return _wait(self.name)
        if body > Decimal("0"):
            return _signal(self.name, SignalDirection.LONG, Decimal("0.66"))
        if body < Decimal("0"):
            return _signal(self.name, SignalDirection.SHORT, Decimal("0.66"))
        return _wait(self.name)


@dataclass(frozen=True)
class LiquiditySweepReversalScalper:
    name: str = "liquidity-sweep-reversal-scalper"
    lookback_period: int = 40
    volume_period: int = 40
    sweep_buffer: Decimal = Decimal("0.0010")
    min_close_reclaim: Decimal = Decimal("0.0005")
    min_wick_ratio: Decimal = Decimal("0.40")
    min_volume_ratio: Decimal = Decimal("1.4")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.lookback_period, self.volume_period) + 2
        if len(candles) < required:
            return _wait(self.name)
        latest = candles[-1]
        prior = candles[-self.lookback_period - 1 : -1]
        low = min(candle.low_price for candle in prior)
        high = max(candle.high_price for candle in prior)
        candle_range = latest.high_price - latest.low_price
        if low <= Decimal("0") or high <= Decimal("0") or candle_range <= Decimal("0"):
            return _wait(self.name)
        average_volume = _average(candle.volume for candle in candles[-self.volume_period - 1 : -1])
        volume_ratio = latest.volume / average_volume if average_volume > Decimal("0") else Decimal("0")
        if volume_ratio < self.min_volume_ratio:
            return _wait(self.name)

        lower_wick_ratio = (min(latest.open_price, latest.close_price) - latest.low_price) / candle_range
        upper_wick_ratio = (latest.high_price - max(latest.open_price, latest.close_price)) / candle_range
        if (
            latest.low_price < low * (Decimal("1") - self.sweep_buffer)
            and latest.close_price > low * (Decimal("1") + self.min_close_reclaim)
            and lower_wick_ratio >= self.min_wick_ratio
        ):
            return _signal(self.name, SignalDirection.LONG, Decimal("0.69"))
        if (
            latest.high_price > high * (Decimal("1") + self.sweep_buffer)
            and latest.close_price < high * (Decimal("1") - self.min_close_reclaim)
            and upper_wick_ratio >= self.min_wick_ratio
        ):
            return _signal(self.name, SignalDirection.SHORT, Decimal("0.69"))
        return _wait(self.name)


@dataclass(frozen=True)
class VolumeDryUpBreakoutScalper:
    name: str = "volume-dryup-breakout-scalper"
    range_period: int = 45
    dryup_period: int = 8
    volume_period: int = 45
    max_dryup_volume_ratio: Decimal = Decimal("0.75")
    min_breakout_volume_ratio: Decimal = Decimal("1.6")
    breakout_buffer: Decimal = Decimal("0.0010")
    min_body_ratio: Decimal = Decimal("0.50")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.range_period, self.volume_period) + self.dryup_period + 2
        if len(candles) < required:
            return _wait(self.name)
        latest = candles[-1]
        range_window = candles[-self.range_period - 1 : -1]
        high = max(candle.high_price for candle in range_window)
        low = min(candle.low_price for candle in range_window)
        average_volume = _average(candle.volume for candle in candles[-self.volume_period - self.dryup_period - 1 : -self.dryup_period - 1])
        dryup_volume = _average(candle.volume for candle in candles[-self.dryup_period - 1 : -1])
        if high <= Decimal("0") or low <= Decimal("0") or average_volume <= Decimal("0"):
            return _wait(self.name)
        if dryup_volume / average_volume > self.max_dryup_volume_ratio:
            return _wait(self.name)
        latest_range = latest.high_price - latest.low_price
        if latest_range <= Decimal("0"):
            return _wait(self.name)
        body = latest.close_price - latest.open_price
        body_ratio = abs(body) / latest_range
        if body_ratio < self.min_body_ratio:
            return _wait(self.name)
        if latest.volume / average_volume < self.min_breakout_volume_ratio:
            return _wait(self.name)
        if latest.close_price > high * (Decimal("1") + self.breakout_buffer) and body > Decimal("0"):
            return _signal(self.name, SignalDirection.LONG, Decimal("0.67"))
        if latest.close_price < low * (Decimal("1") - self.breakout_buffer) and body < Decimal("0"):
            return _signal(self.name, SignalDirection.SHORT, Decimal("0.67"))
        return _wait(self.name)


@dataclass(frozen=True)
class ThreePushExhaustionReversalScalper:
    name: str = "three-push-exhaustion-reversal-scalper"
    trend_period: int = 90
    push_lookback: int = 20
    volume_period: int = 40
    min_trend_return: Decimal = Decimal("0.025")
    min_new_extremes: int = 3
    min_rejection_wick_ratio: Decimal = Decimal("0.50")
    min_volume_ratio: Decimal = Decimal("1.6")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.trend_period, self.push_lookback, self.volume_period) + 2
        if len(candles) < required:
            return _wait(self.name)
        latest = candles[-1]
        trend_base = candles[-self.trend_period - 1].close_price
        trend_return = _return_ratio(latest.close_price, trend_base)
        average_volume = _average(candle.volume for candle in candles[-self.volume_period - 1 : -1])
        if average_volume <= Decimal("0") or latest.volume / average_volume < self.min_volume_ratio:
            return _wait(self.name)
        candle_range = latest.high_price - latest.low_price
        if candle_range <= Decimal("0"):
            return _wait(self.name)
        recent = candles[-self.push_lookback - 1 : -1]
        new_highs = _new_extreme_count((candle.high_price for candle in recent), higher=True)
        new_lows = _new_extreme_count((candle.low_price for candle in recent), higher=False)
        upper_wick_ratio = (latest.high_price - max(latest.open_price, latest.close_price)) / candle_range
        lower_wick_ratio = (min(latest.open_price, latest.close_price) - latest.low_price) / candle_range
        if (
            trend_return >= self.min_trend_return
            and new_highs >= self.min_new_extremes
            and upper_wick_ratio >= self.min_rejection_wick_ratio
        ):
            return _signal(self.name, SignalDirection.SHORT, Decimal("0.66"))
        if (
            trend_return <= -self.min_trend_return
            and new_lows >= self.min_new_extremes
            and lower_wick_ratio >= self.min_rejection_wick_ratio
        ):
            return _signal(self.name, SignalDirection.LONG, Decimal("0.66"))
        return _wait(self.name)


def _signal(name: str, direction: SignalDirection, confidence: Decimal) -> StrategyResult:
    return StrategyResult(name=name, signal=Signal(direction=direction, confidence=confidence))


def _wait(name: str) -> StrategyResult:
    return StrategyResult(name=name, signal=Signal.wait())


def _return_ratio(current: Decimal, base: Decimal) -> Decimal:
    if base <= Decimal("0"):
        return Decimal("0")
    return (current - base) / base


def _range_ratio(candles) -> Decimal:
    candles = tuple(candles)
    if not candles:
        return Decimal("0")
    low = min(candle.low_price for candle in candles)
    high = max(candle.high_price for candle in candles)
    if low <= Decimal("0"):
        return Decimal("0")
    return (high - low) / low


def _average(values) -> Decimal:
    values = tuple(values)
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _new_extreme_count(values, *, higher: bool) -> int:
    values = tuple(values)
    if not values:
        return 0
    count = 0
    extreme = values[0]
    for value in values[1:]:
        if (higher and value > extreme) or (not higher and value < extreme):
            count += 1
            extreme = value
    return count
