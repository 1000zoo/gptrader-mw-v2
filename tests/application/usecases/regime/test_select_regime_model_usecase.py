import inspect
from dataclasses import FrozenInstanceError

import pytest

from src.application.usecases.regime.select_regime_model_usecase import (
    RegimeModelFamilyWinner,
    RegimeModelEvidence,
    RegimeModelGateThresholds,
    SelectRegimeModelCommand,
    SelectRegimeModelUseCase,
)


def _evidence(
    artifact_id: str,
    *,
    model_type: str = "kmeans",
    weekly_counts: tuple[int, ...] = (20, 12, 15),
    month_counts: tuple[int, ...] = (5, 4, 5),
    seed_ari: float = 0.95,
    seed_nmi: float = 0.94,
    centroid_distance: float = 0.15,
    prevalence_drift: float = 0.08,
    low_confidence_rate: float = 0.1,
    silhouette: float | None = 0.42,
    bic: float | None = None,
) -> RegimeModelEvidence:
    if model_type == "gmm" and silhouette == 0.42:
        silhouette = None
        bic = 100.0 if bic is None else bic
    return RegimeModelEvidence(
        artifact_id=artifact_id,
        model_type=model_type,
        cluster_fingerprints=tuple(f"cluster-{index}" for index in range(len(weekly_counts))),
        weekly_episode_counts=weekly_counts,
        distinct_calendar_month_counts=month_counts,
        seed_ari=seed_ari,
        seed_nmi=seed_nmi,
        matched_centroid_distance=centroid_distance,
        prevalence_drift=prevalence_drift,
        low_confidence_rate=low_confidence_rate,
        silhouette=silhouette,
        bic=bic,
    )


def _select(*candidates: RegimeModelEvidence, **command_kwargs):
    return SelectRegimeModelUseCase().execute(
        SelectRegimeModelCommand(candidates=tuple(candidates), **command_kwargs)
    )


def test_model_is_rejected_when_one_cluster_has_fewer_than_eight_weekly_episodes():
    result = _select(_evidence("sparse", weekly_counts=(20, 7, 15)))

    assert not result.decisions[0].eligible
    assert "minimum_weekly_episodes" in result.decisions[0].rejection_reasons
    assert result.selected_artifact_id is None


def test_strategy_results_cannot_enter_model_selection():
    signature = inspect.signature(SelectRegimeModelCommand)

    assert "strategy_results" not in signature.parameters
    assert all("strategy" not in name for name in signature.parameters)


def test_ordered_gates_precede_information_criterion():
    candidate = _evidence(
        "unstable-low-bic",
        model_type="gmm",
        seed_ari=0.2,
        seed_nmi=0.3,
        bic=-1_000_000.0,
    )

    result = _select(candidate)

    assert not result.decisions[0].eligible
    assert result.decisions[0].rejection_reasons[0] == "seed_stability"


def test_negative_adjusted_rand_index_is_valid_evidence_but_fails_stability_gate():
    candidate = _evidence("negative-ari", seed_ari=-0.2)

    decision = _select(candidate).decisions[0]

    assert not decision.eligible
    assert "seed_stability" in decision.rejection_reasons


def test_all_rejection_reasons_accumulate_in_gate_order():
    candidate = _evidence(
        "bad-all-gates",
        weekly_counts=(7, 9, 9),
        month_counts=(2, 4, 4),
        seed_ari=0.1,
        seed_nmi=0.1,
        centroid_distance=9.0,
        prevalence_drift=0.9,
        low_confidence_rate=0.9,
        silhouette=None,
    )

    decision = _select(candidate).decisions[0]

    assert decision.rejection_reasons == (
        "minimum_weekly_episodes",
        "minimum_distinct_months",
        "seed_stability",
        "centroid_stability",
        "prevalence_drift",
        "low_confidence_rate",
        "family_metric_validity",
    )


def test_within_family_ranking_and_ties_are_deterministic():
    lower = _evidence("k-lower", silhouette=0.41)
    tie_z = _evidence("k-z", silhouette=0.5)
    tie_a = _evidence("k-a", silhouette=0.5)
    gmm_high = _evidence("g-high", model_type="gmm", bic=90.0)
    gmm_low = _evidence("g-low", model_type="gmm", bic=80.0)

    result = _select(gmm_high, tie_z, lower, gmm_low, tie_a)

    assert result.family_winners == (
        RegimeModelFamilyWinner("kmeans", "k-a", "silhouette", 0.5),
        RegimeModelFamilyWinner("gmm", "g-low", "bic", 80.0),
    )
    assert result.selected_artifact_id == "k-a"
    assert tuple(decision.artifact_id for decision in result.decisions) == (
        "g-high",
        "g-low",
        "k-a",
        "k-lower",
        "k-z",
    )


