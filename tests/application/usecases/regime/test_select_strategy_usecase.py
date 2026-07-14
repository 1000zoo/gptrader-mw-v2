from datetime import datetime, timedelta, timezone

import pytest

from src.application.usecases.regime.select_strategy_usecase import (
    SelectStrategyCommand,
    SelectStrategyUseCase,
    SelectionConfidenceThresholds,
)
from src.domain.regime.model import ClusterAssignment
from src.domain.regime.selection import RegimeSelectionState, SelectionEventType


UTC = timezone.utc
START = datetime(2026, 7, 13, 0, tzinfo=UTC)
MAPPING = {"a": "strategy-x", "b": "strategy-y"}


def _assignment(
    fingerprint: str = "a",
    *,
    dominant: float = 0.9,
    second: float = 0.1,
    distance: float | None = None,
) -> ClusterAssignment:
    return ClusterAssignment(fingerprint, dominant, second, distance)


def _thresholds(model_type: str = "gmm") -> SelectionConfidenceThresholds:
    if model_type == "gmm":
        return SelectionConfidenceThresholds(
            model_type="gmm", gmm_probability_min=0.7, gmm_margin_min=0.2
        )
    return SelectionConfidenceThresholds(
        model_type="kmeans", kmeans_max_standardized_distance=1.5
    )


def _state(
    *,
    artifact: str = "artifact-v1",
    cluster: str | None = "a",
    strategy: str | None = "strategy-x",
    entries: bool = True,
    boundary: datetime = START,
    version: int = 1,
    pending_cluster: str | None = None,
    pending_count: int = 0,
    pending_artifact: str | None = None,
    low_count: int = 0,
) -> RegimeSelectionState:
    return RegimeSelectionState(
        symbol="BTCUSDT",
        artifact_version=artifact,
        current_cluster_fingerprint=cluster,
        active_strategy_profile_id=strategy,
        pending_cluster_fingerprint=pending_cluster,
        pending_confirmation_count=pending_count,
        consecutive_low_confidence_count=low_count,
        new_entries_enabled=entries,
        last_boundary_at=boundary,
        state_version=version,
        pending_artifact_version=pending_artifact,
    )


def _select(
    *,
    previous: RegimeSelectionState | None = None,
    assignment: ClusterAssignment | None = None,
    mapping: dict[str, str | None] | None = None,
    artifact: str = "artifact-v1",
    model_type: str = "gmm",
    boundary: datetime | None = None,
):
    if assignment is None:
        assignment = _assignment()
    if boundary is None:
        boundary = START if previous is None else previous.last_boundary_at + timedelta(hours=4)
    return SelectStrategyUseCase().execute(
        SelectStrategyCommand(
            previous_state=previous,
            symbol="BTCUSDT",
            boundary_at=boundary,
            target_artifact_version=artifact,
            model_type=model_type,
            confidence_thresholds=_thresholds(model_type),
            assignment=assignment,
            cluster_strategy_mapping=MAPPING if mapping is None else mapping,
        )
    )


def test_initial_high_confidence_selects_mapped_strategy_immediately():
    result = _select()

    assert result.expected_state_version == 0
    assert result.state.active_strategy_profile_id == "strategy-x"
    assert result.state.current_cluster_fingerprint == "a"
    assert result.state.new_entries_enabled
    assert result.state.state_version == 1
    assert result.events == (SelectionEventType.CLASSIFICATION,)


def test_new_cluster_requires_two_consecutive_observations():
    first = _select(previous=_state(), assignment=_assignment("b"))

    assert first.state.active_strategy_profile_id == "strategy-x"
    assert first.state.pending_cluster_fingerprint == "b"
    assert first.state.pending_confirmation_count == 1

    second = _select(previous=first.state, assignment=_assignment("b"))
    assert second.state.active_strategy_profile_id == "strategy-y"
    assert second.state.current_cluster_fingerprint == "b"
    assert second.state.pending_cluster_fingerprint is None
    assert second.events == (
        SelectionEventType.CLUSTER_TRANSITION,
        SelectionEventType.STRATEGY_TRANSITION,
    )


