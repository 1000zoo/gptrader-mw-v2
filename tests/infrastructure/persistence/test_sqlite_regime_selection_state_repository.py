import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from src.domain.ports import ConcurrentSelectionStateError
from src.domain.regime.selection import (
    RegimeSelectionState,
    SelectionEventType,
    SelectStrategyResult,
)
from src.infrastructure.persistence import SqliteRegimeSelectionStateRepository


UTC = timezone.utc
START = datetime(2026, 7, 13, 0, tzinfo=UTC)
ARTIFACT_1 = "a" * 64
ARTIFACT_2 = "b" * 64


def _result(
    *,
    expected: int = 0,
    boundary: datetime = START,
    artifact: str = ARTIFACT_1,
    evaluated_artifact: str | None = None,
    cluster: str | None = "cluster-a",
    strategy: str | None = "strategy-a",
    pending_cluster: str | None = None,
    pending_count: int = 0,
    pending_artifact: str | None = None,
    low_count: int = 0,
    entries: bool = True,
    events: tuple[SelectionEventType, ...] = (SelectionEventType.CLASSIFICATION,),
) -> SelectStrategyResult:
    return SelectStrategyResult(
        expected_state_version=expected,
        state=RegimeSelectionState(
            symbol="BTCUSDT",
            artifact_version=artifact,
            current_cluster_fingerprint=cluster,
            active_strategy_profile_id=strategy,
            pending_cluster_fingerprint=pending_cluster,
            pending_confirmation_count=pending_count,
            consecutive_low_confidence_count=low_count,
            new_entries_enabled=entries,
            last_boundary_at=boundary,
            state_version=expected + 1,
            pending_artifact_version=pending_artifact,
        ),
        events=events,
        evaluated_artifact_identity=(
            artifact if evaluated_artifact is None else evaluated_artifact
        ),
    )


def test_same_boundary_retry_returns_original_commit_once(tmp_path):
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "selection.sqlite3")
    decision = _result()

    first = repository.commit(0, decision)
    retry = repository.commit(0, decision)

    assert retry == first
    assert repository.load("BTCUSDT") == decision.state
    assert repository.list_events("BTCUSDT") == decision.events


def test_conflicting_duplicate_boundary_is_rejected(tmp_path):
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "selection.sqlite3")
    repository.commit(0, _result())

    with pytest.raises(ValueError, match="conflicting boundary commit"):
        repository.commit(0, _result(strategy="strategy-b"))

    assert repository.list_events("BTCUSDT") == (SelectionEventType.CLASSIFICATION,)


def test_same_boundary_different_pending_artifact_is_a_conflict(tmp_path):
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "selection.sqlite3")
    first = _result(
        pending_cluster="cluster-a",
        pending_count=1,
        pending_artifact=ARTIFACT_2,
        evaluated_artifact=ARTIFACT_2,
        entries=False,
        events=(SelectionEventType.ENTRY_SUSPENDED,),
    )
    repository.commit(0, first)
    conflicting = _result(
        pending_cluster="cluster-a",
        pending_count=1,
        pending_artifact="c" * 64,
        evaluated_artifact=ARTIFACT_2,
        entries=False,
        events=(SelectionEventType.ENTRY_SUSPENDED,),
    )

    with pytest.raises(ValueError, match="conflicting boundary commit"):
        repository.commit(0, conflicting)


@pytest.mark.parametrize(
    "decision",
    [
        _result(
            evaluated_artifact=ARTIFACT_2,
            pending_cluster="cluster-a",
            pending_count=1,
            pending_artifact=ARTIFACT_2,
            entries=False,
            events=(SelectionEventType.ENTRY_SUSPENDED,),
        ),
        _result(
            evaluated_artifact=ARTIFACT_2,
            low_count=1,
            entries=False,
            events=(SelectionEventType.ENTRY_SUSPENDED,),
        ),
    ],
    ids=("replacement-first-high", "replacement-low"),
)
def test_replacement_observation_is_keyed_by_evaluated_artifact(tmp_path, decision):
    path = tmp_path / "selection.sqlite3"
    repository = SqliteRegimeSelectionStateRepository(path)

    committed = repository.commit(0, decision)
    retry = repository.commit(0, decision)

    with sqlite3.connect(path) as connection:
        stored_artifact = connection.execute(
            "SELECT artifact_version FROM regime_selection_events"
        ).fetchone()[0]
    assert committed.state.artifact_version == ARTIFACT_1
    assert committed.evaluated_artifact_identity == ARTIFACT_2
    assert stored_artifact == ARTIFACT_2
    assert retry == committed


def test_stale_state_version_cannot_increment_pending_confirmation_twice(tmp_path):
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "selection.sqlite3")
    first = _result(
        pending_cluster="cluster-b",
        pending_count=1,
        entries=False,
        events=(SelectionEventType.ENTRY_SUSPENDED,),
    )
    repository.commit(0, first)
    different_boundary_from_same_prior = _result(
        boundary=START + timedelta(hours=4),
        pending_cluster="cluster-b",
        pending_count=1,
        entries=False,
        events=(SelectionEventType.ENTRY_SUSPENDED,),
    )

    with pytest.raises(ConcurrentSelectionStateError):
        repository.commit(0, different_boundary_from_same_prior)

    assert repository.load("BTCUSDT") == first.state


