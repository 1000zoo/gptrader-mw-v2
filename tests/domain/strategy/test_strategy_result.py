from decimal import Decimal

import pytest

from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import StrategyResult


def test_strategy_result_stores_strategy_name_and_signal():
    signal = Signal(direction=SignalDirection.LONG, confidence=Decimal("0.7"))

    result = StrategyResult(
        name=" breakout ",
        signal=signal,
        metadata={"window": 20},
    )

    assert result.name == "breakout"
    assert result.signal == signal
    assert result.metadata["window"] == 20


def test_strategy_result_rejects_blank_name():
    with pytest.raises(ValueError, match="name"):
        StrategyResult(name=" ", signal=Signal.wait())


def test_strategy_result_defensively_copies_metadata():
    metadata = {"source": "test"}

    result = StrategyResult(name="mean_reversion", signal=Signal.wait(), metadata=metadata)
    metadata["source"] = "changed"

    assert result.metadata["source"] == "test"
    with pytest.raises(TypeError):
        result.metadata["source"] = "changed"
