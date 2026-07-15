from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path

import numpy as np
import pytest

from src.application.services.regime_historical_replay import (
    ConfidenceComparison,
    ConfidenceReference,
    FeatureEnvelopeExceedance,
    HistoricalReplayCandidateResult,
    QuarterWarning,
    ReplayAssignmentDiagnostic,
    TrainingEnvelopeSummary,
    _research_preference_key,
    build_confidence_reference,
    compare_confidence_to_training,
    diagnose_gmm_assignments,
    jensen_shannon_divergence,
    rank_historical_replay_candidates,
    summarize_historical_replay_candidate,
    summarize_training_envelope,
)
from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.model import RegimeModelConfig, component_fingerprint
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
    ThreeDayChartFeatureVector,
)
from src.application.services.regime_balance_diagnostics import QuarterlyClusterCounts, summarize_cluster_balance
from src.infrastructure.regime.historical_replay_source import load_historical_replay_source


UTC = timezone.utc
NAMES = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
SOURCE_REPORT = Path("docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json")
SOURCE_SHA256 = "2e656b11b89baf412d1f6af3217c8900165d45c14531c28f64795695baaa8f4c"
REAL_FINGERPRINTS = {
    4: ("0f705f28e5bf54678ca0ebe3", "6d0d1affcd5a616a8daf784b", "717c5b1f6e6900bf9f2a7d48", "baed8e58c11ce3b4f680e945"),
    8: ("021cf5da658bbb8a891d3803", "340255b9bb291b2c8bf6951c", "4c135e31ff2eb6abf8897fc3", "50a4d2af865d577c31b3c85f",
        "7e2850f05408573738b5e3d5", "98ee2ae3b65563954026199d", "be23e3975752ecc63885bc0d", "e27a95030541d7f7555832b9"),
}


def _fit(cluster_count: int = 4) -> ClusterDiagnosticFit:
    means = tuple((float(value),) for value in np.linspace(-.9, .9, cluster_count))
    weights = tuple(1 / cluster_count for _ in means)
    covariances = tuple((1.0,) for _ in means)
    records = sorted(
        (
            component_fingerprint(
                model_type="gmm",
                feature_schema_version=THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
                feature_names=("return_4h",),
                mean=mean,
                covariance=covariances[index],
                weight=weights[index],
            ),
            mean,
            weights[index],
            covariances[index],
        )
        for index, mean in enumerate(means)
    )
    return ClusterDiagnosticFit(
        schema_version=THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        symbol="BTCUSDT",
        config=RegimeModelConfig("gmm", cluster_count, covariance_type="diag"),
        feature_names=("return_4h",),
        lower_bounds=(-1.0,),
        upper_bounds=(1.0,),
        medians=(0.0,),
        scales=(1.0,),
        fingerprints=tuple(row[0] for row in records),
        means=tuple(row[1] for row in records),
        weights=tuple(row[2] for row in records),
        covariances=tuple(row[3] for row in records),
        distance_thresholds=(),
    )


def _vector(day: int, value: float) -> ThreeDayChartFeatureVector:
    anchor = datetime(2021, 1, 4, tzinfo=UTC) + timedelta(days=day)
    values = {name: 0.0 for name in NAMES}
    values["return_4h"] = value
    return ThreeDayChartFeatureVector("BTCUSDT", anchor, anchor - timedelta(days=3), values)


def _diagnostic(day: int, fingerprint: str, posterior: float, margin: float, distance: float, clipped: int = 0):
    return ReplayAssignmentDiagnostic(
        datetime(2021, 1, 4, tzinfo=UTC) + timedelta(days=day),
        fingerprint,
        posterior,
        margin,
        distance,
        clipped,
    )


