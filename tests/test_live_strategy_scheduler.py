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
