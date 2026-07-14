from decimal import Decimal

import pytest

from src.infrastructure.persistence import SqliteRegimeSelectionStateRepository
from src.infrastructure.regime import JsonRegimeArtifactRepository
from src.infrastructure.exchange.binance.market_data import BinanceMarketDataAdapter
from src.infrastructure.exchange.binance.order_execution import BinanceOrderExecutionAdapter
from src.runtime import RuntimeMode, RuntimeSettings, create_local_app, create_local_runtime
from tests.infrastructure.regime.test_json_regime_artifact_repository import (
    _mapping,
    _model,
)


def test_local_runtime_reports_health_details() -> None:
    runtime = create_local_runtime(RuntimeSettings(symbol="ETHUSDT"))

    details = runtime.health_details()

    assert details["mode"] == "local"
    assert details["symbol"] == "ETHUSDT"
    assert details["dependencies"][0] == {
        "name": "exchange",
        "status": "local",
        "detail": "external exchange disabled",
    }
    assert runtime.regime_selection_scheduler is None


def test_enabled_regime_selection_fails_fast_when_artifact_files_are_missing(tmp_path) -> None:
    settings = RuntimeSettings(
        database_url=str(tmp_path / "state.sqlite3"),
        regime_selection_enabled=True,
        regime_model_artifact_path=str(tmp_path / "model.json"),
        regime_mapping_artifact_path=str(tmp_path / "mapping.json"),
        regime_candidate_definition_hash="a" * 64,
        regime_candidate_universe_hash="b" * 64,
        regime_data_provenance_hash="c" * 64,
    )
    with pytest.raises(ValueError, match="regime model artifact path"):
        create_local_runtime(settings)


def test_enabled_regime_selection_loads_frozen_artifacts_without_changing_trade_strategy(tmp_path) -> None:
    artifact_dir = tmp_path / "artifacts"
    model = _model()
    mapping = _mapping(model)
    artifacts = JsonRegimeArtifactRepository(artifact_dir)
    artifacts.save_model(model)
    artifacts.save_mapping(mapping)
    database_path = tmp_path / "state.sqlite3"
    settings = RuntimeSettings(
        database_url=str(database_path),
        trading_strategy_id="chart-pattern",
        regime_selection_enabled=True,
        regime_model_artifact_path=str(artifact_dir / "model.json"),
        regime_mapping_artifact_path=str(artifact_dir / "mapping.json"),
        regime_candidate_definition_hash=mapping.candidate_definition_hash,
        regime_candidate_universe_hash=mapping.candidate_universe_hash,
        regime_data_provenance_hash=mapping.data_provenance_hash,
    )

    runtime = create_local_runtime(settings)

    assert runtime.regime_selection_scheduler is not None
    assert runtime.regime_selection_snapshot.model_type == "kmeans"
    assert (
        runtime.regime_selection_snapshot.confidence_thresholds.kmeans_max_standardized_distance
        == max(model.distance_thresholds)
    )
    assert runtime.regime_model_artifact == model
    assert runtime.regime_mapping_artifact == mapping
    assert runtime.status_details()["active_strategy_id"] == "chart-pattern"
    assert SqliteRegimeSelectionStateRepository(database_path).list_events("BTCUSDT") == ()


def test_enabled_regime_selection_supports_standalone_mapping_directory(tmp_path) -> None:
    model_dir = tmp_path / "model"
    mapping_dir = tmp_path / "mapping"
    model = _model("diag")
    mapping = _mapping(model)
    JsonRegimeArtifactRepository(model_dir).save_model(model)
    JsonRegimeArtifactRepository(mapping_dir).save_mapping(
        mapping,
        expected_model_artifact_hash=mapping.regime_model_artifact_hash,
        expected_model_fingerprint_hash=mapping.regime_model_fingerprint_hash,
    )
    settings = RuntimeSettings(
        database_url=str(tmp_path / "state.sqlite3"),
        regime_selection_enabled=True,
        regime_model_artifact_path=str(model_dir / "model.json"),
        regime_mapping_artifact_path=str(mapping_dir / "mapping.json"),
        regime_candidate_definition_hash=mapping.candidate_definition_hash,
        regime_candidate_universe_hash=mapping.candidate_universe_hash,
        regime_data_provenance_hash=mapping.data_provenance_hash,
        regime_gmm_p_min=0.8,
        regime_gmm_margin_min=0.3,
    )

    runtime = create_local_runtime(settings)

    thresholds = runtime.regime_selection_snapshot.confidence_thresholds
    assert thresholds.model_type == "gmm"
    assert thresholds.gmm_probability_min == 0.8
    assert thresholds.gmm_margin_min == 0.3