def test_envelope_diagnostics_count_pre_clipping_exceedances_and_linear_quantiles() -> None:
    raw = np.asarray([[-2.0, 0.0], [0.0, 3.0], [0.0, 0.0], [0.0, 0.0]])
    result = summarize_training_envelope(raw, ("a", "b"), (-1.0, -1.0), (1.0, 1.0))

    assert result.any_feature_exceedance_count == 2
    assert result.any_feature_exceedance_share == pytest.approx(.5)
    assert result.per_feature["a"].lower_count == 1
    assert result.per_feature["b"].upper_count == 1
    assert dict(result.clipped_dimension_quantiles) == pytest.approx({"p50": .5, "p95": 1.0, "max": 1.0})
    assert result.quantile_method == "linear"


def test_assignment_matches_independent_posterior_margin_and_component_mahalanobis_formula() -> None:
    fit = _fit()
    vector = _vector(0, .25)
    result = diagnose_gmm_assignments(fit, (vector,), THREE_DAY_CHART_FEATURE_REGISTRY_V1)[0]

    scaled = .25
    log_weights = []
    for mean, weight, covariance in zip(fit.means, fit.weights, fit.covariances):
        log_weights.append(math.log(weight) - .5 * (math.log(2 * math.pi * covariance[0]) + (scaled - mean[0]) ** 2 / covariance[0]))
    exp = np.exp(np.asarray(log_weights) - max(log_weights))
    probabilities = exp / exp.sum()
    order = np.argsort(-probabilities, kind="stable")
    winner = int(order[0])

    assert result.fingerprint == fit.fingerprints[winner]
    assert result.dominant_probability == pytest.approx(probabilities[winner])
    assert result.probability_margin == pytest.approx(probabilities[winner] - probabilities[int(order[1])])
    assert result.mahalanobis_distance == pytest.approx(abs(scaled - fit.means[winner][0]))
    assert result.clipped_dimension_count == 0


def test_assignment_counts_clipped_dimensions_before_clipping_and_is_deeply_immutable() -> None:
    fit = _fit()
    first = diagnose_gmm_assignments(fit, (_vector(0, 9.0),), THREE_DAY_CHART_FEATURE_REGISTRY_V1)[0]
    assert first.clipped_dimension_count == 1
    with pytest.raises(FrozenInstanceError):
        first.clipped_dimension_count = 2  # type: ignore[misc]


def test_training_reference_uses_global_p05_and_component_specific_p995_only_from_training() -> None:
    fit = _fit()
    fingerprints = fit.fingerprints
    training = tuple(
        _diagnostic(index, fingerprints[index % 4], posterior, margin, distance)
        for index, (posterior, margin, distance) in enumerate(
            [(.5, .1, 1), (.6, .2, 2), (.7, .3, 3), (.8, .4, 4), (.9, .5, 5), (.95, .6, 6), (.96, .7, 7), (.97, .8, 8)]
        )
    )
    reference = build_confidence_reference(training, fingerprints)
    expected_posterior = np.quantile([row.dominant_probability for row in training], .05, method="linear")
    expected_margin = np.quantile([row.probability_margin for row in training], .05, method="linear")
    assert reference.posterior_fifth_percentile == pytest.approx(expected_posterior)
    assert reference.margin_fifth_percentile == pytest.approx(expected_margin)
    for fingerprint in fingerprints:
        expected = np.quantile(
            [row.mahalanobis_distance for row in training if row.fingerprint == fingerprint],
            .995,
            method="linear",
        )
        assert reference.component_distance_995[fingerprint] == pytest.approx(expected)
    assert reference.quantile_method == "linear"

    historical = (
        _diagnostic(20, fingerprints[0], .1, .01, 99),
        _diagnostic(21, fingerprints[1], .99, .99, 0),
    )
    comparison = compare_confidence_to_training(historical, reference)
    assert comparison.posterior_below_reference_count == 1
    assert comparison.margin_below_reference_count == 1
    assert comparison.component_distance_above_reference_count == 1
    changed_history = tuple(replace(row, dominant_probability=.999, probability_margin=.999, mahalanobis_distance=0) for row in historical)
    assert compare_confidence_to_training(changed_history, reference) != comparison
    assert reference.posterior_fifth_percentile == pytest.approx(expected_posterior)