def test_historical_exact_retry_returns_original_without_reverting_latest_state(tmp_path):
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "selection.sqlite3")
    first = _result()
    second = _result(expected=1, boundary=START + timedelta(hours=4))
    repository.commit(0, first)
    repository.commit(1, second)

    retry = repository.commit(0, first)

    assert retry == first
    assert repository.load("BTCUSDT") == second.state
    assert repository.list_events("BTCUSDT") == first.events + second.events


def test_reopen_roundtrips_all_state_fields_and_flattens_events_in_order(tmp_path):
    path = tmp_path / "selection.sqlite3"
    first = _result(
        pending_cluster="cluster-a",
        pending_count=1,
        pending_artifact=ARTIFACT_2,
        entries=False,
        events=(SelectionEventType.ENTRY_SUSPENDED,),
    )
    second = _result(
        expected=1,
        boundary=START + timedelta(hours=4),
        artifact=ARTIFACT_2,
        cluster="cluster-b",
        strategy=None,
        entries=False,
        events=(
            SelectionEventType.ARTIFACT_REPLACED,
            SelectionEventType.CLUSTER_TRANSITION,
            SelectionEventType.CASH_TRANSITION,
        ),
    )
    repository = SqliteRegimeSelectionStateRepository(path)
    repository.commit(0, first)
    repository.commit(1, second)

    reopened = SqliteRegimeSelectionStateRepository(path)

    assert reopened.load("BTCUSDT") == second.state
    assert reopened.list_events("BTCUSDT") == first.events + second.events
    assert reopened.load("ETHUSDT") is None
    assert reopened.list_events("ETHUSDT") == ()


@pytest.mark.parametrize(
    "decision",
    [
        _result(events=(SelectionEventType.CLASSIFICATION,)),
        _result(entries=False, events=(SelectionEventType.ENTRY_SUSPENDED,)),
        _result(events=(SelectionEventType.CLUSTER_TRANSITION,)),
        _result(events=(SelectionEventType.STRATEGY_TRANSITION,)),
        _result(strategy=None, entries=False, events=(SelectionEventType.CASH_TRANSITION,)),
        _result(events=(SelectionEventType.ARTIFACT_REPLACED,)),
        _result(
            strategy=None,
            entries=False,
            low_count=2,
            events=(SelectionEventType.CLASSIFICATION,),
        ),
    ],
)
def test_roundtrips_each_event_type(tmp_path, decision):
    repository = SqliteRegimeSelectionStateRepository(
        tmp_path / f"{decision.events[0].value}.sqlite3"
    )

    assert repository.commit(0, decision) == decision
    assert repository.list_events("BTCUSDT") == decision.events


def test_two_repository_instances_concurrently_commit_same_decision_once(tmp_path):
    path = tmp_path / "selection.sqlite3"
    repositories = (
        SqliteRegimeSelectionStateRepository(path),
        SqliteRegimeSelectionStateRepository(path),
    )
    decision = _result()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(repository.commit, 0, decision) for repository in repositories]
        committed = [future.result(timeout=10) for future in futures]

    assert committed == [decision, decision]
    assert repositories[0].list_events("BTCUSDT") == decision.events


def test_schema_initialization_is_concurrent_and_idempotent(tmp_path):
    path = tmp_path / "nested" / "selection.sqlite3"

    with ThreadPoolExecutor(max_workers=2) as executor:
        repositories = list(
            executor.map(SqliteRegimeSelectionStateRepository, (path, path))
        )

    assert [repository.load("BTCUSDT") for repository in repositories] == [None, None]


def test_concurrent_different_decisions_have_one_winner_and_one_conflict(tmp_path):
    path = tmp_path / "selection.sqlite3"
    repositories = (
        SqliteRegimeSelectionStateRepository(path),
        SqliteRegimeSelectionStateRepository(path),
    )
    decisions = (_result(strategy="strategy-a"), _result(strategy="strategy-b"))

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(repository.commit, 0, decision)
            for repository, decision in zip(repositories, decisions)
        ]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result(timeout=10))
            except ValueError as error:
                outcomes.append(error)

    assert sum(isinstance(item, SelectStrategyResult) for item in outcomes) == 1
    errors = [item for item in outcomes if isinstance(item, ValueError)]
    assert len(errors) == 1
    assert "conflicting boundary commit" in str(errors[0])
    assert len(repositories[0].list_events("BTCUSDT")) == 1


@pytest.mark.parametrize("expected", [-1, True, 1.5, "0"])
def test_commit_rejects_invalid_expected_version(tmp_path, expected):
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "selection.sqlite3")

    with pytest.raises(ValueError, match="expected_state_version"):
        repository.commit(expected, _result())


