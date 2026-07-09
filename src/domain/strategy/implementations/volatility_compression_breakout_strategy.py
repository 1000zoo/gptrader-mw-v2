from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable

from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import StrategyContext
from src.domain.strategy.strategy_result import StrategyResult


@dataclass
class VolatilityCompressionBreakoutStrategy:
    name: str = "volatility-compression-breakout"
    lookback: int = 180
    compression_period: int = 45
    compression_ratio: Decimal = Decimal("0.45")
    breakout_buffer: Decimal = Decimal("0.0006")
    min_volume_ratio: Decimal = Decimal("1.00")
    direction_filter_period: int = 1440
    min_filter_return: Decimal = Decimal("0.002")
    _lookback_range: object = field(default=None, init=False, repr=False)
    _compression_range: object = field(default=None, init=False, repr=False)
    _volume_average: object = field(default=None, init=False, repr=False)

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.lookback, self.direction_filter_period) + 2
        if len(candles) < required:
            return StrategyResult(name=self.name, signal=Signal.wait())

        latest = candles[-1]
        full_low, full_high = self._range("lookback", candles)
        compression_low, compression_high = self._range("compression", candles)
        if full_low is None or compression_low is None:
            return StrategyResult(name=self.name, signal=Signal.wait())

        full_range = _range_ratio(full_low, full_high)
        compression_range = _range_ratio(compression_low, compression_high)
        if full_range <= Decimal("0"):
            return StrategyResult(name=self.name, signal=Signal.wait())
        if compression_range / full_range > self.compression_ratio:
            return StrategyResult(name=self.name, signal=Signal.wait())

        average_volume = self._average_volume(candles)
        if average_volume > Decimal("0") and latest.volume / average_volume < self.min_volume_ratio:
            return StrategyResult(name=self.name, signal=Signal.wait())

        trend_base = candles[-self.direction_filter_period - 1].close_price
        trend_return = (latest.close_price - trend_base) / trend_base
        if (
            trend_return >= self.min_filter_return
            and latest.close_price > full_high * (Decimal("1") + self.breakout_buffer)
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.86")),
            )
        if (
            trend_return <= -self.min_filter_return
            and latest.close_price < full_low * (Decimal("1") - self.breakout_buffer)
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("0.86")),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())

    def _range(self, kind: str, candles):
        attr = "_lookback_range" if kind == "lookback" else "_compression_range"
        period = self.lookback if kind == "lookback" else self.compression_period
        window = getattr(self, attr)
        if window is None:
            window = _RollingRange(period)
            setattr(self, attr, window)
        return window.range(candles)

    def _average_volume(self, candles) -> Decimal:
        if self._volume_average is None:
            self._volume_average = _RollingAverage(self.lookback)
        return self._volume_average.average(candles[-2])


class _RollingRange:
    def __init__(self, period: int) -> None:
        self._period = period
        self._index = 0
        self._last_opened_at = None
        self._highs = deque()
        self._lows = deque()

    def range(self, candles) -> tuple[Decimal | None, Decimal | None]:
        latest = candles[-1]
        if self._last_opened_at == latest.opened_at:
            return self._current_range()
        if self._last_opened_at is not None and latest.opened_at < self._last_opened_at:
            self.__init__(self._period)
        self._append(candles[-2])
        self._last_opened_at = latest.opened_at
        return self._current_range()

    def _append(self, candle) -> None:
        index = self._index
        self._index += 1
        while self._highs and self._highs[-1][1] <= candle.high_price:
            self._highs.pop()
        self._highs.append((index, candle.high_price))
        while self._lows and self._lows[-1][1] >= candle.low_price:
            self._lows.pop()
        self._lows.append((index, candle.low_price))

        earliest = self._index - self._period
        while self._highs and self._highs[0][0] < earliest:
            self._highs.popleft()
        while self._lows and self._lows[0][0] < earliest:
            self._lows.popleft()

    def _current_range(self) -> tuple[Decimal | None, Decimal | None]:
        if self._index < self._period or not self._highs or not self._lows:
            return None, None
        return self._lows[0][1], self._highs[0][1]


class _RollingAverage:
    def __init__(self, period: int) -> None:
        self._period = period
        self._values = deque()
        self._total = Decimal("0")
        self._last_opened_at = None

    def average(self, candle) -> Decimal:
        if self._last_opened_at == candle.opened_at:
            return self._current_average()
        self._last_opened_at = candle.opened_at
        self._values.append(candle.volume)
        self._total += candle.volume
        while len(self._values) > self._period:
            self._total -= self._values.popleft()
        return self._current_average()

    def _current_average(self) -> Decimal:
        if len(self._values) < self._period:
            return Decimal("0")
        return self._total / Decimal(len(self._values))


def _range_ratio(low: Decimal, high: Decimal) -> Decimal:
    if low <= Decimal("0"):
        return Decimal("0")
    return (high - low) / low


def _average(values: Iterable[Decimal]) -> Decimal:
    values = tuple(values)
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))