def test_local_app_exposes_health_and_readiness_routes() -> None:
    app = create_local_app(RuntimeSettings(symbol="ETHUSDT"))
    health = next(route for route in app.routes if route.path == "/health")
    readiness = next(route for route in app.routes if route.path == "/readiness")
    status = next(route for route in app.routes if route.path == "/status")

    assert health.endpoint()["details"]["symbol"] == "ETHUSDT"
    assert readiness.endpoint()["details"]["ready_for"] == "local"
    assert status.endpoint()["data"]["trade_controls"] == "disabled"
    assert status.endpoint()["data"]["live_order_path"] == "disabled"


def test_local_runtime_can_run_strategy_backtest_cycle() -> None:
    runtime = create_local_runtime(RuntimeSettings(symbol="BTCUSDT"))

    result = runtime.run_strategy_backtest_cycle("cycle-local")

    assert result.succeeded_count == 6
    assert result.failed_count == 0
    assert {item.strategy_id for item in result.items} == {
        "latest-close-moving-average",
        "session-volume-profile",
        "chart-pattern",
        "tv-range-seed-s1-t1-p2-fixed",
        "live-compression-s2-sl0030-rr045-balanced",
        "live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2",
    }
    assert runtime.status_details()["strategy_backtest_cycle"]["succeeded_count"] == 6


def test_local_runtime_can_filter_backtest_strategies() -> None:
    runtime = create_local_runtime(
        RuntimeSettings(
            symbol="BTCUSDT",
            backtest_strategy_ids=("chart-pattern",),
        )
    )

    result = runtime.run_strategy_backtest_cycle("cycle-local")

    assert result.succeeded_count == 1
    assert result.failed_count == 0
    assert [item.strategy_id for item in result.items] == ["chart-pattern"]


def test_live_armed_runtime_uses_seed_combo_and_live_exchange_adapters() -> None:
    runtime = create_local_runtime(
        RuntimeSettings(
            mode=RuntimeMode.LIVE_ARMED,
            live_armed=True,
            trading_strategy_id="tv-range-seed-s1-t1-p2-fixed",
            take_profit_stop_loss="fixed",
            stop_loss_ratio=Decimal("0.09"),
            reward_risk_ratio=Decimal("0.15"),
            position_sizing="fixed",
            fixed_equity_ratio=Decimal("0.10"),
            fixed_leverage=Decimal("15"),
        )
    )

    details = runtime.status_details()

    assert details["trade_controls"] == "enabled"
    assert details["live_order_path"] == "enabled"
    assert details["active_strategy_id"] == "tv-range-seed-s1-t1-p2-fixed"
    assert details["take_profit_stop_loss"] == {
        "kind": "fixed",
        "stop_loss_ratio": "0.09",
        "reward_risk_ratio": "0.15",
    }
    assert details["position_sizing"] == {
        "kind": "fixed",
        "equity_ratio": "0.10",
        "leverage": "15",
    }
    assert isinstance(runtime._market_data, BinanceMarketDataAdapter)
    assert isinstance(runtime._order_execution, BinanceOrderExecutionAdapter)


def test_live_armed_runtime_uses_compression_s2_combo_settings() -> None:
    runtime = create_local_runtime(
        RuntimeSettings(
            mode=RuntimeMode.LIVE_ARMED,
            live_armed=True,
            trading_strategy_id="live-compression-s2-sl0030-rr045-balanced",
            candle_limit=1442,
            take_profit_stop_loss="fixed",
            stop_loss_ratio=Decimal("0.030"),
            reward_risk_ratio=Decimal("0.45"),
            position_sizing="confidence",
            min_equity_ratio=Decimal("0.02"),
            max_equity_ratio=Decimal("0.14"),
            min_leverage=Decimal("1"),
            max_leverage=Decimal("8"),
        )
    )

    details = runtime.status_details()

    assert details["active_strategy_id"] == "live-compression-s2-sl0030-rr045-balanced"
    assert details["take_profit_stop_loss"] == {
        "kind": "fixed",
        "stop_loss_ratio": "0.030",
        "reward_risk_ratio": "0.45",
    }
    assert details["position_sizing"] == {
        "kind": "confidence",
        "min_equity_ratio": "0.02",
        "max_equity_ratio": "0.14",
        "min_leverage": "1",
        "max_leverage": "8",
    }
