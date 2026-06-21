from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TypeVar

from src.application.usecases.trade import (
    ClosePositionCommand,
    ClosePositionResult,
    ClosePositionUseCase,
    ExecuteTradeCommand,
    ExecuteTradeResult,
    ExecuteTradeUseCase,
    SyncPositionCommand,
    SyncPositionResult,
    SyncPositionUseCase,
)
from src.observability.logging import runtime_logger


CommandT = TypeVar("CommandT")
ResultT = TypeVar("ResultT")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ScheduledTradeExecution:
    schedule_name: str
    started_at: datetime
    finished_at: datetime
    command: ExecuteTradeCommand | None = None
    result: ExecuteTradeResult | None = None
    error: Exception | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ScheduledPositionClose:
    schedule_name: str
    started_at: datetime
    finished_at: datetime
    command: ClosePositionCommand | None = None
    result: ClosePositionResult | None = None
    error: Exception | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ScheduledPositionSync:
    schedule_name: str
    started_at: datetime
    finished_at: datetime
    command: SyncPositionCommand | None = None
    result: SyncPositionResult | None = None
    error: Exception | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class TradeScheduler:
    def __init__(
        self,
        execute_trade_usecase: ExecuteTradeUseCase,
        close_position_usecase: ClosePositionUseCase,
        sync_position_usecase: SyncPositionUseCase,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._execute_trade_usecase = execute_trade_usecase
        self._close_position_usecase = close_position_usecase
        self._sync_position_usecase = sync_position_usecase
        self._now = now or _utc_now

    def run_trade_execution(
        self,
        schedule_name: str,
        command_factory: Callable[[], ExecuteTradeCommand],
    ) -> ScheduledTradeExecution:
        started_at = self._now()
        command: ExecuteTradeCommand | None = None
        result: ExecuteTradeResult | None = None
        error: Exception | None = None
        runtime_logger.info("trade scheduler execution started", schedule_name=schedule_name)
        try:
            command = command_factory()
            result = self._execute_trade_usecase.execute(command)
        except Exception as exc:
            error = exc
            runtime_logger.exception(
                "trade scheduler execution failed",
                schedule_name=schedule_name,
                error=str(exc),
            )
        else:
            runtime_logger.info(
                "trade scheduler execution succeeded",
                schedule_name=schedule_name,
                status=getattr(getattr(result, "status", None), "value", None),
            )
        return ScheduledTradeExecution(
            schedule_name=schedule_name,
            started_at=started_at,
            finished_at=self._now(),
            command=command,
            result=result,
            error=error,
        )

    def close_position(
        self,
        schedule_name: str,
        command_factory: Callable[[], ClosePositionCommand],
    ) -> ScheduledPositionClose:
        started_at = self._now()
        command: ClosePositionCommand | None = None
        result: ClosePositionResult | None = None
        error: Exception | None = None
        runtime_logger.info("position close scheduler started", schedule_name=schedule_name)
        try:
            command = command_factory()
            result = self._close_position_usecase.close(command)
        except Exception as exc:
            error = exc
            runtime_logger.exception(
                "position close scheduler failed",
                schedule_name=schedule_name,
                error=str(exc),
            )
        else:
            runtime_logger.info(
                "position close scheduler succeeded",
                schedule_name=schedule_name,
                status=getattr(getattr(result, "status", None), "value", None),
            )
        return ScheduledPositionClose(
            schedule_name=schedule_name,
            started_at=started_at,
            finished_at=self._now(),
            command=command,
            result=result,
            error=error,
        )

    def sync_position(
        self,
        schedule_name: str,
        command_factory: Callable[[], SyncPositionCommand],
    ) -> ScheduledPositionSync:
        started_at = self._now()
        command: SyncPositionCommand | None = None
        result: SyncPositionResult | None = None
        error: Exception | None = None
        runtime_logger.info("position sync scheduler started", schedule_name=schedule_name)
        try:
            command = command_factory()
            result = self._sync_position_usecase.sync(command)
        except Exception as exc:
            error = exc
            runtime_logger.exception(
                "position sync scheduler failed",
                schedule_name=schedule_name,
                error=str(exc),
            )
        else:
            runtime_logger.info(
                "position sync scheduler succeeded",
                schedule_name=schedule_name,
                applied_report_count=len(getattr(result, "applied_reports", ())),
            )
        return ScheduledPositionSync(
            schedule_name=schedule_name,
            started_at=started_at,
            finished_at=self._now(),
            command=command,
            result=result,
            error=error,
        )