def test_commit_rejects_mismatched_expected_argument(tmp_path):
    repository = SqliteRegimeSelectionStateRepository(tmp_path / "selection.sqlite3")

    with pytest.raises(ValueError, match="expected_state_version"):
        repository.commit(1, _result())


def test_repository_rejects_directory_database_path(tmp_path):
    with pytest.raises(ValueError, match="database path"):
        SqliteRegimeSelectionStateRepository(tmp_path)


def test_load_detects_tampered_state_hash(tmp_path):
    path = tmp_path / "selection.sqlite3"
    repository = SqliteRegimeSelectionStateRepository(path)
    repository.commit(0, _result())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE regime_selection_states SET state_hash = ? WHERE symbol = ?",
            ("0" * 64, "BTCUSDT"),
        )

    with pytest.raises(ValueError, match="state.*integrity"):
        repository.load("BTCUSDT")


def test_load_rejects_unknown_state_json_key_even_with_matching_hash(tmp_path):
    path = tmp_path / "selection.sqlite3"
    repository = SqliteRegimeSelectionStateRepository(path)
    repository.commit(0, _result())
    with sqlite3.connect(path) as connection:
        original = connection.execute(
            "SELECT state_json FROM regime_selection_states WHERE symbol = 'BTCUSDT'"
        ).fetchone()[0]
        forged = original[:-1] + ',"unknown":1}'
        connection.execute(
            "UPDATE regime_selection_states SET state_json = ?, state_hash = ? WHERE symbol = ?",
            (forged, hashlib.sha256(forged.encode()).hexdigest(), "BTCUSDT"),
        )

    with pytest.raises(ValueError, match="state.*keys"):
        repository.load("BTCUSDT")


def test_list_events_detects_tampered_result_payload(tmp_path):
    path = tmp_path / "selection.sqlite3"
    repository = SqliteRegimeSelectionStateRepository(path)
    repository.commit(0, _result())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE regime_selection_events SET result_json = result_json || ' '"
        )

    with pytest.raises(ValueError, match="decision.*integrity"):
        repository.list_events("BTCUSDT")


def test_retry_detects_tampered_existing_decision_before_idempotency(tmp_path):
    path = tmp_path / "selection.sqlite3"
    repository = SqliteRegimeSelectionStateRepository(path)
    decision = _result()
    repository.commit(0, decision)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE regime_selection_events SET decision_hash = ?",
            ("0" * 64,),
        )

    with pytest.raises(ValueError, match="decision.*integrity"):
        repository.commit(0, decision)


@pytest.mark.parametrize(
    ("column", "value", "query_symbol"),
    [
        ("symbol", "ETHUSDT", "ETHUSDT"),
        ("boundary_at", "2026-07-13T04:00:00+00:00", "BTCUSDT"),
        ("artifact_version", ARTIFACT_2, "BTCUSDT"),
        ("expected_version", 1, "BTCUSDT"),
        ("committed_version", 2, "BTCUSDT"),
    ],
)
def test_list_events_rejects_tampered_coordinate_columns(
    tmp_path, column, value, query_symbol
):
    path = tmp_path / "selection.sqlite3"
    repository = SqliteRegimeSelectionStateRepository(path)
    repository.commit(0, _result())
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"UPDATE regime_selection_events SET {column} = ?",
            (value,),
        )

    with pytest.raises(ValueError, match="decision.*row|coordinate"):
        repository.list_events(query_symbol)


def test_retry_rejects_tampered_coordinate_columns_before_idempotency(tmp_path):
    path = tmp_path / "selection.sqlite3"
    repository = SqliteRegimeSelectionStateRepository(path)
    decision = _result()
    repository.commit(0, decision)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE regime_selection_events SET committed_version = 2"
        )

    with pytest.raises(ValueError, match="decision.*row|coordinate"):
        repository.commit(0, decision)


def test_state_write_failure_rolls_back_inserted_event(tmp_path):
    path = tmp_path / "selection.sqlite3"
    repository = SqliteRegimeSelectionStateRepository(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_selection_state_insert
            BEFORE INSERT ON regime_selection_states
            BEGIN
                SELECT RAISE(ABORT, 'state write rejected');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="state write rejected"):
        repository.commit(0, _result())

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM regime_selection_events"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM regime_selection_states"
        ).fetchone()[0] == 0


def test_rejects_noncanonical_duplicate_json_keys_with_matching_hash(tmp_path):
    path = tmp_path / "selection.sqlite3"
    repository = SqliteRegimeSelectionStateRepository(path)
    repository.commit(0, _result())
    duplicate = '{"expected_state_version":0,"expected_state_version":0,"events":["classification"],"state":{}}'
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE regime_selection_events SET result_json = ?, decision_hash = ?",
            (duplicate, hashlib.sha256(duplicate.encode()).hexdigest()),
        )

    with pytest.raises(ValueError, match="duplicate|canonical|decision"):
        repository.list_events("BTCUSDT")
