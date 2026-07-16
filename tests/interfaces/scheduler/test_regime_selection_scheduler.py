from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from concurrent.futures import ThreadPoolExecutor

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
from tests.application.usecases.regime.test_select_daily_strategy_usecase import (
    BOUNDARY as DAILY_BOUNDARY,
    COMPONENTS as DAILY_COMPONENTS,
    _FrozenModel,
    _candles as daily_candles,
    _command as daily_command,
)
from src.application.usecases.regime.select_daily_strategy_usecase import (
    DailySelectStrategyResult,
    SelectDailyStrategyUseCase,
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
        selection_input_hash="d" * 64,
    )


def test_selection_scheduler_commits_once_and_retry_returns_original_result() -> None:
    snapshot = SelectionArtifactSnapshot(
        model_artifact_hash="b" * 64,
        mapping_artifact_hash="c" * 64,
        cluster_strategy_mapping={"cluster-a": "alpha"},
        model_type="gmm",
        confidence_thresholds=SelectionConfidenceThresholds(
            model_type="gmm", gmm_probability_min=0.7, gmm_margin_min=0.2
        ),
    )
    command = SelectStrategyCommand(None, "BTCUSDT", START, snapshot, ClusterAssignment("cluster-a", 0.9, 0.1, None))
    result = SelectStrategyUseCase().execute(command)
    usecase = Mock()
    usecase.execute.return_value = result
    repository = Mock()
    repository.commit.return_value = result
    repository.load.return_value = None
    repository.find_committed_result.return_value = None
    factory = Mock(side_effect=lambda _previous: command)
    times = iter((START, FINISH, START, FINISH))
    scheduler = RegimeSelectionScheduler(usecase, repository, now=lambda: next(times))

    first = scheduler.run_selection("btc-regime", "BTCUSDT", factory)
    retry = scheduler.run_selection("btc-regime", "BTCUSDT", factory)

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
    usecase = Mock(wraps=SelectStrategyUseCase())
    scheduler = RegimeSelectionScheduler(usecase, repository, now=lambda: START)
    received_states = []

    def command_factory(previous):
        received_states.append(previous)
        return replace(command, previous_state=previous)

    first = scheduler.run_selection("btc-regime", "BTCUSDT", command_factory)
    retry = scheduler.run_selection("btc-regime", "BTCUSDT", command_factory)

    assert first.result == retry.result
    assert repository.list_events("BTCUSDT") == (
        SelectionEventType.CLASSIFICATION,
    )
    assert usecase.execute.call_count == 1
    assert received_states == [None, first.result.state]


def test_selection_scheduler_same_coordinate_different_assignment_conflicts(tmp_path) -> None:
    snapshot = SelectionArtifactSnapshot(
        model_artifact_hash="b" * 64,
        mapping_artifact_hash="c" * 64,
        cluster_strategy_mapping={"a": "alpha", "b": "beta"},
        model_type="gmm",
        confidence_thresholds=SelectionConfidenceThresholds(
            model_type="gmm", gmm_probability_min=0.7, gmm_margin_min=0.2
        ),
    )
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "state.sqlite3")
    scheduler = RegimeSelectionScheduler(SelectStrategyUseCase(), repository, now=lambda: START)
    make = lambda fingerprint: lambda previous: SelectStrategyCommand(
        previous, "BTCUSDT", START, snapshot,
        ClusterAssignment(fingerprint, 0.9, 0.1, None),
    )
    assert scheduler.run_selection("btc", "BTCUSDT", make("a")).succeeded
    conflict = scheduler.run_selection("btc", "BTCUSDT", make("b"))
    assert not conflict.succeeded
    assert isinstance(conflict.error, ValueError)
    assert "conflicting boundary commit" in str(conflict.error)


def test_concurrent_selection_schedulers_are_repository_idempotent(tmp_path) -> None:
    snapshot = SelectionArtifactSnapshot(
        model_artifact_hash="b" * 64,
        mapping_artifact_hash="c" * 64,
        cluster_strategy_mapping={"a": "alpha"},
        model_type="gmm",
        confidence_thresholds=SelectionConfidenceThresholds(
            model_type="gmm", gmm_probability_min=0.7, gmm_margin_min=0.2
        ),
    )
    path = tmp_path / "state.sqlite3"
    repositories = [SqliteRegimeSelectionStateRepository(path) for _ in range(2)]
    schedulers = [
        RegimeSelectionScheduler(SelectStrategyUseCase(), repository, now=lambda: START)
        for repository in repositories
    ]
    factory = lambda previous: SelectStrategyCommand(
        previous, "BTCUSDT", START, snapshot, ClusterAssignment("a", 0.9, 0.1, None)
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda scheduler: scheduler.run_selection(
                    "btc", "BTCUSDT", factory
                ),
                schedulers,
            )
        )
    assert all(result.succeeded for result in results)
    assert results[0].result == results[1].result
    assert repositories[0].list_events("BTCUSDT") == (
        SelectionEventType.CLASSIFICATION,
    )


