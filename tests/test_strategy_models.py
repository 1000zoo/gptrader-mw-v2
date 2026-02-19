import pytest

from src.strategy.strategies.models import StrategyRunInput


def test_strategy_run_input_rejects_unknown_indicator_columns():
    with pytest.raises(ValueError):
        StrategyRunInput(
            indicators_by_tf={
                "1m": [{"timestamp": "2026-01-01T00:00:00Z", "unknown_col": 1.0}],
                "5m": [],
                "15m": [],
                "30m": [],
                "1h": [],
            }
        )
