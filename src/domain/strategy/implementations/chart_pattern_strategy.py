from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Literal

from src.domain.market import Candle
from src.domain.signal import Signal, SignalDirection, SignalReason
from src.domain.strategy import StrategyContext, StrategyResult


PatternName = Literal[
    "ascending_triangle",
    "descending_triangle",
    "symmetrical_triangle",
    "box_range",
    "double_top",
    "double_bottom",
    "triple_top",
    "triple_bottom",
    "head_and_shoulders",
    "inverse_head_and_shoulders",
    "falling_wedge",
    "rising_wedge",
]
PatternSignal = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class Pivot:
    index: int
    price: Decimal


@dataclass(frozen=True)
class PatternCandidate:
    pattern: PatternName
    signal: PatternSignal
    confidence: Decimal
    reason: str
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    structure_clear: bool
    breakout: bool
    breakdown: bool
    volume_confirmed: bool
    pivot_count: int
    direction_matches_trend: bool
    width_ratio: Decimal
    volatility_ratio: Decimal


@dataclass(frozen=True)
class ChartPatternStrategy:
    name: str = "chart-pattern"
    lookback: int = 120
    pivot_window: int = 3
    price_tolerance: Decimal = Decimal("0.01")
    breakout_buffer: Decimal = Decimal("0.003")
    volume_ma_period: int = 20
    volume_multiplier: Decimal = Decimal("1.3")
    min_confidence: Decimal = Decimal("0.6")
    risk_reward_ratio: Decimal = Decimal("2.0")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = tuple(context.market.candles[-self.lookback :])
        if len(candles) < (self.pivot_window * 2) + 3:
            return self._hold("insufficient candles", None)

        pivot_highs = PivotDetector.find_pivot_highs(candles, self.pivot_window)
        pivot_lows = PivotDetector.find_pivot_lows(candles, self.pivot_window)
        detector = PatternDetector(self, candles, pivot_highs, pivot_lows)
        candidates = detector.detect_all()
        if not candidates:
            return self._hold("no chart pattern satisfied numeric conditions", None)

        candidate = _select_candidate(candidates)
        if candidate.signal != "HOLD" and candidate.confidence < self.min_confidence:
            candidate = PatternCandidate(
                pattern=candidate.pattern,
                signal="HOLD",
                confidence=candidate.confidence,
                reason=f"{candidate.reason}; confidence below minimum",
                entry_price=None,
                stop_loss=None,
                take_profit=None,
                structure_clear=candidate.structure_clear,
                breakout=candidate.breakout,
                breakdown=candidate.breakdown,
                volume_confirmed=candidate.volume_confirmed,
                pivot_count=candidate.pivot_count,
                direction_matches_trend=candidate.direction_matches_trend,
                width_ratio=candidate.width_ratio,
                volatility_ratio=candidate.volatility_ratio,
            )

        direction = {
            "BUY": SignalDirection.LONG,
            "SELL": SignalDirection.SHORT,
            "HOLD": SignalDirection.WAIT,
        }[candidate.signal]
        metadata = _metadata(candidate)
        if direction is SignalDirection.WAIT:
            signal = Signal.wait(metadata=metadata)
        else:
            signal = Signal(
                direction=direction,
                confidence=candidate.confidence,
                reasons=(
                    SignalReason(
                        code=f"chart_pattern_{candidate.pattern}",
                        message=candidate.reason,
                        metadata=metadata,
                    ),
                ),
                metadata=metadata,
            )
        return StrategyResult(name=self.name, signal=signal, metadata=metadata)

    def _hold(self, reason: str, pattern: str | None) -> StrategyResult:
        metadata = {
            "strategy": "chart_pattern",
            "signal": "HOLD",
            "pattern": pattern,
            "confidence": Decimal("0"),
            "reason": reason,
            "entry_price": None,
            "stop_loss": None,
            "take_profit": None,
        }
        return StrategyResult(
            name=self.name,
            signal=Signal.wait(metadata=metadata),
            metadata=metadata,
        )


