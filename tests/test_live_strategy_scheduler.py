from datetime import datetime, timezone
from decimal import Decimal

import pytest

from scripts.live_strategy_scheduler import (
    SchedulerConfig,
    build_signal_id,
    load_environment,
    parse_interval_seconds,
    run_scheduler,
)
from src.application.usecases.trade import ExecuteTradeResult, TradeExecutionStatus
from src.domain.signal import Signal, SignalDirection
from src.domain.signal_generator import GeneratedSignal


class RecordingRuntime:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.signal_ids: list[str] = []

    def run_trade_execution_once(self, signal_id: str) -> ExecuteTradeResult:
        self.signal_ids.append(signal_id)
        if self.fail_first and len(self.signal_ids) == 1:
            raise RuntimeError("temporary exchange failure")
        return ExecuteTradeResult(
            status=TradeExecutionStatus.SKIPPED,
            generated_signal=GeneratedSignal(
                signal=Signal(
                    direction=SignalDirection.WAIT,
                    confidence=Decimal("0"),
                ),
                strategy_results=(),
            ),
            reason="non_entry_decision",
        )


def test_parse_interval_seconds_requires_positive_integer() -> None:
    assert parse_interval_seconds("15") == 15

    with pytest.raises(ValueError, match="positive"):
        parse_interval_seconds("0")


def test_build_signal_id_includes_prefix_timestamp_and_sequence() -> None:
    signal_id = build_signal_id(
        "live-compression-s2",
        datetime(2026, 7, 10, 12, 34, 56, tzinfo=timezone.utc),
        7,
    )

    assert signal_id == "live-compression-s2-20260710T123456Z-000007"


def test_load_environment_reads_dotenv_without_overriding_existing_values(
    tmp_path, monkeypatch
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "BINANCE_API_KEY=from-file\n"
        "BINANCE_API_SECRET=secret-from-file\n"
        "GPTRADER_SCHEDULER_INTERVAL_SECONDS=45\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BINANCE_API_KEY", "from-shell")
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)

    env = load_environment(dotenv_path)

    assert env["BINANCE_API_KEY"] == "from-shell"
    assert env["BINANCE_API_SECRET"] == "secret-from-file"
    assert env["GPTRADER_SCHEDULER_INTERVAL_SECONDS"] == "45"


def test_run_scheduler_triggers_runtime_at_configured_interval() -> None:
    runtime = RecordingRuntime()
    sleeps: list[float] = []
    lines: list[str] = []

    run_scheduler(
        runtime=runtime,
        config=SchedulerConfig(interval_seconds=60, signal_id_prefix="sig"),
        max_runs=2,
        now=lambda: datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
        sleep=sleeps.append,
        emit=lines.append,
    )

    assert runtime.signal_ids == [
        "sig-20260710T000000Z-000001",
        "sig-20260710T000000Z-000002",
    ]
    assert sleeps == [60]
    assert any("status=skipped" in line for line in lines)


def test_run_scheduler_logs_error_and_continues_next_tick() -> None:
    runtime = RecordingRuntime(fail_first=True)
    sleeps: list[float] = []
    lines: list[str] = []

    run_scheduler(
        runtime=runtime,
        config=SchedulerConfig(interval_seconds=30, signal_id_prefix="sig"),
        max_runs=2,
        now=lambda: datetime(2026, 7, 10, 0, 0, tzinfo=timezone.utc),
        sleep=sleeps.append,
        emit=lines.append,
    )

    assert len(runtime.signal_ids) == 2
    assert sleeps == [30]
    assert any("error=temporary exchange failure" in line for line in lines)
    assert any("status=skipped" in line for line in lines)


def test_live_scheduler_runtime_default_keeps_regime_selection_disabled() -> None:
    from src.runtime import RuntimeSettings

    settings = RuntimeSettings.from_env({})

    assert settings.regime_selection_enabled is False
    assert settings.regime_model_artifact_path is None
    assert settings.regime_mapping_artifact_path is None


def test_live_runtime_explicit_regime_composition_remains_legacy_four_hour_selector(
    tmp_path,
) -> None:
    from dataclasses import replace

    from src.infrastructure.regime import JsonRegimeArtifactRepository
    from src.runtime import RuntimeSettings, create_local_runtime
    from src.application.usecases.regime import SelectStrategyUseCase
    from tests.infrastructure.regime.test_json_regime_artifact_repository import (
        _mapping,
        _model,
    )

    original_model = _model()
    model = replace(
        original_model,
        distance_thresholds=(0.0,) + original_model.distance_thresholds[1:],
    )
    mapping = _mapping(model)
    artifacts = JsonRegimeArtifactRepository(tmp_path)
    artifacts.save_model(model)
    artifacts.save_mapping(mapping)
    runtime = create_local_runtime(RuntimeSettings(
        database_url=str(tmp_path / "state.sqlite3"),
        regime_selection_enabled=True,
        regime_model_artifact_path=str(tmp_path / "model.json"),
        regime_mapping_artifact_path=str(tmp_path / "mapping.json"),
        regime_candidate_definition_hash=mapping.candidate_definition_hash,
        regime_candidate_universe_hash=mapping.candidate_universe_hash,
        regime_data_provenance_hash=mapping.data_provenance_hash,
    ))

    usecase = runtime.regime_selection_scheduler._usecase
    assert isinstance(usecase, SelectStrategyUseCase)
    assert type(usecase).__module__.endswith("select_strategy_usecase")
