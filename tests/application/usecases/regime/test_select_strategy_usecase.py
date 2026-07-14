from datetime import datetime, timedelta, timezone

import pytest

from src.application.usecases.regime.select_strategy_usecase import (
    SelectStrategyCommand,
    SelectStrategyUseCase,
)
from src.domain.regime.model import ClusterAssignment
from src.domain.regime.selection import (
    RegimeSelectionState,
    SelectionArtifactSnapshot,
    SelectionConfidenceThresholds,
    SelectionEventType,
)


UTC = timezone.utc
START = datetime(2026, 7, 13, 0, tzinfo=UTC)
MAPPING = {"a": "strategy-x", "b": "strategy-y"}
MODEL_HASH = "a" * 64
MAPPING_HASH = "b" * 64


def _snapshot(
    label: str = "artifact-v1",
    mapping: dict[str, str | None] | None = None,
    *,
    identity: str | None = None,
    model_type: str = "gmm",
    thresholds: SelectionConfidenceThresholds | None = None,
) -> SelectionArtifactSnapshot:
    discriminator = label.encode().hex()[-1]
    return SelectionArtifactSnapshot(
        model_artifact_hash=discriminator * 64,
        mapping_artifact_hash=MAPPING_HASH,
        cluster_strategy_mapping=MAPPING if mapping is None else mapping,
        artifact_identity=identity,
        model_type=model_type,
        confidence_thresholds=thresholds or _thresholds(model_type),
    )


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
    if len(artifact) != 64:
        artifact = _snapshot(artifact).artifact_identity
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
    snapshot: SelectionArtifactSnapshot | None = None,
    model_type: str = "gmm",
    boundary: datetime | None = None,
):
    if assignment is None:
        assignment = _assignment()
    if boundary is None:
        boundary = START if previous is None else previous.last_boundary_at + timedelta(hours=4)
    selected_mapping = MAPPING if mapping is None else mapping
    artifact_snapshot = snapshot or _snapshot(
        artifact, selected_mapping, model_type=model_type
    )
    return SelectStrategyUseCase().execute(
        SelectStrategyCommand(
            previous_state=previous,
            symbol="BTCUSDT",
            boundary_at=boundary,
            artifact_snapshot=artifact_snapshot,
            assignment=assignment,
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
    low = _assignment(dominant=0.6, second=0.4)
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

    result = _select(previous=cash, assignment=_assignment(dominant=0.6, second=0.4))

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
    previous = _state(artifact=_snapshot(mapping=mapping).artifact_identity)
    first = _select(previous=previous, assignment=_assignment("b"), mapping=mapping)

    result = _select(previous=first.state, assignment=_assignment("b"), mapping=mapping)

    assert result.events == (SelectionEventType.CLUSTER_TRANSITION,)


def test_confirmed_cluster_cash_mapping_has_separate_cluster_and_cash_events():
    mapping = {"a": "strategy-x", "b": None}
    previous = _state(artifact=_snapshot(mapping=mapping).artifact_identity)
    first = _select(previous=previous, assignment=_assignment("b"), mapping=mapping)

    result = _select(previous=first.state, assignment=_assignment("b"), mapping=mapping)

    assert result.state.active_strategy_profile_id is None
    assert result.events == (
        SelectionEventType.CLUSTER_TRANSITION,
        SelectionEventType.CASH_TRANSITION,
    )


def test_artifact_change_requires_two_new_confirmations():
    result = _select(previous=_state(), artifact="artifact-v2")

    assert result.state.artifact_version == _snapshot("artifact-v1").artifact_identity
    assert result.state.pending_artifact_version == _snapshot("artifact-v2").artifact_identity
    assert not result.state.new_entries_enabled
    assert result.state.pending_confirmation_count == 1
    assert result.events == (SelectionEventType.ENTRY_SUSPENDED,)


def test_second_matching_artifact_confirmation_commits_replacement():
    first = _select(previous=_state(), artifact="artifact-v2")

    result = _select(previous=first.state, artifact="artifact-v2")

    assert result.state.artifact_version == _snapshot("artifact-v2").artifact_identity
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
        assignment=_assignment(dominant=0.6, second=0.4),
        artifact="artifact-v2",
    )

    assert low.state.pending_artifact_version is None
    assert low.state.pending_confirmation_count == 0
    assert low.state.artifact_version == _snapshot("artifact-v1").artifact_identity

    restarted = _select(previous=low.state, artifact="artifact-v2")
    assert restarted.state.pending_confirmation_count == 1


def test_different_target_artifact_resets_candidate_even_for_same_cluster():
    first = _select(previous=_state(), artifact="artifact-v2")

    result = _select(previous=first.state, artifact="artifact-v3")

    assert result.state.pending_artifact_version == _snapshot("artifact-v3").artifact_identity
    assert result.state.pending_confirmation_count == 1
    assert result.state.artifact_version == _snapshot("artifact-v1").artifact_identity


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
        _snapshot(
            model_type="gmm",
            thresholds=_thresholds("kmeans"),
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
        artifact_version=_snapshot().artifact_identity,
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


def test_changed_mapping_content_forces_artifact_replacement_confirmation():
    old_snapshot = SelectionArtifactSnapshot(
        model_artifact_hash=MODEL_HASH,
        mapping_artifact_hash=MAPPING_HASH,
        cluster_strategy_mapping={"a": "strategy-x", "b": "strategy-y"},
        model_type="gmm",
        confidence_thresholds=_thresholds(),
    )
    changed_snapshot = SelectionArtifactSnapshot(
        model_artifact_hash=MODEL_HASH,
        mapping_artifact_hash=MAPPING_HASH,
        cluster_strategy_mapping={"a": "strategy-z", "b": "strategy-y"},
        model_type="gmm",
        confidence_thresholds=_thresholds(),
    )
    previous = _state(artifact=old_snapshot.artifact_identity)

    first = _select(previous=previous, snapshot=changed_snapshot)

    assert old_snapshot.artifact_identity != changed_snapshot.artifact_identity
    assert first.state.artifact_version == old_snapshot.artifact_identity
    assert first.state.pending_artifact_version == changed_snapshot.artifact_identity
    assert first.state.active_strategy_profile_id == "strategy-x"

    second = _select(previous=first.state, snapshot=changed_snapshot)
    assert second.state.artifact_version == changed_snapshot.artifact_identity
    assert second.state.active_strategy_profile_id == "strategy-z"


def test_forged_artifact_snapshot_identity_is_rejected():
    with pytest.raises(ValueError, match="artifact identity"):
        SelectionArtifactSnapshot(
            model_artifact_hash=MODEL_HASH,
            mapping_artifact_hash=MAPPING_HASH,
            cluster_strategy_mapping=MAPPING,
            artifact_identity="f" * 64,
            model_type="gmm",
            confidence_thresholds=_thresholds(),
        )


def test_artifact_snapshot_defensively_freezes_canonical_mapping():
    source = {"b": "strategy-y", "a": "strategy-x"}
    snapshot = SelectionArtifactSnapshot(
        model_artifact_hash=MODEL_HASH,
        mapping_artifact_hash=MAPPING_HASH,
        cluster_strategy_mapping=source,
        model_type="gmm",
        confidence_thresholds=_thresholds(),
    )

    source["a"] = "forged"

    assert tuple(snapshot.cluster_strategy_mapping) == ("a", "b")
    assert snapshot.cluster_strategy_mapping["a"] == "strategy-x"
    with pytest.raises(TypeError):
        snapshot.cluster_strategy_mapping["a"] = "forged"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"pending_artifact_version": "c" * 64, "new_entries_enabled": True},
        {"consecutive_low_confidence_count": 3, "new_entries_enabled": False},
        {"consecutive_low_confidence_count": 1, "new_entries_enabled": True},
        {
            "consecutive_low_confidence_count": 2,
            "new_entries_enabled": False,
            "active_strategy_profile_id": "strategy-x",
        },
    ],
)
def test_selection_state_rejects_stricter_transition_invariants(kwargs):
    values = dict(
        symbol="BTCUSDT",
        artifact_version=_snapshot().artifact_identity,
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
    if kwargs.get("pending_artifact_version") is not None:
        values.update(pending_cluster_fingerprint="a", pending_confirmation_count=1)
    values.update(kwargs)
    with pytest.raises(ValueError):
        RegimeSelectionState(**values)


def test_artifact_observation_does_not_repeat_suspension_when_already_suspended():
    previous = _state(entries=False, low_count=1)

    result = _select(previous=previous, artifact="artifact-v2")

    assert result.events == (SelectionEventType.CLASSIFICATION,)


def test_artifact_observation_from_cash_does_not_emit_suspension():
    previous = _state(strategy=None, entries=False)

    result = _select(previous=previous, artifact="artifact-v2")

    assert result.events == (SelectionEventType.CLASSIFICATION,)


def test_artifact_target_reset_does_not_repeat_suspension_while_pending():
    first = _select(previous=_state(), artifact="artifact-v2")

    result = _select(previous=first.state, artifact="artifact-v3")

    assert result.events == (SelectionEventType.CLASSIFICATION,)


@pytest.mark.parametrize("boundary", ["2026-07-13T00:00:00Z", 123])
def test_invalid_boundary_type_fails_with_value_error(boundary):
    with pytest.raises(ValueError, match="four-hour UTC boundary"):
        _select(boundary=boundary)


@pytest.mark.parametrize("boundary", ["2026-07-13T00:00:00Z", 123, None])
def test_persisted_selection_state_rejects_invalid_boundary_type(boundary):
    with pytest.raises(ValueError, match="last_boundary_at must be a four-hour UTC boundary"):
        RegimeSelectionState(
            symbol="BTCUSDT",
            artifact_version=_snapshot().artifact_identity,
            current_cluster_fingerprint="a",
            active_strategy_profile_id="strategy-x",
            pending_cluster_fingerprint=None,
            pending_confirmation_count=0,
            consecutive_low_confidence_count=0,
            new_entries_enabled=True,
            last_boundary_at=boundary,
            state_version=1,
        )


@pytest.mark.parametrize(
    "values",
    [
        (True, 0.1, None),
        (0.9, False, None),
        (0.9, 0.1, True),
    ],
)
def test_cluster_assignment_rejects_boolean_numerics(values):
    with pytest.raises(ValueError):
        ClusterAssignment("a", *values)


def test_changed_confidence_threshold_forces_new_artifact_identity():
    original = _snapshot()
    changed = _snapshot(
        thresholds=SelectionConfidenceThresholds(
            model_type="gmm",
            gmm_probability_min=0.71,
            gmm_margin_min=0.2,
        )
    )

    assert changed.artifact_identity != original.artifact_identity
    with pytest.raises(ValueError, match="artifact identity"):
        _snapshot(
            identity=original.artifact_identity,
            thresholds=changed.confidence_thresholds,
        )

    previous = _state(artifact=original.artifact_identity)
    first = _select(previous=previous, snapshot=changed)
    assert first.state.artifact_version == original.artifact_identity
    assert first.state.pending_artifact_version == changed.artifact_identity
    assert first.state.pending_confirmation_count == 1
    assert not first.state.new_entries_enabled

    second = _select(previous=first.state, snapshot=changed)
    assert second.state.artifact_version == changed.artifact_identity


def test_changed_model_type_forces_new_artifact_identity():
    gmm = _snapshot()
    kmeans = _snapshot(model_type="kmeans")

    assert gmm.artifact_identity != kmeans.artifact_identity


def test_command_cannot_override_frozen_confidence_policy():
    assert "model_type" not in SelectStrategyCommand.__dataclass_fields__
    assert "confidence_thresholds" not in SelectStrategyCommand.__dataclass_fields__


def test_gmm_decimal_boundary_is_inclusive_without_binary_subtraction_error():
    snapshot = _snapshot(
        thresholds=SelectionConfidenceThresholds(
            model_type="gmm",
            gmm_probability_min=0.7,
            gmm_margin_min=0.5,
        )
    )

    result = _select(
        snapshot=snapshot,
        assignment=_assignment(dominant=0.7, second=0.2),
    )

    assert result.state.active_strategy_profile_id == "strategy-x"
    assert result.state.new_entries_enabled


@pytest.mark.parametrize(
    "assignment",
    [
        _assignment(dominant=0.699999999999, second=0.199999999999),
        _assignment(dominant=0.7, second=0.200000000001),
    ],
)
def test_gmm_just_below_probability_or_margin_is_low(assignment):
    snapshot = _snapshot(
        thresholds=SelectionConfidenceThresholds(
            model_type="gmm",
            gmm_probability_min=0.7,
            gmm_margin_min=0.5,
        )
    )

    result = _select(snapshot=snapshot, assignment=assignment)

    assert result.state.active_strategy_profile_id is None
    assert not result.state.new_entries_enabled


def test_cluster_assignment_rejects_impossible_top_two_probability_sum():
    with pytest.raises(ValueError, match="sum"):
        ClusterAssignment("a", 0.8, 0.7, None)


def test_cluster_assignment_allows_tight_roundoff_at_probability_sum_one():
    assignment = ClusterAssignment("a", 0.8, 0.2000000000005, None)

    assert assignment.fingerprint == "a"
