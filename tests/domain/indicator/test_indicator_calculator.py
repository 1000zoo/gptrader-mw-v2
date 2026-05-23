from typing import Protocol

from src.domain.indicator import IndicatorCalculator, IndicatorSet
from src.domain.market import MarketSnapshot


def test_indicator_calculator_defines_market_snapshot_to_indicator_set_contract():
    assert issubclass(IndicatorCalculator, Protocol)

    annotations = IndicatorCalculator.calculate.__annotations__

    assert annotations["snapshot"] == MarketSnapshot
    assert annotations["return"] == IndicatorSet
