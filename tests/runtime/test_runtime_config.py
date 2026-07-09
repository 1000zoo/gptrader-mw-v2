import pytest
from decimal import Decimal

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


def test_runtime_settings_loads_live_seed_combo_controls() -> None:
    settings = RuntimeSettings.from_env(
        {
            "GPTRADER_TRADING_STRATEGY_ID": "tv-range-seed-s1-t1-p2-fixed",
            "GPTRADER_TAKE_PROFIT_STOP_LOSS": "fixed",
            "GPTRADER_STOP_LOSS_RATIO": "0.09",
            "GPTRADER_REWARD_RISK_RATIO": "0.15",
            "GPTRADER_POSITION_SIZING": "fixed",
            "GPTRADER_FIXED_EQUITY_RATIO": "0.10",
            "GPTRADER_FIXED_LEVERAGE": "15",
        }
    )

    assert settings.trading_strategy_id == "tv-range-seed-s1-t1-p2-fixed"
    assert settings.take_profit_stop_loss == "fixed"
    assert settings.stop_loss_ratio == Decimal("0.09")
    assert settings.reward_risk_ratio == Decimal("0.15")
    assert settings.position_sizing == "fixed"
    assert settings.fixed_equity_ratio == Decimal("0.10")
    assert settings.fixed_leverage == Decimal("15")


def test_runtime_settings_loads_backtest_strategy_filters() -> None:
    settings = RuntimeSettings.from_env(
        {
            "GPTRADER_BACKTEST_STRATEGY_IDS": "chart-pattern, session-volume-profile ",
            "GPTRADER_DISABLED_BACKTEST_STRATEGY_IDS": "latest-close-moving-average",
        }
    )

    assert settings.backtest_strategy_ids == (
        "chart-pattern",
        "session-volume-profile",
    )
    assert settings.disabled_backtest_strategy_ids == ("latest-close-moving-average",)


def test_runtime_settings_loads_position_sizing_controls() -> None:
    settings = RuntimeSettings.from_env(
        {
            "GPTRADER_MIN_EQUITY_RATIO": "0.05",
            "GPTRADER_MAX_EQUITY_RATIO": "0.40",
            "GPTRADER_MIN_LEVERAGE": "1",
            "GPTRADER_MAX_LEVERAGE": "15",
        }
    )

    assert settings.min_equity_ratio == Decimal("0.05")
    assert settings.max_equity_ratio == Decimal("0.40")
    assert settings.min_leverage == Decimal("1")
    assert settings.max_leverage == Decimal("15")


def test_runtime_settings_rejects_leverage_above_15() -> None:
    with pytest.raises(ValueError, match="max_leverage cannot exceed 15"):
        RuntimeSettings(max_leverage=Decimal("16"))


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
