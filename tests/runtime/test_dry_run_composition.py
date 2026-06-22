from pathlib import Path

from src.application.usecases.trade import TradeExecutionStatus
from src.infrastructure.persistence import (
    SqliteRuntimeStateRepository,
    SqliteSignalLogRepository,
)
from src.runtime import RuntimeMode, RuntimeSettings, create_local_app, create_local_runtime
from src.observability.logging import configure_runtime_logging


def _settings(tmp_path: Path) -> RuntimeSettings:
    return RuntimeSettings(
        mode=RuntimeMode.DRY_RUN,
        symbol="BTCUSDT",
        database_url=f"sqlite:///{tmp_path / 'dry-run.sqlite3'}",
        client_order_id_prefix="gptrader-dry-run",
        generator_id="dry-run-generator",
        signal_id_prefix="dry-run-signal",
    )


def test_dry_run_runtime_reports_trade_controls_enabled_without_live_order_path(
    tmp_path,
) -> None:
    runtime = create_local_runtime(_settings(tmp_path))

    details = runtime.status_details()

    assert details["ready_for"] == "dry-run"
    assert details["runtime"] == "dry-run"
    assert details["trade_controls"] == "enabled"
    assert details["live_order_path"] == "disabled"
    assert details["dependencies"][0] == {
        "name": "exchange",
        "status": "dry-run",
        "detail": "orders are recorded locally and not submitted",
    }


def test_dry_run_runtime_runs_trade_execution_and_persists_records(tmp_path) -> None:
    settings = _settings(tmp_path)
    runtime = create_local_runtime(settings)

    result = runtime.run_trade_execution_once("manual-smoke")

    assert result.status is TradeExecutionStatus.ORDER_SUBMITTED
    assert result.order_result is not None
    assert result.order_result.client_order_id == "gptrader-dry-run-manual-smoke"
    assert result.order_result.exchange_order_id == "dry-run-gptrader-dry-run-manual-smoke"

    database_path = tmp_path / "dry-run.sqlite3"
    signal_repository = SqliteSignalLogRepository(database_path)
    runtime_repository = SqliteRuntimeStateRepository(database_path)
    signals = signal_repository.list_signals_for_generator("dry-run-generator")
    dry_run_orders = runtime_repository.list_runtime_records("dry_run_order")
    scheduler_runs = runtime_repository.list_runtime_records("scheduler_run")

    assert len(signals) == 1
    assert signals[0].signal_id == "manual-smoke"
    assert len(dry_run_orders) == 3
    assert dry_run_orders[0].record_id == "gptrader-dry-run-manual-smoke"
    assert dry_run_orders[0].payload["symbol"] == "BTCUSDT"
    assert dry_run_orders[1].record_id == "gptrader-dry-run-manual-smoke-tp"
    assert dry_run_orders[2].record_id == "gptrader-dry-run-manual-smoke-sl"
    assert len(scheduler_runs) == 1
    assert scheduler_runs[0].record_id == "manual-smoke"
    assert scheduler_runs[0].payload["succeeded"] is True
    assert runtime.status_details()["last_trade_execution"]["status"] == "order_submitted"


def test_dry_run_runtime_writes_execution_progress_logs(tmp_path) -> None:
    log_file = configure_runtime_logging(log_root=tmp_path / "logs")
    runtime = create_local_runtime(_settings(tmp_path))

    runtime.run_trade_execution_once("log-smoke")

    content = log_file.read_text(encoding="utf-8")
    assert "runtime created" in content
    assert "dry-run trade execution started" in content
    assert "strategy signal generated" in content
    assert "latest-close-moving-average" in content
    assert "close_above_moving_average" in content
    assert "trade entry sizing calculated" in content
    assert "position_direction" in content
    assert "enter_long" in content
    assert "entry_price" in content
    assert "104" in content
    assert "requested_notional" in content
    assert "position_notional" in content
    assert "position_quantity" in content
    assert "dry-run order recorded" in content
    assert "dry-run trade execution succeeded" in content


def test_dry_run_app_trade_execute_endpoint_is_wired(tmp_path) -> None:
    app = create_local_app(_settings(tmp_path))
    endpoint = next(route.endpoint for route in app.routes if route.path == "/trade/execute")

    response = endpoint({"signal_id": "api-smoke"})

    assert response["ok"] is True
    assert response["data"]["status"] == "order_submitted"
    assert response["data"]["order_result"]["client_order_id"] == (
        "gptrader-dry-run-api-smoke"
    )
