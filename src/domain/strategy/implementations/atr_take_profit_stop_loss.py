from dataclasses import dataclass
from decimal import Decimal

from src.domain.market import Candle
from src.domain.signal import SignalDirection
from src.domain.strategy import StrategyContext
from src.domain.strategy.take_profit_stop_loss import TakeProfitStopLossLevels


@dataclass(frozen=True)
class AtrTakeProfitStopLossStrategy:
    name: str = "atr-take-profit-stop-loss"
    atr_period: int = 14
    atr_multiplier: Decimal = Decimal("2")
    reward_risk_ratio: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        if self.atr_period <= 0:
            raise ValueError("atr_period must be positive")
        if self.atr_multiplier <= Decimal("0"):
            raise ValueError("atr_multiplier must be positive")
        if self.reward_risk_ratio <= Decimal("0"):
            raise ValueError("reward_risk_ratio must be positive")

    def calculate(
        self,
        context: StrategyContext,
        direction: SignalDirection,
    ) -> TakeProfitStopLossLevels:
        if direction is SignalDirection.WAIT:
            raise ValueError("direction must be LONG or SHORT")

        atr = self._average_true_range(context.market.candles)
        entry_price = context.market.latest_candle.close_price
        risk_distance = atr * self.atr_multiplier

        if direction is SignalDirection.LONG:
            stop_loss = entry_price - risk_distance
            take_profit = entry_price + (risk_distance * self.reward_risk_ratio)
        else:
            stop_loss = entry_price + risk_distance
            take_profit = entry_price - (risk_distance * self.reward_risk_ratio)

        return TakeProfitStopLossLevels(
            strategy_name=self.name,
            entry_price=entry_price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            metadata={
                "atr": str(atr),
                "atr_period": self.atr_period,
                "atr_multiplier": str(self.atr_multiplier),
                "reward_risk_ratio": str(self.reward_risk_ratio),
            },
        )

    def _average_true_range(self, candles: tuple[Candle, ...]) -> Decimal:
        if len(candles) < self.atr_period + 1:
            raise ValueError("not enough candles for atr_period")

        selected = candles[-self.atr_period :]
        previous = candles[-self.atr_period - 1 : -1]
        true_ranges = tuple(
            _true_range(candle, previous_candle.close_price)
            for candle, previous_candle in zip(selected, previous)
        )
        return sum(true_ranges, Decimal("0")) / Decimal(self.atr_period)


def _true_range(candle: Candle, previous_close: Decimal) -> Decimal:
    return max(
        candle.high_price - candle.low_price,
        abs(candle.high_price - previous_close),
        abs(candle.low_price - previous_close),
    )
