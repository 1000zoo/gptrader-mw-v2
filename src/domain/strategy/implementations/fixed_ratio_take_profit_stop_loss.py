from dataclasses import dataclass
from decimal import Decimal

from src.domain.signal import SignalDirection
from src.domain.strategy import StrategyContext
from src.domain.strategy.take_profit_stop_loss import TakeProfitStopLossLevels


@dataclass(frozen=True)
class FixedRatioTakeProfitStopLossStrategy:
    name: str = "fixed-ratio-take-profit-stop-loss"
    stop_loss_ratio: Decimal = Decimal("0.003")
    reward_risk_ratio: Decimal = Decimal("2")

    def calculate(
        self,
        context: StrategyContext,
        direction: SignalDirection,
    ) -> TakeProfitStopLossLevels:
        if direction is SignalDirection.WAIT:
            raise ValueError("direction must be long or short")
        entry = context.market.latest_candle.close_price
        risk = entry * self.stop_loss_ratio
        if direction is SignalDirection.LONG:
            stop_loss = entry - risk
            take_profit = entry + risk * self.reward_risk_ratio
        else:
            stop_loss = entry + risk
            take_profit = entry - risk * self.reward_risk_ratio
        return TakeProfitStopLossLevels(
            strategy_name=self.name,
            entry_price=entry,
            take_profit=take_profit,
            stop_loss=stop_loss,
            metadata={
                "stop_loss_ratio": str(self.stop_loss_ratio),
                "reward_risk_ratio": str(self.reward_risk_ratio),
            },
        )
