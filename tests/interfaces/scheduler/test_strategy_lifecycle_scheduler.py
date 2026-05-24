from datetime import datetime, timezone

from src.interfaces.scheduler.strategy_lifecycle_scheduler import (
    StrategyLifecycleScheduler,
)


class RecordingRunStrategyLifecycleUseCase:
    def __init__(self, result: object | None = None) -> None:
        self.result = result or object()
        self.commands: list[object] = []

    def execute(self, command: object) -> object:
        self.commands.append(command)
        return self.result


def test_run_lifecycle_calls_usecase_with_factory_command() -> None:
    command = object()
    result = object()
    usecase = RecordingRunStrategyLifecycleUseCase(result=result)
    scheduler = StrategyLifecycleScheduler(
        run_strategy_lifecycle_usecase=usecase,
        now=lambda: datetime(2026, 5, 25, 2, 3, 4, tzinfo=timezone.utc),
    )

    execution = scheduler.run_lifecycle(
        schedule_name="daily-promotion-check",
        command_factory=lambda: command,
    )

    assert usecase.commands == [command]
    assert execution.schedule_name == "daily-promotion-check"
    assert execution.command is command
    assert execution.result is result
    assert execution.error is None
    assert execution.succeeded is True
    assert execution.started_at == datetime(2026, 5, 25, 2, 3, 4, tzinfo=timezone.utc)
    assert execution.finished_at == datetime(2026, 5, 25, 2, 3, 4, tzinfo=timezone.utc)


def test_run_lifecycle_captures_command_factory_error_before_usecase_call() -> None:
    error = ValueError("missing policy")
    usecase = RecordingRunStrategyLifecycleUseCase()
    scheduler = StrategyLifecycleScheduler(
        run_strategy_lifecycle_usecase=usecase,
    )

    execution = scheduler.run_lifecycle(
        schedule_name="daily-promotion-check",
        command_factory=lambda: (_ for _ in ()).throw(error),
    )

    assert usecase.commands == []
    assert execution.command is None
    assert execution.result is None
    assert execution.error is error
    assert execution.succeeded is False