def test_different_candidate_resets_normal_confirmation():
    pending_b = _select(previous=_state(), assignment=_assignment("b")).state

    result = _select(previous=pending_b, assignment=_assignment("c"), mapping={**MAPPING, "c": None})

    assert result.state.pending_cluster_fingerprint == "c"
    assert result.state.pending_confirmation_count == 1
    assert result.state.current_cluster_fingerprint == "a"


def test_first_low_confidence_disables_entries_and_second_commits_cash():
    low = _assignment(dominant=0.6, second=0.5)
    first = _select(previous=_state(), assignment=low)

    assert not first.state.new_entries_enabled
    assert first.state.active_strategy_profile_id == "strategy-x"
    assert first.events == (SelectionEventType.ENTRY_SUSPENDED,)

    second = _select(previous=first.state, assignment=low)
    assert second.state.active_strategy_profile_id is None
    assert second.state.current_cluster_fingerprint == "a"
    assert second.events == (SelectionEventType.CASH_TRANSITION,)


def test_repeated_low_confidence_does_not_emit_duplicate_cash_transition():
    cash = _state(strategy=None, entries=False, low_count=2)

    result = _select(previous=cash, assignment=_assignment(dominant=0.6, second=0.5))

    assert result.state.consecutive_low_confidence_count == 2
    assert result.events == (SelectionEventType.CLASSIFICATION,)


def test_high_confidence_return_to_current_cluster_reenables_entries():
    suspended = _state(entries=False, low_count=1)

    result = _select(previous=suspended)

    assert result.state.active_strategy_profile_id == "strategy-x"
    assert result.state.new_entries_enabled
    assert result.state.consecutive_low_confidence_count == 0


def test_cluster_change_to_same_strategy_is_not_strategy_switch():
    mapping = {"a": "strategy-x", "b": "strategy-x"}
    first = _select(previous=_state(), assignment=_assignment("b"), mapping=mapping)

    result = _select(previous=first.state, assignment=_assignment("b"), mapping=mapping)

    assert result.events == (SelectionEventType.CLUSTER_TRANSITION,)


def test_confirmed_cluster_cash_mapping_has_separate_cluster_and_cash_events():
    mapping = {"a": "strategy-x", "b": None}
    first = _select(previous=_state(), assignment=_assignment("b"), mapping=mapping)

    result = _select(previous=first.state, assignment=_assignment("b"), mapping=mapping)

    assert result.state.active_strategy_profile_id is None
    assert result.events == (
        SelectionEventType.CLUSTER_TRANSITION,
        SelectionEventType.CASH_TRANSITION,
    )


def test_artifact_change_requires_two_new_confirmations():
    result = _select(previous=_state(), artifact="artifact-v2")

    assert result.state.artifact_version == "artifact-v1"
    assert result.state.pending_artifact_version == "artifact-v2"
    assert not result.state.new_entries_enabled
    assert result.state.pending_confirmation_count == 1
    assert result.events == (SelectionEventType.ENTRY_SUSPENDED,)


def test_second_matching_artifact_confirmation_commits_replacement():
    first = _select(previous=_state(), artifact="artifact-v2")

    result = _select(previous=first.state, artifact="artifact-v2")

    assert result.state.artifact_version == "artifact-v2"
    assert result.state.pending_artifact_version is None
    assert result.state.new_entries_enabled
    assert result.events == (SelectionEventType.ARTIFACT_REPLACED,)


def test_artifact_replacement_emits_ordered_cluster_and_strategy_transitions():
    first = _select(previous=_state(), assignment=_assignment("b"), artifact="artifact-v2")

    result = _select(previous=first.state, assignment=_assignment("b"), artifact="artifact-v2")

    assert result.events == (
        SelectionEventType.ARTIFACT_REPLACED,
        SelectionEventType.CLUSTER_TRANSITION,
        SelectionEventType.STRATEGY_TRANSITION,
    )


