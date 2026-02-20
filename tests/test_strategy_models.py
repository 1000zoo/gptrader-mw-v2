import pytest

from src.binance.vo.ohlcv.default import DefaultOhlcvVo
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
            },
            ohlcv_by_tf={
                "1m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
                "5m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
                "15m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
                "30m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
                "1h": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0},
            },
        )


def test_strategy_run_input_rejects_unknown_ohlcv_columns():
    with pytest.raises(ValueError):
        StrategyRunInput(
            indicators_by_tf={
                "1m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
                "5m": [],
                "15m": [],
                "30m": [],
                "1h": [],
            },
            ohlcv_by_tf={
                "1m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0, "bad_key": 1.0},
                "5m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
                "15m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
                "30m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
                "1h": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            },
        )


def test_from_ohlcv_vo_list_builds_ohlcv_by_tf():
    rows = [
        DefaultOhlcvVo(c_interval="1m", ts="2026-01-01T00:00:00Z", c_open=100.0, c_high=101.0, c_low=99.0, c_close=100.5, volume=10.0, quote_volume=20.0),
        DefaultOhlcvVo(c_interval="5m", ts="2026-01-01T00:05:00Z", c_open=200.0, c_high=201.0, c_low=199.0, c_close=200.5, volume=30.0, quote_volume=40.0),
    ]

    actual = StrategyRunInput.ohlcv_by_tf_from_vo_list(rows)

    assert actual["1m"]["open"] == 100.0
    assert actual["5m"]["close"] == 200.5
