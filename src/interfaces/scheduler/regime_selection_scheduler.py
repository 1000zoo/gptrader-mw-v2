from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from src.application.usecases.regime.select_strategy_usecase import (
    SelectStrategyCommand,
    SelectStrategyUseCase,
    selection_command_input_hash,
)
from src.domain.ports.regime_selection_state_repository_port import (
    RegimeSelectionStateRepositoryPort,
)
from src.domain.regime.selection import RegimeSelectionState, SelectStrategyResult
from src.observability.logging import runtime_logger


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ScheduledRegimeSelection:
    schedule_name: str
    started_at: datetime
    finished_at: datetime
    result: SelectStrategyResult | None = None
    error: Exception | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.schedule_name, str)
            or not self.schedule_name
            or self.schedule_name != self.schedule_name.strip()
        ):
            raise ValueError("schedule_name must be a nonempty canonical string")
        for value in (self.started_at, self.finished_at):
            if not isinstance(value, datetime) or value.tzinfo is not timezone.utc:
                raise ValueError("scheduler timestamps must use canonical UTC")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")
        if (self.result is None) == (self.error is None):
            raise ValueError("exactly one of result or error is required")
        if self.result is not None and not isinstance(self.result, SelectStrategyResult):
            raise ValueError("result must be a SelectStrategyResult")
        if self.error is not None and not isinstance(self.error, Exception):
            raise ValueError("error must be an Exception")

    @property
    def succeeded(self) -> bool:
        return self.error is None


class RegimeSelectionScheduler:
    def __init__(
        self,
        usecase: SelectStrategyUseCase,
        repository: RegimeSelectionStateRepositoryPort,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._usecase = usecase
        self._repository = repository
        self._now = now or _utc_now

    def run_selection(
        self,
        schedule_name: str,
        symbol: str,
        command_factory: Callable[[RegimeSelectionState | None], SelectStrategyCommand],
    ) -> ScheduledRegimeSelection:
        if (
            not isinstance(schedule_name, str)
            or not schedule_name
            or schedule_name != schedule_name.strip()
        ):
            raise ValueError("schedule_name must be a nonempty canonical string")
        started_at = self._now()
        runtime_logger.info(
            "regime selection scheduler started", schedule_name=schedule_name
        )
        try:
            previous_state = self._repository.load(symbol)
            command = command_factory(previous_state)
            if not isinstance(command, SelectStrategyCommand):
                raise ValueError("command factory must return a SelectStrategyCommand")
            if command.symbol != symbol:
                raise ValueError("selection command symbol must match scheduler symbol")
            input_hash = selection_command_input_hash(command)
            existing = self._repository.find_committed_result(
                symbol,
                command.boundary_at,
                command.artifact_snapshot.artifact_identity,
            )
            if existing is not None:
                if existing.selection_input_hash != input_hash:
                    raise ValueError("conflicting boundary commit")
                result = existing
            else:
                proposed = self._usecase.execute(command)
                if proposed.selection_input_hash != input_hash:
                    raise ValueError("selection result input hash does not match command")
                result = self._repository.commit(
                    proposed.expected_state_version,
                    proposed,
                )
        except Exception as exc:
            runtime_logger.exception(
                "regime selection scheduler failed",
                schedule_name=schedule_name,
                error=str(exc),
            )
            return ScheduledRegimeSelection(
                schedule_name=schedule_name,
                started_at=started_at,
                finished_at=self._now(),
                error=exc,
            )
        runtime_logger.info(
            "regime selection scheduler succeeded",
            schedule_name=schedule_name,
            symbol=result.state.symbol,
            state_version=result.state.state_version,
        )
        return ScheduledRegimeSelection(
            schedule_name=schedule_name,
            started_at=started_at,
            finished_at=self._now(),
            result=result,
        )


__all__ = ["RegimeSelectionScheduler", "ScheduledRegimeSelection"]
