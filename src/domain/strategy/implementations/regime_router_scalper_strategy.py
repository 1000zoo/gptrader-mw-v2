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
