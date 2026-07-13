from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal

from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import StrategyContext
from src.domain.strategy.strategy_result import StrategyResult


@dataclass
class RangeEdgeReversionStrategy:
    name: str = "range-edge-reversion"
    range_period: int = 720
    lower_band: Decimal = Decimal("0.08")
    upper_band: Decimal = Decimal("0.92")
    min_range_width: Decimal = Decimal("0.018")
    reclaim_return: Decimal = Decimal("0.001")
    _window: object = field(default=None, init=False, repr=False)

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        if len(candles) < self.range_period + 2:
            return StrategyResult(name=self.name, signal=Signal.wait())

        latest = candles[-1]
        previous = candles[-2]
        range_low, range_high = self._range(candles)
        if range_low is None or range_high is None:
            return StrategyResult(name=self.name, signal=Signal.wait())
        if range_low <= Decimal("0") or range_high <= range_low:
            return StrategyResult(name=self.name, signal=Signal.wait())

        width_ratio = (range_high - range_low) / range_low
        if width_ratio < self.min_range_width:
            return StrategyResult(name=self.name, signal=Signal.wait())

        range_position = (latest.close_price - range_low) / (range_high - range_low)
        reclaimed_up = latest.close_price >= previous.close_price * (
            Decimal("1") + self.reclaim_return
        )
        reclaimed_down = latest.close_price <= previous.close_price * (
            Decimal("1") - self.reclaim_return
        )

        if range_position <= self.lower_band and reclaimed_up:
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
            )
        if range_position >= self.upper_band and reclaimed_down:
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())

    def _range(self, candles) -> tuple[Decimal | None, Decimal | None]:
        if self._window is None:
            self._window = _RollingRange(self.range_period)
        return self._window.range(candles)


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

        previous = candles[-2]
        self._append(previous)
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