def test_family_priority_is_explicit_and_never_compares_bic_to_silhouette():
    kmeans = _evidence("k", silhouette=-0.5)
    gmm = _evidence("g", model_type="gmm", bic=-999_999.0)

    default = _select(kmeans, gmm)
    gmm_first = _select(kmeans, gmm, model_family_priority=("gmm", "kmeans"))

    assert default.model_family_priority == ("kmeans", "gmm")
    assert default.selected_artifact_id == "k"
    assert gmm_first.selected_artifact_id == "g"
    assert gmm_first.winning_artifact_id == "g"


def test_non_ranking_diagnostic_metric_is_allowed_but_ignored_for_family_ranking():
    k_better = _evidence("k-better", silhouette=0.5, bic=999_999.0)
    k_worse = _evidence("k-worse", silhouette=0.4, bic=-999_999.0)
    g_better = _evidence("g-better", model_type="gmm", silhouette=-1.0, bic=10.0)
    g_worse = _evidence("g-worse", model_type="gmm", silhouette=1.0, bic=20.0)

    result = _select(k_worse, g_worse, k_better, g_better)

    assert result.family_winners == (
        RegimeModelFamilyWinner("kmeans", "k-better", "silhouette", 0.5),
        RegimeModelFamilyWinner("gmm", "g-better", "bic", 10.0),
    )


def test_selection_is_independent_of_input_order_and_all_rejected_returns_none():
    a = _evidence("a", silhouette=0.3)
    b = _evidence("b", silhouette=0.4)

    assert _select(a, b) == _select(b, a)
    rejected = _evidence("bad", weekly_counts=(1, 1, 1), month_counts=(1, 1, 1))
    assert _select(rejected).selected_artifact_id is None


@pytest.mark.parametrize(
    ("model_type", "silhouette", "bic"),
    [
        ("kmeans", None, None),
        ("gmm", None, None),
    ],
)
def test_missing_or_wrong_family_metric_fails_closed(model_type, silhouette, bic):
    candidate = _evidence(
        "metric-invalid",
        model_type=model_type,
        silhouette=silhouette,
        bic=bic,
    )

    decision = _select(candidate).decisions[0]

    assert not decision.eligible
    assert decision.rejection_reasons[-1] == "family_metric_validity"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model_type": "dbscan"},
        {"weekly_counts": (8, True, 8)},
        {"weekly_counts": (8, 8), "month_counts": (3, 3, 3)},
        {"seed_ari": float("nan")},
        {"seed_nmi": 1.1},
        {"centroid_distance": -0.1},
        {"prevalence_drift": -0.1},
        {"low_confidence_rate": 1.1},
        {"silhouette": 1.1},
    ],
)
def test_evidence_rejects_malformed_values(kwargs):
    with pytest.raises(ValueError):
        _evidence("candidate", **kwargs)


def test_evidence_rejects_empty_artifact_id():
    with pytest.raises(ValueError):
        _evidence("")


def test_evidence_rejects_more_distinct_months_than_weekly_episodes():
    with pytest.raises(ValueError, match="months cannot exceed weekly episodes"):
        _evidence("impossible", weekly_counts=(8, 8, 8), month_counts=(3, 9, 3))


def test_command_rejects_duplicate_artifacts_and_invalid_family_priority():
    candidate = _evidence("same")
    with pytest.raises(ValueError, match="artifact IDs"):
        SelectRegimeModelCommand((candidate, candidate))
    with pytest.raises(ValueError, match="priority"):
        SelectRegimeModelCommand((candidate,), model_family_priority=("kmeans", "kmeans"))


def test_family_winner_is_validated_and_immutable():
    with pytest.raises(ValueError, match="winner metric"):
        RegimeModelFamilyWinner("kmeans", "artifact", "bic", 1.0)
    with pytest.raises(ValueError):
        RegimeModelFamilyWinner("gmm", "artifact", "bic", float("nan"))

    winner = RegimeModelFamilyWinner("kmeans", "artifact", "silhouette", 0.4)
    with pytest.raises(FrozenInstanceError):
        winner.metric_value = 0.5


def test_thresholds_are_validated_and_all_contracts_are_immutable():
    with pytest.raises(ValueError):
        RegimeModelGateThresholds(minimum_weekly_episodes=True)
    with pytest.raises(ValueError):
        RegimeModelGateThresholds(minimum_seed_ari=float("nan"))

    thresholds = RegimeModelGateThresholds()
    evidence = _evidence("immutable")
    command = SelectRegimeModelCommand((evidence,), thresholds=thresholds)
    result = SelectRegimeModelUseCase().execute(command)
    with pytest.raises(FrozenInstanceError):
        evidence.seed_ari = 0.0
    with pytest.raises(FrozenInstanceError):
        thresholds.minimum_weekly_episodes = 0
    with pytest.raises(FrozenInstanceError):
        command.candidates = ()
    with pytest.raises(FrozenInstanceError):
        result.selected_artifact_id = None
