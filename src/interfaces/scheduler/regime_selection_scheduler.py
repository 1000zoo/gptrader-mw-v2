from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar, runtime_checkable

from src.application.usecases.regime.select_strategy_usecase import (
    SelectStrategyCommand,
    selection_command_input_hash,
)
from src.domain.ports.regime_selection_state_repository_port import (
    RegimeSelectionStateRepositoryPort,
)
from src.domain.regime.selection import (
    AuditedSelectStrategyResult,
    RegimeSelectionState,
    SelectionEventType,
    SelectStrategyResult,
)
from src.observability.logging import runtime_logger


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@runtime_checkable
class RegimeSelectionResultPort(Protocol):
    """Observable selector result shared by canonical and audited decisions."""

    @property
    def state(self) -> RegimeSelectionState: ...

    @property
    def events(self) -> tuple[SelectionEventType, ...]: ...

    @property
    def selection_input_hash(self) -> str: ...


CommandT = TypeVar("CommandT", contravariant=True)
ResultT = TypeVar("ResultT", bound=RegimeSelectionResultPort, covariant=True)


class RegimeSelectorPort(Protocol[CommandT, ResultT]):
    """Structural selector boundary shared by production and research selectors."""

    def execute(self, command: CommandT) -> ResultT:
        ...


def _command_input_hash(command: object) -> str:
    if isinstance(command, SelectStrategyCommand):
        return selection_command_input_hash(command)
    value = getattr(command, "selection_input_hash", None)
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("selection command must expose a lowercase SHA256 input hash")
    return value


def _base_result(result: RegimeSelectionResultPort) -> SelectStrategyResult:
    if not isinstance(result, RegimeSelectionResultPort):
        raise ValueError("selector must return a structural selection result")
    if not isinstance(result.state, RegimeSelectionState):
        raise ValueError("selection result state must be canonical")
    if (
        not isinstance(result.events, tuple)
        or not result.events
        or any(not isinstance(event, SelectionEventType) for event in result.events)
    ):
        raise ValueError("selection result events must be canonical")
    if isinstance(result, SelectStrategyResult):
        return result
    base = getattr(result, "base_result", None)
    if not isinstance(base, SelectStrategyResult):
        raise ValueError("selector must return a canonical selection result")
    return base


@dataclass(frozen=True)
class ScheduledRegimeSelection:
    schedule_name: str
    started_at: datetime
    finished_at: datetime
    result: RegimeSelectionResultPort | None = None
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
        if self.result is not None:
            _base_result(self.result)
        if self.error is not None and not isinstance(self.error, Exception):
            raise ValueError("error must be an Exception")

    @property
    def succeeded(self) -> bool:
        return self.error is None


class RegimeSelectionScheduler:
    def __init__(
        self,
        usecase: RegimeSelectorPort[Any, RegimeSelectionResultPort],
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
        command_factory: Callable[[RegimeSelectionState | None], object],
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
            if getattr(command, "symbol", None) != symbol:
                raise ValueError("selection command symbol must match scheduler symbol")
            boundary_at = getattr(command, "boundary_at", None)
            artifact_snapshot = getattr(command, "artifact_snapshot", None)
            if not isinstance(boundary_at, datetime) or artifact_snapshot is None:
                raise ValueError("command factory must return a regime selection command")
            input_hash = _command_input_hash(command)
            requires_audit = getattr(command, "requires_audited_result", False)
            if type(requires_audit) is not bool:
                raise ValueError("requires_audited_result must be a strict boolean")
            if requires_audit:
                find_audited = getattr(self._repository, "find_committed_audited", None)
                commit_audited = getattr(self._repository, "commit_audited", None)
                if not callable(find_audited) or not callable(commit_audited):
                    raise ValueError("audited selection requires an audited repository")
                existing = find_audited(
                    symbol, boundary_at, artifact_snapshot.artifact_identity
                )
            else:
                existing = self._repository.find_committed_result(
                    symbol,
                    boundary_at,
                    artifact_snapshot.artifact_identity,
                )
            if existing is not None:
                if existing.selection_input_hash != input_hash:
                    raise ValueError("conflicting boundary commit")
                result = existing
            else:
                proposed = self._usecase.execute(command)
                proposed_base = _base_result(proposed)
                if proposed_base.selection_input_hash != input_hash:
                    raise ValueError("selection result input hash does not match command")
                if requires_audit:
                    if not isinstance(proposed, AuditedSelectStrategyResult):
                        raise ValueError("audited selection must return an audited result")
                    committed = commit_audited(
                        proposed_base.expected_state_version, proposed
                    )
                else:
                    committed = self._repository.commit(
                        proposed_base.expected_state_version,
                        proposed_base,
                    )
                if requires_audit:
                    result = (
                        proposed
                        if committed.base_result == proposed.base_result
                        and committed.audit_record == proposed.audit_record
                        else committed
                    )
                else:
                    result = proposed if committed == proposed_base else committed
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


__all__ = [
    "RegimeSelectionResultPort",
    "RegimeSelectionScheduler",
    "RegimeSelectorPort",
    "ScheduledRegimeSelection",
]