class PivotDetector:
    @staticmethod
    def find_pivot_highs(
        candles: tuple[Candle, ...],
        pivot_window: int,
    ) -> tuple[Pivot, ...]:
        pivots: list[Pivot] = []
        for index in range(pivot_window, len(candles) - pivot_window):
            price = candles[index].high_price
            left = candles[index - pivot_window : index]
            right = candles[index + 1 : index + pivot_window + 1]
            if all(price >= candle.high_price for candle in left + right):
                _append_deduped_pivot(pivots, Pivot(index, price), pivot_window, high=True)
        return tuple(pivots)

    @staticmethod
    def find_pivot_lows(
        candles: tuple[Candle, ...],
        pivot_window: int,
    ) -> tuple[Pivot, ...]:
        pivots: list[Pivot] = []
        for index in range(pivot_window, len(candles) - pivot_window):
            price = candles[index].low_price
            left = candles[index - pivot_window : index]
            right = candles[index + 1 : index + pivot_window + 1]
            if all(price <= candle.low_price for candle in left + right):
                _append_deduped_pivot(pivots, Pivot(index, price), pivot_window, high=False)
        return tuple(pivots)


class PatternDetector:
    def __init__(
        self,
        config: ChartPatternStrategy,
        candles: tuple[Candle, ...],
        pivot_highs: tuple[Pivot, ...],
        pivot_lows: tuple[Pivot, ...],
    ) -> None:
        self.config = config
        self.candles = candles
        self.highs = pivot_highs
        self.lows = pivot_lows

    def detect_all(self) -> tuple[PatternCandidate, ...]:
        detectors = (
            self.detect_descending_triangle,
            self.detect_double_top,
            self.detect_triple_top,
            self.detect_head_and_shoulders,
            self.detect_rising_wedge,
            self.detect_ascending_triangle,
            self.detect_double_bottom,
            self.detect_triple_bottom,
            self.detect_inverse_head_and_shoulders,
            self.detect_falling_wedge,
            self.detect_symmetrical_triangle,
            self.detect_box_range,
        )
        return tuple(candidate for detector in detectors if (candidate := detector()))

    def detect_ascending_triangle(self) -> PatternCandidate | None:
        highs = self.highs[-3:]
        lows = self.lows[-3:]
        if len(highs) < 2 or len(lows) < 2:
            return None
        resistance = _average_price(highs)
        structure = _prices_close(highs, self.config.price_tolerance) and _rising(lows)
        if not structure:
            return None
        return self._candidate(
            "ascending_triangle",
            buy_level=resistance,
            sell_level=None,
            stop_reference=lows[-1].price,
            reason="similar pivot highs with rising pivot lows",
            pivot_count=len(highs) + len(lows),
        )

    def detect_descending_triangle(self) -> PatternCandidate | None:
        highs = self.highs[-3:]
        lows = self.lows[-3:]
        if len(highs) < 2 or len(lows) < 2:
            return None
        support = _average_price(lows)
        structure = _prices_close(lows, self.config.price_tolerance) and _falling(highs)
        if not structure:
            return None
        return self._candidate(
            "descending_triangle",
            buy_level=None,
            sell_level=support,
            stop_reference=highs[-1].price,
            reason="similar pivot lows with falling pivot highs",
            pivot_count=len(highs) + len(lows),
        )

    def detect_symmetrical_triangle(self) -> PatternCandidate | None:
        highs = self.highs[-3:]
        lows = self.lows[-3:]
        if len(highs) < 2 or len(lows) < 2:
            return None
        if not (_falling(highs) and _rising(lows) and self._range_contracting(highs, lows)):
            return None
        return self._candidate(
            "symmetrical_triangle",
            buy_level=_project_line(highs, len(self.candles) - 1),
            sell_level=_project_line(lows, len(self.candles) - 1),
            stop_reference=lows[-1].price,
            reason="falling pivot highs and rising pivot lows with narrowing range",
            pivot_count=len(highs) + len(lows),
        )

    def detect_box_range(self) -> PatternCandidate | None:
        highs = self.highs[-4:]
        lows = self.lows[-4:]
        if len(highs) < 2 or len(lows) < 2:
            return None
        if not (_prices_close(highs, self.config.price_tolerance) and _prices_close(lows, self.config.price_tolerance)):
            return None
        return self._candidate(
            "box_range",
            buy_level=_average_price(highs),
            sell_level=_average_price(lows),
            stop_reference=lows[-1].price,
            reason="price repeatedly tested similar support and resistance",
            pivot_count=len(highs) + len(lows),
        )

    def detect_double_top(self) -> PatternCandidate | None:
        highs = self.highs[-2:]
        if len(highs) < 2 or not _prices_close(highs, self.config.price_tolerance):
            return None
        lows_between = _between(self.lows, highs[0].index, highs[1].index)
        if not lows_between:
            return None
        neckline = min(lows_between, key=lambda pivot: pivot.price).price
        return self._candidate(
            "double_top",
            buy_level=None,
            sell_level=neckline,
            stop_reference=max(high.price for high in highs),
            reason="two similar pivot highs with neckline support",
            pivot_count=len(highs) + len(lows_between),
        )

    def detect_double_bottom(self) -> PatternCandidate | None:
        lows = self.lows[-2:]
        if len(lows) < 2 or not _prices_close(lows, self.config.price_tolerance):
            return None
        highs_between = _between(self.highs, lows[0].index, lows[1].index)
        if not highs_between:
            return None
        neckline = max(highs_between, key=lambda pivot: pivot.price).price
        return self._candidate(
            "double_bottom",
            buy_level=neckline,
            sell_level=None,
            stop_reference=min(low.price for low in lows),
            reason="two similar pivot lows with neckline resistance",
            pivot_count=len(lows) + len(highs_between),
        )

    def detect_triple_top(self) -> PatternCandidate | None:
        highs = self.highs[-3:]
        if len(highs) < 3 or not _prices_close(highs, self.config.price_tolerance):
            return None
        lows_between = _between(self.lows, highs[0].index, highs[-1].index)
        if len(lows_between) < 2:
            return None
        neckline = min(pivot.price for pivot in lows_between)
        return self._candidate(
            "triple_top",
            buy_level=None,
            sell_level=neckline,
            stop_reference=max(pivot.price for pivot in highs),
            reason="three similar pivot highs with reaction lows",
            pivot_count=len(highs) + len(lows_between),
        )

    def detect_triple_bottom(self) -> PatternCandidate | None:
        lows = self.lows[-3:]
        if len(lows) < 3 or not _prices_close(lows, self.config.price_tolerance):
            return None
        highs_between = _between(self.highs, lows[0].index, lows[-1].index)
        if len(highs_between) < 2:
            return None
        neckline = max(pivot.price for pivot in highs_between)
        return self._candidate(
            "triple_bottom",
            buy_level=neckline,
            sell_level=None,
            stop_reference=min(pivot.price for pivot in lows),
            reason="three similar pivot lows with reaction highs",
            pivot_count=len(lows) + len(highs_between),
        )

    def detect_head_and_shoulders(self) -> PatternCandidate | None:
        highs = self.highs[-3:]
        if len(highs) < 3:
            return None
        left, head, right = highs
        if not (head.price > left.price and head.price > right.price):
            return None
        if not _close(left.price, right.price, self.config.price_tolerance):
            return None
        lows_between = _between(self.lows, left.index, right.index)
        if len(lows_between) < 2:
            return None
        neckline = _average_price(lows_between)
        return self._candidate(
            "head_and_shoulders",
            buy_level=None,
            sell_level=neckline,
            stop_reference=right.price,
            reason="head high above similar shoulder highs with neckline support",
            pivot_count=len(highs) + len(lows_between),
        )

    def detect_inverse_head_and_shoulders(self) -> PatternCandidate | None:
        lows = self.lows[-3:]
        if len(lows) < 3:
            return None
        left, head, right = lows
        if not (head.price < left.price and head.price < right.price):
            return None
        if not _close(left.price, right.price, self.config.price_tolerance):
            return None
        highs_between = _between(self.highs, left.index, right.index)
        if len(highs_between) < 2:
            return None
        neckline = _average_price(highs_between)
        return self._candidate(
            "inverse_head_and_shoulders",
            buy_level=neckline,
            sell_level=None,
            stop_reference=right.price,
            reason="head low below similar shoulder lows with neckline resistance",
            pivot_count=len(lows) + len(highs_between),
        )

    def detect_falling_wedge(self) -> PatternCandidate | None:
        highs = self.highs[-3:]
        lows = self.lows[-3:]
        if len(highs) < 2 or len(lows) < 2:
            return None
        high_slope = _slope(highs)
        low_slope = _slope(lows)
        if not (_falling(highs) and _falling(lows) and high_slope < low_slope and self._range_contracting(highs, lows)):
            return None
        return self._candidate(
            "falling_wedge",
            buy_level=_project_line(highs, len(self.candles) - 1),
            sell_level=None,
            stop_reference=lows[-1].price,
            reason="falling highs and lows with contracting wedge",
            pivot_count=len(highs) + len(lows),
        )

    def detect_rising_wedge(self) -> PatternCandidate | None:
        highs = self.highs[-3:]
        lows = self.lows[-3:]
        if len(highs) < 2 or len(lows) < 2:
            return None
        high_slope = _slope(highs)
        low_slope = _slope(lows)
        if not (_rising(highs) and _rising(lows) and low_slope > high_slope and self._range_contracting(highs, lows)):
            return None
        return self._candidate(
            "rising_wedge",
            buy_level=None,
            sell_level=_project_line(lows, len(self.candles) - 1),
            stop_reference=highs[-1].price,
            reason="rising highs and lows with contracting wedge",
            pivot_count=len(highs) + len(lows),
        )

    def _candidate(
        self,
        pattern: PatternName,
        *,
        buy_level: Decimal | None,
        sell_level: Decimal | None,
        stop_reference: Decimal,
        reason: str,
        pivot_count: int,
    ) -> PatternCandidate:
        close = self.candles[-1].close_price
        signal: PatternSignal = "HOLD"
        breakout = buy_level is not None and close > buy_level * (Decimal("1") + self.config.breakout_buffer)
        breakdown = sell_level is not None and close < sell_level * (Decimal("1") - self.config.breakout_buffer)
        if breakdown:
            signal = "SELL"
        elif breakout:
            signal = "BUY"

        entry_price = close if signal != "HOLD" else None
        stop_loss = None
        take_profit = None
        if entry_price is not None:
            if signal == "BUY":
                stop_loss = min(stop_reference, close) * (Decimal("1") - self.config.breakout_buffer)
                take_profit = entry_price + (entry_price - stop_loss) * self.config.risk_reward_ratio
            else:
                stop_loss = max(stop_reference, close) * (Decimal("1") + self.config.breakout_buffer)
                take_profit = entry_price - (stop_loss - entry_price) * self.config.risk_reward_ratio

        volume_confirmed = self._volume_confirmed()
        width_ratio = self._pattern_width_ratio()
        volatility_ratio = self._volatility_ratio()
        direction_matches_trend = self._direction_matches_trend(signal)
        confidence = ConfidenceScorer.score(
            structure_clear=True,
            breakout_or_breakdown=breakout or breakdown,
            volume_confirmed=volume_confirmed,
            direction_matches_trend=direction_matches_trend,
            pivot_count=pivot_count,
            weak_close=False,
            width_too_small=width_ratio < self.config.breakout_buffer,
            volatility_too_high=volatility_ratio > Decimal("0.08"),
        )
        return PatternCandidate(
            pattern=pattern,
            signal=signal,
            confidence=confidence,
            reason=reason if signal == "HOLD" else f"{reason}; {'breakout' if signal == 'BUY' else 'breakdown'} confirmed",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            structure_clear=True,
            breakout=breakout,
            breakdown=breakdown,
            volume_confirmed=volume_confirmed,
            pivot_count=pivot_count,
            direction_matches_trend=direction_matches_trend,
            width_ratio=width_ratio,
            volatility_ratio=volatility_ratio,
        )

    def _volume_confirmed(self) -> bool:
        if len(self.candles) < self.config.volume_ma_period:
            return False
        volumes = [candle.volume for candle in self.candles[-self.config.volume_ma_period :]]
        average = sum(volumes, Decimal("0")) / Decimal(len(volumes))
        return self.candles[-1].volume > average * self.config.volume_multiplier

    def _pattern_width_ratio(self) -> Decimal:
        recent = self.candles[-min(len(self.candles), self.config.lookback) :]
        high = max(candle.high_price for candle in recent)
        low = min(candle.low_price for candle in recent)
        return Decimal("0") if high == 0 else (high - low) / high

    def _volatility_ratio(self) -> Decimal:
        ranges = [
            (candle.high_price - candle.low_price) / candle.close_price
            for candle in self.candles[-min(20, len(self.candles)) :]
            if candle.close_price > Decimal("0")
        ]
        if not ranges:
            return Decimal("0")
        return sum(ranges, Decimal("0")) / Decimal(len(ranges))

    def _direction_matches_trend(self, signal: PatternSignal) -> bool:
        if signal == "HOLD" or len(self.candles) < 5:
            return False
        first = self.candles[-5].close_price
        last = self.candles[-1].close_price
        return (signal == "BUY" and last >= first) or (signal == "SELL" and last <= first)

    def _range_contracting(self, highs: tuple[Pivot, ...], lows: tuple[Pivot, ...]) -> bool:
        first_gap = highs[0].price - lows[0].price
        last_gap = highs[-1].price - lows[-1].price
        return first_gap > Decimal("0") and last_gap > Decimal("0") and last_gap < first_gap