@pytest.mark.parametrize("cluster_count", [4, 8])
def test_reference_preserves_each_fixed_models_lexicographic_fingerprint_order(cluster_count: int) -> None:
    source = load_historical_replay_source(SOURCE_REPORT, expected_sha256=SOURCE_SHA256)
    fit = source.fits[f"gmm-diag-k{cluster_count}"]
    diagnostics = tuple(
        _diagnostic(index, fingerprint, .8, .4, index + 1)
        for index, fingerprint in enumerate(fit.fingerprints)
    )
    reference = build_confidence_reference(diagnostics, fit.fingerprints)
    assert reference.fingerprints == fit.fingerprints == REAL_FINGERPRINTS[cluster_count]


def test_jsd_matches_hand_formula_and_handles_common_zero_shares() -> None:
    p = {"a": .5, "b": .5, "c": 0.0}
    q = {"a": 1.0, "b": 0.0, "c": 0.0}
    expected = .5 * (.5 * math.log(.5 / .75) + .5 * math.log(.5 / .25)) + .5 * math.log(1 / .75)
    assert jensen_shannon_divergence(p, q, ("a", "b", "c")) == pytest.approx(expected)
    assert jensen_shannon_divergence(p, p, ("a", "b", "c")) == 0


def test_integrated_summary_has_fourteen_quarters_frozen_order_and_overlap_diagnostics() -> None:
    fit = _fit()
    start = datetime(2021, 1, 4, tzinfo=UTC)
    days = (datetime(2024, 7, 1, tzinfo=UTC) - start).days
    vectors = tuple(_vector(index, (-1, -.25, .25, 1)[index % 4]) for index in range(days))
    historical = diagnose_gmm_assignments(fit, vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    reference = build_confidence_reference(historical[:100], fit.fingerprints)
    training_shares = {name: .25 for name in fit.fingerprints}
    result = summarize_historical_replay_candidate(
        identity="gmm-diag-k4", fit=fit, vectors=vectors, diagnostics=historical,
        reference=reference, training_shares=training_shares,
    )

    assert result.quarterly.quarters == tuple(
        f"{year}-Q{quarter}" for year in range(2021, 2025) for quarter in range(1, 5)
        if not (year == 2024 and quarter > 2)
    )
    assert result.bootstrap.block_length == 3
    assert (result.bootstrap.resamples, result.bootstrap.confidence, result.bootstrap.seed) == (5000, .95, 20260714)
    assert result.effective_sample_sizes.max_lag == 30
    assert len(result.diagnostics) == len(vectors)
    assert result.balance.total == len(vectors)


def test_ranking_applies_every_declared_lexicographic_tie_break() -> None:
    base = (.0, .0, .0, 0, 100.0, .0, 4, "a")
    for index, worse_value in enumerate((.1, .1, .1, 1, 99.0, .1, 8, "b")):
        worse = list(base)
        worse[index] = worse_value
        assert _research_preference_key(*base) < _research_preference_key(*worse)


@pytest.mark.parametrize(
    "operation",
    [
        lambda fit, diagnostics: build_confidence_reference((replace(diagnostics[0], dominant_probability=True),), fit.fingerprints),
        lambda fit, diagnostics: build_confidence_reference((replace(diagnostics[0], mahalanobis_distance=math.nan),), fit.fingerprints),
        lambda fit, diagnostics: build_confidence_reference(diagnostics, tuple(reversed(fit.fingerprints))),
        lambda fit, diagnostics: compare_confidence_to_training((replace(diagnostics[0], fingerprint="unknown"),), build_confidence_reference(diagnostics, fit.fingerprints)),
        lambda fit, diagnostics: jensen_shannon_divergence({name: True for name in fit.fingerprints}, {name: .25 for name in fit.fingerprints}, fit.fingerprints),
    ],
)
def test_invalid_nonfinite_bool_order_and_fingerprint_states_fail_closed(operation) -> None:
    fit = _fit()
    diagnostics = diagnose_gmm_assignments(fit, tuple(_vector(i, value) for i, value in enumerate((-1, -.25, .25, 1))), THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    with pytest.raises(ValueError):
        operation(fit, diagnostics)


def test_diagnosis_rejects_wrong_model_dimension_and_vector_order() -> None:
    fit = _fit()
    tied = replace(fit, config=RegimeModelConfig("gmm", 4, covariance_type="tied"), covariances=tuple((1.0,) for _ in range(4)))
    with pytest.raises(ValueError, match="diagonal"):
        diagnose_gmm_assignments(tied, (_vector(0, 0),), THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    with pytest.raises(ValueError, match="chronological"):
        diagnose_gmm_assignments(fit, (_vector(1, 0), _vector(0, 0)), THREE_DAY_CHART_FEATURE_REGISTRY_V1)


def test_numerical_path_enters_and_restores_single_thread_limit(monkeypatch) -> None:
    events = []

    class Boundary:
        def __init__(self, limits):
            events.append(("init", limits))
        def __enter__(self):
            events.append(("enter", 1))
        def __exit__(self, *args):
            events.append(("exit", 1))

    monkeypatch.setattr("src.application.services.regime_historical_replay.threadpool_limits", Boundary)
    diagnose_gmm_assignments(_fit(), (_vector(0, 0),), THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    assert events == [("init", 1), ("enter", 1), ("exit", 1)]


def test_result_constructors_recompute_derived_summaries_and_copy_maps() -> None:
    fit = _fit()
    diagnostics = diagnose_gmm_assignments(fit, tuple(_vector(i, value) for i, value in enumerate((-1, -.25, .25, 1))), THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    reference = build_confidence_reference(diagnostics, fit.fingerprints)
    copied = dict(reference.component_distance_995)
    copied[fit.fingerprints[0]] = 999
    assert reference.component_distance_995[fit.fingerprints[0]] != 999
    with pytest.raises(ValueError):
        ConfidenceComparison(4, 1, 0.0, 0, 0.0, 0, 0.0)

    vectors = tuple(_vector(i, (-1, -.25, .25, 1)[i % 4]) for i in range(1274))
    rows = diagnose_gmm_assignments(fit, vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    result = summarize_historical_replay_candidate(
        identity="gmm-diag-k4", fit=fit, vectors=vectors, diagnostics=rows,
        reference=build_confidence_reference(rows, fit.fingerprints),
        training_shares={name: .25 for name in fit.fingerprints},
    )
    forged = summarize_cluster_balance((fit.fingerprints[0],) * len(rows), fit.fingerprints)
    with pytest.raises(ValueError, match="diagnostic-derived"):
        replace(result, balance=forged)

    envelope_rows = dict(result.envelope.per_feature)
    envelope_rows[fit.feature_names[0]] = FeatureEnvelopeExceedance(1, 0, 1 / 1274, 0.0)
    forged_envelope = TrainingEnvelopeSummary(
        result.envelope.feature_names, 1274, envelope_rows, 1, 1 / 1274,
        {"p50": 0.0, "p95": 0.0, "max": 1.0},
    )
    with pytest.raises(ValueError, match="per-anchor-diagnostic-derived"):
        replace(result, envelope=forged_envelope)


def test_mixed_boolean_raw_envelope_values_fail_closed() -> None:
    with pytest.raises(ValueError, match="booleans"):
        summarize_training_envelope([[True, 0.0], [0.0, 0.0]], ("a", "b"), (-1.0, -1.0), (1.0, 1.0))


@pytest.mark.parametrize("lower,upper", [((True,), (1.0,)), ((-1.0,), (False,))])
def test_boolean_envelope_bounds_fail_closed(lower, upper) -> None:
    with pytest.raises(ValueError, match="booleans"):
        summarize_training_envelope([[0.0]], ("a",), lower, upper)


def test_envelope_summary_rejects_positive_any_count_when_all_feature_counts_are_zero() -> None:
    rows = {
        "a": FeatureEnvelopeExceedance(0, 0, 0.0, 0.0),
        "b": FeatureEnvelopeExceedance(0, 0, 0.0, 0.0),
    }
    with pytest.raises(ValueError, match="cross-field"):
        TrainingEnvelopeSummary(("a", "b"), 4, rows, 1, .25, {"p50": 0.0, "p95": 1.0, "max": 1.0})


def test_envelope_summary_rejects_any_count_below_one_features_exceedance_count() -> None:
    rows = {
        "a": FeatureEnvelopeExceedance(1, 1, .25, .25),
        "b": FeatureEnvelopeExceedance(0, 0, 0.0, 0.0),
    }
    with pytest.raises(ValueError, match="cross-field"):
        TrainingEnvelopeSummary(
            ("a", "b"), 4, rows, 1, .25,
            {"p50": 0.0, "p95": 1.7, "max": 2.0},
        )


def test_candidate_summary_rejects_tied_fit_and_noncanonical_historical_quarters() -> None:
    fit = _fit()
    vectors = tuple(_vector(i, value) for i, value in enumerate((-1, -.25, .25, 1) * 10))
    diagnostics = diagnose_gmm_assignments(fit, vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    reference = build_confidence_reference(diagnostics, fit.fingerprints)
    with pytest.raises(ValueError, match="canonical historical daily anchors"):
        summarize_historical_replay_candidate(
            identity="gmm-diag-k4", fit=fit, vectors=vectors, diagnostics=diagnostics,
            reference=reference, training_shares={name: .25 for name in fit.fingerprints},
        )

    tied = replace(fit, config=RegimeModelConfig("gmm", 4, covariance_type="tied"), covariances=tuple((1.0,) for _ in range(4)))
    historical_vectors = tuple(_vector(index, (-1, -.25, .25, 1)[index % 4]) for index in range(1274))
    historical_diagnostics = diagnose_gmm_assignments(fit, historical_vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    with pytest.raises(ValueError, match="diagonal"):
        summarize_historical_replay_candidate(
            identity="gmm-tied-k4", fit=tied, vectors=historical_vectors, diagnostics=historical_diagnostics,
            reference=build_confidence_reference(historical_diagnostics[:100], fit.fingerprints),
            training_shares={name: .25 for name in fit.fingerprints},
        )


def test_result_and_ranking_reject_incorrect_quarter_state() -> None:
    fit = _fit()
    vectors = tuple(_vector(index, (-1, -.25, .25, 1)[index % 4]) for index in range(1274))
    diagnostics = diagnose_gmm_assignments(fit, vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    result = summarize_historical_replay_candidate(
        identity="gmm-diag-k4", fit=fit, vectors=vectors, diagnostics=diagnostics,
        reference=build_confidence_reference(diagnostics[:100], fit.fingerprints),
        training_shares={name: .25 for name in fit.fingerprints},
    )
    wrong_quarterly = QuarterlyClusterCounts(
        fit.fingerprints, ("2021-Q1",),
        {"2021-Q1": dict(result.balance.counts)}, 1274,
    )
    with pytest.raises(ValueError, match="quarter"):
        replace(result, quarterly=wrong_quarterly)

    noncanonical = copy_result = object.__new__(HistoricalReplayCandidateResult)
    for field in result.__dataclass_fields__:
        object.__setattr__(copy_result, field, getattr(result, field))
    object.__setattr__(noncanonical, "quarterly", wrong_quarterly)
    with pytest.raises(ValueError, match="quarter"):
        rank_historical_replay_candidates((noncanonical,))

    wrong_identity = object.__new__(HistoricalReplayCandidateResult)
    for field in result.__dataclass_fields__:
        object.__setattr__(wrong_identity, field, getattr(result, field))
    object.__setattr__(wrong_identity, "identity", "wrong")
    with pytest.raises(ValueError, match="identity"):
        rank_historical_replay_candidates((wrong_identity,))
