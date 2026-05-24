from datetime import datetime, timezone

from src.interfaces.scheduler.trade_scheduler import TradeScheduler


class RecordingExecuteTradeUseCase:
    def __init__(self, result: object | None = None, error: Exception | None = None) -> None:
        self.result = result or object()
        self.error = error
        self.commands: list[object] = []

    def execute(self, command: object) -> object:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.result


class RecordingClosePositionUseCase:
    def __init__(self, result: object | None = None) -> None:
        self.result = result or object()
        self.commands: list[object] = []

    def close(self, command: object) -> object:
        self.commands.append(command)
        return self.result


class RecordingSyncPositionUseCase:
    def __init__(self, result: object | None = None) -> None:
        self.result = result or object()
        self.commands: list[object] = []

    def sync(self, command: object) -> object:
        self.commands.append(command)
        return self.result


def test_run_trade_execution_calls_execute_usecase_with_factory_command() -> None:
    command = object()
    result = object()
    execute_usecase = RecordingExecuteTradeUseCase(result=result)
    scheduler = TradeScheduler(
        execute_trade_usecase=execute_usecase,
        close_position_usecase=RecordingClosePositionUseCase(),
        sync_position_usecase=RecordingSyncPositionUseCase(),
        now=lambda: datetime(2026, 5, 25, 1, 2, 3, tzinfo=timezone.utc),
    )

    execution = scheduler.run_trade_execution(
        schedule_name="btc-1m-entry",
        command_factory=lambda: command,
    )

    assert execute_usecase.commands == [command]
    assert execution.schedule_name == "btc-1m-entry"
    assert execution.command is command
    assert execution.result is result
    assert execution.error is None
    assert execution.succeeded is True
    assert execution.started_at == datetime(2026, 5, 25, 1, 2, 3, tzinfo=timezone.utc)
    assert execution.finished_at == datetime(2026, 5, 25, 1, 2, 3, tzinfo=timezone.utc)


def test_close_position_calls_close_usecase() -> None:
    command = object()
    result = object()
    close_usecase = RecordingClosePositionUseCase(result=result)
    scheduler = TradeScheduler(
        execute_trade_usecase=RecordingExecuteTradeUseCase(),
        close_position_usecase=close_usecase,
        sync_position_usecase=RecordingSyncPositionUseCase(),
    )

    execution = scheduler.close_position(
        schedule_name="close-btc",
        command_factory=lambda: command,
    )

    assert close_usecase.commands == [command]
    assert execution.command is command
    assert execution.result is result
    assert execution.succeeded is True


def test_sync_position_calls_sync_usecase() -> None:
    command = object()
    result = object()
    sync_usecase = RecordingSyncPositionUseCase(result=result)
    scheduler = TradeScheduler(
        execute_trade_usecase=RecordingExecuteTradeUseCase(),
        close_position_usecase=RecordingClosePositionUseCase(),
        sync_position_usecase=sync_usecase,
    )

    execution = scheduler.sync_position(
        schedule_name="sync-btc-position",
        command_factory=lambda: command,
    )

    assert sync_usecase.commands == [command]
    assert execution.command is command
    assert execution.result is result
    assert execution.succeeded is True


def test_run_trade_execution_captures_usecase_error() -> None:
    command = object()
    error = RuntimeError("exchange unavailable")
    execute_usecase = RecordingExecuteTradeUseCase(error=error)
    scheduler = TradeScheduler(
        execute_trade_usecase=execute_usecase,
        close_position_usecase=RecordingClosePositionUseCase(),
        sync_position_usecase=RecordingSyncPositionUseCase(),
    )

    execution = scheduler.run_trade_execution(
        schedule_name="btc-1m-entry",
        command_factory=lambda: command,
    )

    assert execute_usecase.commands == [command]
    assert execution.command is command
    assert execution.result is None
    assert execution.error is error
    assert execution.succeeded is False


def test_run_trade_execution_captures_command_factory_error() -> None:
    error = ValueError("missing settings")
    execute_usecase = RecordingExecuteTradeUseCase()
    scheduler = TradeScheduler(
        execute_trade_usecase=execute_usecase,
        close_position_usecase=RecordingClosePositionUseCase(),
        sync_position_usecase=RecordingSyncPositionUseCase(),
    )

    execution = scheduler.run_trade_execution(
        schedule_name="btc-1m-entry",
        command_factory=lambda: (_ for _ in ()).throw(error),
    )

    assert execution.error is error
    assert execution.command is None
    assert execution.result is None
    assert execution.succeeded is False
    assert execute_usecase.commands == []
