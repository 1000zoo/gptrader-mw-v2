from decimal import Decimal

from src.domain.signal import SignalDirection
from src.domain.strategy.implementations import LatestCloseMovingAverageStrategy
from src.runtime import RuntimeSettings, build_local_strategy_context


def test_latest_close_moving_average_strategy_emits_long_signal() -> None:
    context = build_local_strategy_context(RuntimeSettings())

    result = LatestCloseMovingAverageStrategy().evaluate(context)

    assert result.name == "latest-close-moving-average"
    assert result.signal.direction is SignalDirection.LONG
    assert result.signal.confidence > Decimal("0")
    assert result.signal.reasons[0].code == "close_above_moving_average"
