from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from src.domain.regime.selection import (
    RegimeSelectionState,
    SelectionEventType,
    SelectStrategyResult,
)
from src.application.usecases.regime.select_strategy_usecase import (
    SelectStrategyCommand,
    SelectStrategyUseCase,
)
from src.domain.regime.model import ClusterAssignment
from src.domain.regime.selection import (
    SelectionArtifactSnapshot,
    SelectionConfidenceThresholds,
)
from src.infrastructure.persistence import SqliteRegimeSelectionStateRepository
from src.interfaces.scheduler.regime_selection_scheduler import (
    RegimeSelectionScheduler,
    ScheduledRegimeSelection,
)


UTC = timezone.utc
START = datetime(2026, 7, 13, 0, tzinfo=UTC)
FINISH = datetime(2026, 7, 13, 0, 0, 1, tzinfo=UTC)


def _result() -> SelectStrategyResult:
    return SelectStrategyResult(
        expected_state_version=0,
        state=RegimeSelectionState(
            symbol="BTCUSDT",
            artifact_version="a" * 64,
            current_cluster_fingerprint="cluster-a",
            active_strategy_profile_id="alpha",
            pending_cluster_fingerprint=None,
            pending_confirmation_count=0,
            consecutive_low_confidence_count=0,
            new_entries_enabled=True,
            last_boundary_at=START,
            state_version=1,
        ),
        events=(SelectionEventType.CLASSIFICATION,),
        evaluated_artifact_identity="a" * 64,
    )


def test_selection_scheduler_commits_once_and_retry_returns_original_result() -> None:
    command = object()
    result = _result()
    usecase = Mock()
    usecase.execute.return_value = result
    repository = Mock()
    repository.commit.return_value = result
    factory = Mock(return_value=command)
    times = iter((START, FINISH, START, FINISH))
    scheduler = RegimeSelectionScheduler(usecase, repository, now=lambda: next(times))

    first = scheduler.run_selection("btc-regime", factory)
    retry = scheduler.run_selection("btc-regime", factory)

    assert first.result is result
    assert retry.result is result
    assert factory.call_count == 2
    assert usecase.execute.call_count == 2
    assert repository.commit.call_count == 2
    repository.commit.assert_called_with(0, result)
    assert first.succeeded and retry.succeeded
    assert first.started_at == START and first.finished_at == FINISH


def test_selection_scheduler_real_repository_retry_persists_one_event(tmp_path) -> None:
    snapshot = SelectionArtifactSnapshot(
        model_artifact_hash="b" * 64,
        mapping_artifact_hash="c" * 64,
        cluster_strategy_mapping={"cluster-a": "alpha"},
        model_type="gmm",
        confidence_thresholds=SelectionConfidenceThresholds(
            model_type="gmm", gmm_probability_min=0.7, gmm_margin_min=0.2
        ),
    )
    command = SelectStrategyCommand(
        previous_state=None,
        symbol="BTCUSDT",
        boundary_at=START,
        artifact_snapshot=snapshot,
        assignment=ClusterAssignment("cluster-a", 0.9, 0.1, None),
    )
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "state.sqlite3")
    scheduler = RegimeSelectionScheduler(
        SelectStrategyUseCase(), repository, now=lambda: START
    )

    first = scheduler.run_selection("btc-regime", lambda: command)
    retry = scheduler.run_selection("btc-regime", lambda: command)

    assert first.result == retry.result
    assert repository.list_events("BTCUSDT") == (
        SelectionEventType.CLASSIFICATION,
    )


def test_selection_scheduler_rejects_invalid_schedule_before_factory() -> None:
    factory = Mock()
    scheduler = RegimeSelectionScheduler(Mock(), Mock(), now=lambda: START)
    with pytest.raises(ValueError, match="schedule_name"):
        scheduler.run_selection(" ", factory)
    factory.assert_not_called()


@pytest.mark.parametrize("failure_at", ["factory", "usecase", "repository"])
def test_selection_scheduler_surfaces_and_logs_each_exception(monkeypatch, failure_at) -> None:
    error = RuntimeError(failure_at)
    command = object()
    result = _result()
    factory = Mock(return_value=command)
    usecase = Mock()
    usecase.execute.return_value = result
    repository = Mock()
    repository.commit.return_value = result
    if failure_at == "factory":
        factory.side_effect = error
    elif failure_at == "usecase":
        usecase.execute.side_effect = error
    else:
        repository.commit.side_effect = error
    logged = Mock()
    monkeypatch.setattr(
        "src.interfaces.scheduler.regime_selection_scheduler.runtime_logger.exception",
        logged,
    )
    times = iter((START, FINISH))

    execution = RegimeSelectionScheduler(
        usecase, repository, now=lambda: next(times)
    ).run_selection("btc-regime", factory)

    assert execution.error is error
    assert execution.result is None
    assert not execution.succeeded
    assert execution.finished_at == FINISH
    assert factory.call_count == 1
    logged.assert_called_once()


def test_scheduler_does_not_catch_base_exception() -> None:
    scheduler = RegimeSelectionScheduler(Mock(), Mock(), now=lambda: START)
    with pytest.raises(KeyboardInterrupt):
        scheduler.run_selection("btc-regime", Mock(side_effect=KeyboardInterrupt()))


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"schedule_name": " ", "result": _result()}, "schedule_name"),
        (
            {
                "schedule_name": "btc",
                "started_at": START.replace(tzinfo=None),
                "result": _result(),
            },
            "canonical UTC",
        ),
        (
            {
                "schedule_name": "btc",
                "started_at": FINISH,
                "finished_at": START,
                "result": _result(),
            },
            "finished_at",
        ),
        ({"schedule_name": "btc"}, "exactly one"),
        (
            {
                "schedule_name": "btc",
                "result": _result(),
                "error": RuntimeError("x"),
            },
            "exactly one",
        ),
    ],
)
def test_scheduled_selection_validates_invariants(kwargs, message) -> None:
    values = {"started_at": START, "finished_at": FINISH, **kwargs}
    with pytest.raises(ValueError, match=message):
        ScheduledRegimeSelection(**values)
