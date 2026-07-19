from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from src.application.usecases.strategy_lifecycle import (
    RunStrategyBacktestCycleCommand,
    RunStrategyBacktestCycleResult,
    RunStrategyBacktestCycleUseCase,
    RunStrategyLifecycleCommand,
    RunStrategyLifecycleResult,
    RunStrategyLifecycleUseCase,
)
from src.observability.logging import runtime_logger


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ScheduledStrategyLifecycleRun:
    schedule_name: str
    started_at: datetime
    finished_at: datetime
    command: RunStrategyLifecycleCommand | None = None
    result: RunStrategyLifecycleResult | None = None
    error: Exception | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ScheduledStrategyBacktestCycleRun:
    schedule_name: str
    started_at: datetime
    finished_at: datetime
    command: RunStrategyBacktestCycleCommand | None = None
    result: RunStrategyBacktestCycleResult | None = None
    error: Exception | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class StrategyLifecycleScheduler:
    def __init__(
        self,
        run_strategy_lifecycle_usecase: RunStrategyLifecycleUseCase,
        now: Callable[[], datetime] | None = None,
        run_strategy_backtest_cycle_usecase: (
            RunStrategyBacktestCycleUseCase | None
        ) = None,
    ) -> None:
        self._run_strategy_lifecycle_usecase = run_strategy_lifecycle_usecase
        self._run_strategy_backtest_cycle_usecase = run_strategy_backtest_cycle_usecase
        self._now = now or _utc_now

    def run_lifecycle(
        self,
        schedule_name: str,
        command_factory: Callable[[], RunStrategyLifecycleCommand],
    ) -> ScheduledStrategyLifecycleRun:
        started_at = self._now()
        command: RunStrategyLifecycleCommand | None = None
        result: RunStrategyLifecycleResult | None = None
        error: Exception | None = None
        runtime_logger.info(
            "strategy lifecycle scheduler started",
            schedule_name=schedule_name,
        )
        try:
            command = command_factory()
            result = self._run_strategy_lifecycle_usecase.execute(command)
        except Exception as exc:
            error = exc
            runtime_logger.exception(
                "strategy lifecycle scheduler failed",
                schedule_name=schedule_name,
                error=str(exc),
            )
        else:
            runtime_logger.info(
                "strategy lifecycle scheduler succeeded",
                schedule_name=schedule_name,
                target_id=getattr(command, "target_id", None),
            )
        return ScheduledStrategyLifecycleRun(
            schedule_name=schedule_name,
            started_at=started_at,
            finished_at=self._now(),
            command=command,
            result=result,
            error=error,
        )

    def run_backtest_cycle(
        self,
        schedule_name: str,
        command_factory: Callable[[], RunStrategyBacktestCycleCommand],
    ) -> ScheduledStrategyBacktestCycleRun:
        started_at = self._now()
        command: RunStrategyBacktestCycleCommand | None = None
        result: RunStrategyBacktestCycleResult | None = None
        error: Exception | None = None
        runtime_logger.info(
            "strategy backtest cycle scheduler started",
            schedule_name=schedule_name,
        )
        try:
            command = command_factory()
            if self._run_strategy_backtest_cycle_usecase is None:
                raise RuntimeError(
                    "run_strategy_backtest_cycle_usecase is not configured"
                )
            result = self._run_strategy_backtest_cycle_usecase.execute(command)
        except Exception as exc:
            error = exc
            runtime_logger.exception(
                "strategy backtest cycle scheduler failed",
                schedule_name=schedule_name,
                error=str(exc),
            )
        else:
            runtime_logger.info(
                "strategy backtest cycle scheduler succeeded",
                schedule_name=schedule_name,
                cycle_id=getattr(command, "cycle_id", None),
                succeeded_count=getattr(result, "succeeded_count", None),
                failed_count=getattr(result, "failed_count", None),
            )
        return ScheduledStrategyBacktestCycleRun(
            schedule_name=schedule_name,
            started_at=started_at,
            finished_at=self._now(),
            command=command,
            result=result,
            error=error,
        )