class ConfidenceScorer:
    @staticmethod
    def score(
        *,
        structure_clear: bool,
        breakout_or_breakdown: bool,
        volume_confirmed: bool,
        direction_matches_trend: bool,
        pivot_count: int,
        weak_close: bool,
        width_too_small: bool,
        volatility_too_high: bool,
    ) -> Decimal:
        score = Decimal("0.5")
        if structure_clear:
            score += Decimal("0.15")
        if breakout_or_breakdown:
            score += Decimal("0.15")
        if volume_confirmed:
            score += Decimal("0.15")
        else:
            score -= Decimal("0.1")
        if direction_matches_trend:
            score += Decimal("0.1")
        if pivot_count >= 4:
            score += Decimal("0.05")
        if weak_close:
            score -= Decimal("0.1")
        if width_too_small:
            score -= Decimal("0.1")
        if volatility_too_high:
            score -= Decimal("0.1")
        return min(Decimal("1"), max(Decimal("0"), score))


def _append_deduped_pivot(
    pivots: list[Pivot],
    pivot: Pivot,
    pivot_window: int,
    *,
    high: bool,
) -> None:
    if not pivots or pivot.index - pivots[-1].index > pivot_window:
        pivots.append(pivot)
        return
    previous = pivots[-1]
    if (high and pivot.price > previous.price) or (not high and pivot.price < previous.price):
        pivots[-1] = pivot