def test_selection_scheduler_rejects_invalid_schedule_before_factory() -> None:
    factory = Mock()
    scheduler = RegimeSelectionScheduler(Mock(), Mock(), now=lambda: START)
    with pytest.raises(ValueError, match="schedule_name"):
        scheduler.run_selection(" ", "BTCUSDT", factory)
    factory.assert_not_called()


@pytest.mark.parametrize("failure_at", ["factory", "usecase", "repository"])
def test_selection_scheduler_surfaces_and_logs_each_exception(monkeypatch, failure_at) -> None:
    error = RuntimeError(failure_at)
    snapshot = SelectionArtifactSnapshot(
        model_artifact_hash="b" * 64,
        mapping_artifact_hash="c" * 64,
        cluster_strategy_mapping={"cluster-a": "alpha"},
        model_type="gmm",
        confidence_thresholds=SelectionConfidenceThresholds(
            model_type="gmm", gmm_probability_min=0.7, gmm_margin_min=0.2
        ),
    )
    command = SelectStrategyCommand(None, "BTCUSDT", START, snapshot, ClusterAssignment("cluster-a", 0.9, 0.1, None))
    result = SelectStrategyUseCase().execute(command)
    factory = Mock(side_effect=lambda _previous: command)
    usecase = Mock()
    usecase.execute.return_value = result
    repository = Mock()
    repository.load.return_value = None
    repository.find_committed_result.return_value = None
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
    ).run_selection("btc-regime", "BTCUSDT", factory)

    assert execution.error is error
    assert execution.result is None
    assert not execution.succeeded
    assert execution.finished_at == FINISH
    assert factory.call_count == 1
    logged.assert_called_once()


def test_scheduler_does_not_catch_base_exception() -> None:
    scheduler = RegimeSelectionScheduler(Mock(), Mock(), now=lambda: START)
    with pytest.raises(KeyboardInterrupt):
        scheduler.run_selection(
            "btc-regime", "BTCUSDT", Mock(side_effect=KeyboardInterrupt())
        )


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


def test_scheduler_accepts_daily_selector_and_commits_consecutive_midnights(tmp_path) -> None:
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "daily-state.sqlite3")
    scheduler = RegimeSelectionScheduler(
        SelectDailyStrategyUseCase(), repository, now=lambda: START
    )
    first = scheduler.run_selection(
        "daily-research", "BTCUSDT", lambda previous: daily_command(previous=previous)
    )
    second = scheduler.run_selection(
        "daily-research",
        "BTCUSDT",
        lambda previous: daily_command(
            previous=previous,
            boundary=DAILY_BOUNDARY + timedelta(days=1),
            candles=daily_candles(start=DAILY_BOUNDARY - timedelta(days=2)),
            model=_FrozenModel(
                ClusterAssignment(DAILY_COMPONENTS[1], 0.9, 0.05, None)
            ),
        ),
    )

    assert first.succeeded and second.succeeded
    assert isinstance(first.result, DailySelectStrategyResult)
    assert second.result.state.state_version == 2
    assert repository.load("BTCUSDT") == second.result.state
    assert repository.list_events("BTCUSDT") == (
        SelectionEventType.CLASSIFICATION,
        SelectionEventType.CLUSTER_TRANSITION,
    )


def test_scheduler_daily_duplicate_is_idempotent_and_conflict_is_rejected(tmp_path) -> None:
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "daily-retry.sqlite3")
    usecase = Mock(wraps=SelectDailyStrategyUseCase())
    scheduler = RegimeSelectionScheduler(usecase, repository, now=lambda: START)
    factory = lambda previous: daily_command(previous=previous)

    first = scheduler.run_selection("daily-research", "BTCUSDT", factory)
    retry = scheduler.run_selection("daily-research", "BTCUSDT", factory)
    conflicting_candles = list(daily_candles())
    conflicting_candles[0] = replace(
        conflicting_candles[0], volume=conflicting_candles[0].volume + 1
    )
    conflict = scheduler.run_selection(
        "daily-research",
        "BTCUSDT",
        lambda previous: daily_command(
            previous=previous,
            candles=tuple(conflicting_candles),
        ),
    )

    assert first.succeeded and retry.succeeded
    retry_base = (
        retry.result.base_result
        if isinstance(retry.result, DailySelectStrategyResult)
        else retry.result
    )
    assert retry_base == first.result.base_result
    assert usecase.execute.call_count == 1
    assert repository.list_events("BTCUSDT") == (SelectionEventType.CLASSIFICATION,)
    assert not conflict.succeeded
    assert "conflicting boundary commit" in str(conflict.error)