def test_low_between_artifact_confirmations_resets_candidate():
    first = _select(previous=_state(), artifact="artifact-v2")
    low = _select(
        previous=first.state,
        assignment=_assignment(dominant=0.6, second=0.5),
        artifact="artifact-v2",
    )

    assert low.state.pending_artifact_version is None
    assert low.state.pending_confirmation_count == 0
    assert low.state.artifact_version == "artifact-v1"

    restarted = _select(previous=low.state, artifact="artifact-v2")
    assert restarted.state.pending_confirmation_count == 1


def test_different_target_artifact_resets_candidate_even_for_same_cluster():
    first = _select(previous=_state(), artifact="artifact-v2")

    result = _select(previous=first.state, artifact="artifact-v3")

    assert result.state.pending_artifact_version == "artifact-v3"
    assert result.state.pending_confirmation_count == 1
    assert result.state.artifact_version == "artifact-v1"


def test_kmeans_confidence_uses_distance_only():
    high = _select(
        model_type="kmeans",
        assignment=_assignment(dominant=0.1, second=0.1, distance=1.5),
    )
    low = _select(
        previous=high.state,
        model_type="kmeans",
        assignment=_assignment(distance=1.5001),
    )

    assert high.state.active_strategy_profile_id == "strategy-x"
    assert low.events == (SelectionEventType.ENTRY_SUSPENDED,)


@pytest.mark.parametrize(
    ("boundary", "message"),
    [
        (START + timedelta(hours=1), "four-hour UTC boundary"),
        (START.replace(tzinfo=None), "four-hour UTC boundary"),
    ],
)
def test_rejects_noncanonical_boundary(boundary, message):
    with pytest.raises(ValueError, match=message):
        _select(boundary=boundary)


def test_rejects_equal_or_stale_boundary():
    with pytest.raises(ValueError, match="strictly after"):
        _select(previous=_state(), boundary=START)


def test_rejects_assignment_missing_from_mapping():
    with pytest.raises(ValueError, match="assignment fingerprint"):
        _select(assignment=_assignment("missing"))


def test_rejects_model_threshold_mismatch_and_missing_kmeans_distance():
    with pytest.raises(ValueError, match="model type"):
        SelectStrategyUseCase().execute(
            SelectStrategyCommand(
                previous_state=None,
                symbol="BTCUSDT",
                boundary_at=START,
                target_artifact_version="artifact-v1",
                model_type="gmm",
                confidence_thresholds=_thresholds("kmeans"),
                assignment=_assignment(),
                cluster_strategy_mapping=MAPPING,
            )
        )

    with pytest.raises(ValueError, match="distance"):
        _select(model_type="kmeans", assignment=_assignment(distance=None))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"symbol": "btcusdt"},
        {"pending_cluster_fingerprint": "b", "pending_confirmation_count": 0},
        {"pending_cluster_fingerprint": None, "pending_confirmation_count": 1},
        {"active_strategy_profile_id": "strategy-x", "current_cluster_fingerprint": None},
        {"new_entries_enabled": True, "active_strategy_profile_id": None},
        {"state_version": True},
    ],
)
def test_selection_state_rejects_invalid_invariants(kwargs):
    values = dict(
        symbol="BTCUSDT",
        artifact_version="artifact-v1",
        current_cluster_fingerprint="a",
        active_strategy_profile_id="strategy-x",
        pending_cluster_fingerprint=None,
        pending_confirmation_count=0,
        consecutive_low_confidence_count=0,
        new_entries_enabled=True,
        last_boundary_at=START,
        state_version=1,
        pending_artifact_version=None,
    )
    values.update(kwargs)

    with pytest.raises(ValueError):
        RegimeSelectionState(**values)
