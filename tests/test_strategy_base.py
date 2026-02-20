import pytest

from src.strategy.strategies.IStrategy import IStrategy
from src.strategy.strategies.models import StrategyInitConfig, StrategyRunInput


class DummyStrategy(IStrategy):
    def init_strategy(self, config):
        super().init_strategy(config)

    def run_strategy(self, data):
        self.validate_input(data)
        return self._hold("ok")


@pytest.fixture
def sample_input():
    return StrategyRunInput(
        indicators_by_tf={
            "1m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "5m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "15m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "30m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "1h": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
        },
        ohlcv_by_tf={
            "1m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "5m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "15m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "30m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "1h": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
        },
    )


@pytest.fixture
def sample_config():
    return StrategyInitConfig(
        strategy_name="dummy",
        symbol="BTCUSDT",
        timeframes=["1m", "5m", "15m", "30m", "1h"],
        lookback_by_tf={"1m": 1, "5m": 1, "15m": 1, "30m": 1, "1h": 1},
        params={},
    )


def test_run_strategy_raises_when_not_initialized(sample_input):
    strategy = DummyStrategy()
    with pytest.raises(ValueError):
        strategy.run_strategy(sample_input)


def test_validate_input_raises_on_missing_timeframe(sample_config):
    strategy = DummyStrategy()
    strategy.init_strategy(sample_config)

    bad_input = StrategyRunInput(
        indicators_by_tf={
            "1m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "5m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "15m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "30m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
        },
        ohlcv_by_tf={
            "1m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "5m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "15m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "30m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "1h": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
        },
    )

    with pytest.raises(ValueError):
        strategy.validate_input(bad_input)


def test_validate_input_raises_on_insufficient_rows():
    strategy = DummyStrategy()
    strategy.init_strategy(
        StrategyInitConfig(
            strategy_name="dummy",
            symbol="BTCUSDT",
            timeframes=["1m", "5m", "15m", "30m", "1h"],
            lookback_by_tf={"1m": 2, "5m": 1, "15m": 1, "30m": 1, "1h": 1},
            params={},
        )
    )

    bad_input = StrategyRunInput(
        indicators_by_tf={
            "1m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "5m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "15m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "30m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "1h": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
        },
        ohlcv_by_tf={
            "1m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "5m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "15m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "30m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "1h": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
        },
    )

    with pytest.raises(ValueError):
        strategy.validate_input(bad_input)


def test_validate_input_raises_on_missing_ohlcv_timeframe(sample_config):
    strategy = DummyStrategy()
    strategy.init_strategy(sample_config)

    bad_input = StrategyRunInput(
        indicators_by_tf={
            "1m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "5m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "15m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "30m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "1h": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
        },
        ohlcv_by_tf={
            "1m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "5m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "15m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "30m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
        },
    )

    with pytest.raises(ValueError):
        strategy.validate_input(bad_input)


def test_latest_and_window_helpers_work(sample_config):
    strategy = DummyStrategy()
    strategy.init_strategy(sample_config)

    data = StrategyRunInput(
        indicators_by_tf={
            "1m": [
                {"timestamp": "2026-01-01T00:00:00Z", "rsi": 40.0},
                {"timestamp": "2026-01-01T00:01:00Z", "rsi": 55.0},
            ],
            "5m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "15m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "30m": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
            "1h": [{"timestamp": "2026-01-01T00:00:00Z", "rsi": 50.0}],
        },
        ohlcv_by_tf={
            "1m": {"timestamp": "2026-01-01T00:01:00Z", "open": 1.0},
            "5m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "15m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "30m": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
            "1h": {"timestamp": "2026-01-01T00:00:00Z", "open": 1.0},
        },
    )

    assert strategy._latest(data, "1m", "rsi") == 55.0
    assert len(strategy._window(data, "1m", 2)) == 2


def test_name_returns_configured_name_after_init(sample_config):
    strategy = DummyStrategy()
    assert strategy.name() == "DummyStrategy"

    strategy.init_strategy(sample_config)
    assert strategy.name() == "dummy"


def test_latest_raises_value_error_for_invalid_column(sample_config, sample_input):
    strategy = DummyStrategy()
    strategy.init_strategy(sample_config)

    with pytest.raises(ValueError):
        strategy._latest(sample_input, "1m", "not_exists")
