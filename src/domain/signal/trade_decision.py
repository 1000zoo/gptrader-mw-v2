from dataclasses import dataclass
from enum import Enum

from src.domain.signal.signal import Signal, SignalDirection


class TradeDecisionAction(Enum):
    ENTER_LONG = "enter_long"
    ENTER_SHORT = "enter_short"
    EXIT = "exit"
    HOLD = "hold"


@dataclass(frozen=True)
class TradeDecision:
    action: TradeDecisionAction
    signal: Signal

    def __post_init__(self) -> None:
        if (
            self.action is TradeDecisionAction.ENTER_LONG
            and self.signal.direction is not SignalDirection.LONG
        ):
            raise ValueError("ENTER_LONG requires a LONG signal")

        if (
            self.action is TradeDecisionAction.ENTER_SHORT
            and self.signal.direction is not SignalDirection.SHORT
        ):
            raise ValueError("ENTER_SHORT requires a SHORT signal")
