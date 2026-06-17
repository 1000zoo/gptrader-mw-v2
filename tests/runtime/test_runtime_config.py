import pytest

from src.runtime import RuntimeMode, RuntimeSettings


def test_runtime_settings_loads_from_env_mapping() -> None:
    settings = RuntimeSettings.from_env(
        {
            "GPTRADER_MODE": "dry-run",
            "GPTRADER_SYMBOL": "ETHUSDT",
            "GPTRADER_TIMEFRAME": "5m",
            "GPTRADER_CANDLE_LIMIT": "50",
            "GPTRADER_CLIENT_ORDER_ID_PREFIX": "dry",
            "GPTRADER_GENERATOR_ID": "generator",
            "GPTRADER_SIGNAL_ID_PREFIX": "signal",
            "GPTRADER_DB_URL": "sqlite:///tmp.sqlite3",
        }
    )

    assert settings.mode is RuntimeMode.DRY_RUN
    assert settings.symbol == "ETHUSDT"
    assert settings.timeframe == "5m"
    assert settings.candle_limit == 50
    assert settings.database_url == "sqlite:///tmp.sqlite3"


def test_live_armed_mode_requires_explicit_arm_flag() -> None:
    with pytest.raises(ValueError, match="live-armed mode requires"):
        RuntimeSettings.from_env({"GPTRADER_MODE": "live-armed"})


def test_testnet_mode_requires_testnet_binance_credentials() -> None:
    with pytest.raises(ValueError, match="BINANCE_TEST_API_KEY"):
        RuntimeSettings.from_env({"GPTRADER_MODE": "testnet"})


def test_live_armed_mode_requires_live_binance_credentials() -> None:
    with pytest.raises(ValueError, match="BINANCE_API_KEY"):
        RuntimeSettings.from_env(
            {
                "GPTRADER_MODE": "live-armed",
                "GPTRADER_LIVE_ARMED": "true",
            }
        )