def _select_candidate(candidates: tuple[PatternCandidate, ...]) -> PatternCandidate:
    actionable = [candidate for candidate in candidates if candidate.signal == "SELL"]
    if not actionable:
        actionable = [candidate for candidate in candidates if candidate.signal == "BUY"]
    if not actionable:
        actionable = list(candidates)
    return max(actionable, key=lambda candidate: candidate.confidence)


def _metadata(candidate: PatternCandidate) -> dict[str, object]:
    return {
        "strategy": "chart_pattern",
        "signal": candidate.signal,
        "pattern": candidate.pattern,
        "confidence": candidate.confidence,
        "reason": candidate.reason,
        "entry_price": candidate.entry_price,
        "stop_loss": candidate.stop_loss,
        "take_profit": candidate.take_profit,
        "volume_confirmed": candidate.volume_confirmed,
        "breakout": candidate.breakout,
        "breakdown": candidate.breakdown,
    }


def _average_price(pivots: Iterable[Pivot]) -> Decimal:
    values = [pivot.price for pivot in pivots]
    return sum(values, Decimal("0")) / Decimal(len(values))


def _prices_close(pivots: tuple[Pivot, ...], tolerance: Decimal) -> bool:
    prices = [pivot.price for pivot in pivots]
    low = min(prices)
    high = max(prices)
    return low > 0 and (high / low) - Decimal("1") <= tolerance


def _close(left: Decimal, right: Decimal, tolerance: Decimal) -> bool:
    low = min(left, right)
    high = max(left, right)
    return low > 0 and (high / low) - Decimal("1") <= tolerance


def _rising(pivots: tuple[Pivot, ...]) -> bool:
    return all(current.price > previous.price for previous, current in zip(pivots, pivots[1:]))


def _falling(pivots: tuple[Pivot, ...]) -> bool:
    return all(current.price < previous.price for previous, current in zip(pivots, pivots[1:]))


def _between(pivots: tuple[Pivot, ...], start: int, end: int) -> tuple[Pivot, ...]:
    return tuple(pivot for pivot in pivots if start < pivot.index < end)


def _slope(pivots: tuple[Pivot, ...]) -> Decimal:
    first = pivots[0]
    last = pivots[-1]
    distance = Decimal(last.index - first.index)
    if distance == 0:
        return Decimal("0")
    return (last.price - first.price) / distance


def _project_line(pivots: tuple[Pivot, ...], index: int) -> Decimal:
    if len(pivots) < 2:
        return pivots[-1].price
    slope = _slope(pivots[-2:])
    last = pivots[-1]
    return last.price + slope * Decimal(index - last.index)
