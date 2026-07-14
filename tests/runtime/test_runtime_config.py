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


def test_regime_selection_is_disabled_by_default_and_does_not_require_artifacts() -> None:
    settings = RuntimeSettings.from_env({})
    assert settings.regime_selection_enabled is False
    assert settings.regime_model_artifact_path is None


def test_enabled_regime_selection_loads_compatibility_and_confidence_settings() -> None:
    hashes = {name: character * 64 for name, character in (
        ("GPTRADER_REGIME_CANDIDATE_DEFINITION_HASH", "a"),
        ("GPTRADER_REGIME_CANDIDATE_UNIVERSE_HASH", "b"),
        ("GPTRADER_REGIME_DATA_PROVENANCE_HASH", "c"),
    )}
    settings = RuntimeSettings.from_env({
        "GPTRADER_REGIME_SELECTION_ENABLED": "true",
        "GPTRADER_REGIME_MODEL_ARTIFACT_PATH": " artifacts/model.json ",
        "GPTRADER_REGIME_MAPPING_ARTIFACT_PATH": " artifacts/mapping.json ",
        "GPTRADER_REGIME_GMM_P_MIN": "0.8",
        "GPTRADER_REGIME_GMM_MARGIN_MIN": "0.3",
        "GPTRADER_REGIME_KMEANS_MAX_DISTANCE": "2.5",
        **hashes,
    })
    assert settings.regime_model_artifact_path == "artifacts/model.json"
    assert settings.regime_gmm_p_min == 0.8
    assert settings.regime_gmm_margin_min == 0.3
    assert settings.regime_kmeans_max_distance == 2.5


@pytest.mark.parametrize("value", ["yes", "1", "", "TRUE "])
def test_regime_selection_enabled_is_a_strict_environment_boolean(value) -> None:
    with pytest.raises(ValueError, match="GPTRADER_REGIME_SELECTION_ENABLED"):
        RuntimeSettings.from_env({"GPTRADER_REGIME_SELECTION_ENABLED": value})


def test_enabled_regime_selection_requires_artifact_paths_and_hashes() -> None:
    with pytest.raises(ValueError, match="regime artifact paths"):
        RuntimeSettings(regime_selection_enabled=True)
    with pytest.raises(ValueError, match="compatibility hashes"):
        RuntimeSettings(
            regime_selection_enabled=True,
            regime_model_artifact_path="model.json",
            regime_mapping_artifact_path="mapping.json",
        )


@pytest.mark.parametrize("field,value", [
    ("regime_gmm_p_min", True),
    ("regime_gmm_p_min", float("nan")),
    ("regime_gmm_p_min", 1.1),
    ("regime_gmm_margin_min", -0.1),
    ("regime_kmeans_max_distance", 0),
    ("regime_kmeans_max_distance", float("inf")),
])
def test_regime_confidence_controls_are_strict(field, value) -> None:
    with pytest.raises(ValueError, match="regime"):
        RuntimeSettings(**{field: value})
