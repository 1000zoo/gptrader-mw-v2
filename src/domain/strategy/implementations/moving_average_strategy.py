from dataclasses import dataclass
from decimal import Decimal

from src.domain.signal import Signal, SignalDirection, SignalReason
from src.domain.strategy import StrategyContext, StrategyResult


@dataclass(frozen=True)
class LatestCloseMovingAverageStrategy:
    name: str = "latest-close-moving-average"
    indicator_key: str = "moving_average.period_3"

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        latest_close = context.market.latest_candle.close_price
        moving_average = context.indicators.require(self.indicator_key).value
        if latest_close > moving_average:
            signal = Signal(
                direction=SignalDirection.LONG,
                confidence=_confidence(latest_close, moving_average),
                reasons=(
                    SignalReason(
                        code="close_above_moving_average",
                        message="latest close is above moving average",
                        metadata={
                            "latest_close": str(latest_close),
                            "moving_average": str(moving_average),
                        },
                    ),
                ),
            )
        elif latest_close < moving_average:
            signal = Signal(
                direction=SignalDirection.SHORT,
                confidence=_confidence(latest_close, moving_average),
                reasons=(
                    SignalReason(
                        code="close_below_moving_average",
                        message="latest close is below moving average",
                        metadata={
                            "latest_close": str(latest_close),
                            "moving_average": str(moving_average),
                        },
                    ),
                ),
            )
        else:
            signal = Signal.wait(
                metadata={
                    "reason": "latest_close_equals_moving_average",
                    "latest_close": str(latest_close),
                    "moving_average": str(moving_average),
                }
            )

        return StrategyResult(
            name=self.name,
            signal=signal,
            metadata={"indicator_key": self.indicator_key},
        )


def _confidence(latest_close: Decimal, moving_average: Decimal) -> Decimal:
    if moving_average == Decimal("0"):
        return Decimal("1")
    distance_ratio = abs(latest_close - moving_average) / moving_average
    return min(Decimal("1"), max(Decimal("0.1"), distance_ratio))
