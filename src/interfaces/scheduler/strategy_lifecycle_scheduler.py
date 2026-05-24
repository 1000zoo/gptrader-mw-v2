from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from src.application.usecases.strategy_lifecycle import (
    RunStrategyLifecycleCommand,
    RunStrategyLifecycleResult,
    RunStrategyLifecycleUseCase,
)


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


class StrategyLifecycleScheduler:
    def __init__(
        self,
        run_strategy_lifecycle_usecase: RunStrategyLifecycleUseCase,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._run_strategy_lifecycle_usecase = run_strategy_lifecycle_usecase
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
        try:
            command = command_factory()
            result = self._run_strategy_lifecycle_usecase.execute(command)
        except Exception as exc:
            error = exc
        return ScheduledStrategyLifecycleRun(
            schedule_name=schedule_name,
            started_at=started_at,
            finished_at=self._now(),
            command=command,
            result=result,
            error=error,
        )
