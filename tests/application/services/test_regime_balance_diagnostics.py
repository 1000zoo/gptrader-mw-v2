from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import math

import pytest

from src.application.services.regime_balance_diagnostics import (
    BalanceCandidate,
    BootstrapClusterShareIntervals,
    CentroidMatch,
    ClusterBalanceSummary,
    ClusterShareInterval,
    EffectiveSampleSizes,
    QuarterlyClusterCounts,
    bootstrap_cluster_share_intervals,
    effective_sample_sizes,
    match_refit_centroids,
    prevalence_drift,
    quarterly_cluster_counts,
    rank_balance_candidates,
    seed_stability,
    summarize_cluster_balance,
)
from src.domain.regime.daily_temporal import DailyRegimeEpisode, build_daily_regime_episodes


def _episode(anchor: datetime) -> DailyRegimeEpisode:
    return DailyRegimeEpisode(
        anchor_at=anchor,
        feature_start_at=anchor - timedelta(days=3),
        outcome_start_at=anchor,
        outcome_end_at=anchor + timedelta(days=1),
    )


def test_summarize_balance_includes_zero_count_clusters_and_entropy() -> None:
    result = summarize_cluster_balance(("a", "a", "b", "a"), ("a", "b", "c"))

    assert result.total == 4
    assert dict(result.counts) == {"a": 3, "b": 1, "c": 0}
    assert dict(result.shares) == pytest.approx({"a": .75, "b": .25, "c": 0})
    expected = -(.75 * math.log(.75) + .25 * math.log(.25)) / math.log(3)
    assert result.normalized_entropy == pytest.approx(expected)
    assert result.minimum_share == 0
    assert result.maximum_share == .75
    assert sum(result.counts.values()) == result.total
    assert sum(result.shares.values()) == pytest.approx(1)


def test_balance_results_are_deeply_immutable_copies() -> None:
    fingerprints = ["a", "b"]
    result = summarize_cluster_balance(["a", "b"], fingerprints)
    fingerprints[0] = "changed"

    assert result.fingerprints == ("a", "b")
    with pytest.raises(TypeError):
        result.counts["a"] = 8  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.total = 3  # type: ignore[misc]


def test_balance_result_rejects_counts_and_shares_that_disagree() -> None:
    with pytest.raises(ValueError, match="count-derived"):
        ClusterBalanceSummary(("a", "b"), 2, {"a": 2, "b": 0}, {"a": 0.0, "b": 1.0}, 0.0, 0.0, 1.0)


@pytest.mark.parametrize(
    "override",
    [
        {"normalized_entropy": .25},
        {"normalized_entropy": True},
        {"minimum_share": True},
        {"counts": {"a": True, "b": 1}},
        {"shares": {"a": True, "b": 0.5}},
        {"total": True},
    ],
)
def test_balance_result_rejects_inconsistent_entropy_and_bool_numerics(override) -> None:
    values = dict(
        fingerprints=("a", "b"), total=2, counts={"a": 1, "b": 1}, shares={"a": .5, "b": .5},
        normalized_entropy=1.0, minimum_share=.5, maximum_share=.5,
    )
    values.update(override)
    with pytest.raises(ValueError):
        ClusterBalanceSummary(**values)


def test_single_cluster_balance_requires_zero_normalized_entropy() -> None:
    with pytest.raises(ValueError, match="entropy"):
        ClusterBalanceSummary(("a",), 2, {"a": 2}, {"a": 1.0}, .1, 1.0, 1.0)


@pytest.mark.parametrize(
    ("labels", "fingerprints"),
    [((), ("a",)), (("x",), ("a",)), (("a",), ()), (("a",), ("a", "a")), (("a",), ("a", " "))],
)
def test_balance_rejects_invalid_inputs(labels, fingerprints) -> None:
    with pytest.raises(ValueError):
        summarize_cluster_balance(labels, fingerprints)


def test_quarterly_counts_are_calendar_ordered_and_count_each_anchor_once() -> None:
    episodes = build_daily_regime_episodes(
        datetime(2024, 6, 28, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    episodes = episodes[:727]
    labels = tuple("a" if i % 2 else "b" for i in range(727))

    result = quarterly_cluster_counts(episodes, labels, ("a", "b"))

    assert result.quarters == (
        "2024-Q3", "2024-Q4", "2025-Q1", "2025-Q2",
        "2025-Q3", "2025-Q4", "2026-Q1", "2026-Q2",
    )
    assert sum(sum(row.values()) for row in result.counts.values()) == 727
    assert sum(result.counts["2024-Q3"].values()) == 92
    assert sum(result.counts["2026-Q2"].values()) == 88
    with pytest.raises(TypeError):
        result.counts["2024-Q3"]["a"] = 0  # type: ignore[index]


def test_quarterly_counts_reject_mismatches_and_noncanonical_chronology() -> None:
    anchors = [datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 2, tzinfo=timezone.utc)]
    episodes = tuple(_episode(value) for value in anchors)
    with pytest.raises(ValueError, match="equal"):
        quarterly_cluster_counts(episodes, ("a",), ("a",))
    with pytest.raises(ValueError, match="chronological"):
        quarterly_cluster_counts(tuple(reversed(episodes)), ("a", "a"), ("a",))
    with pytest.raises(ValueError, match="known"):
        quarterly_cluster_counts(episodes, ("a", "x"), ("a",))


def test_quarterly_counts_can_derive_first_seen_fingerprint_order() -> None:
    episodes = tuple(
        _episode(datetime(2025, 1, day, tzinfo=timezone.utc))
        for day in (1, 2, 3)
    )

    result = quarterly_cluster_counts(episodes, ("b", "a", "b"))

    assert result.fingerprints == ("b", "a")
    assert dict(result.counts["2025-Q1"]) == {"b": 2, "a": 1}


@pytest.mark.parametrize(
    "quarters,counts,total",
    [
        (("2025-1",), {"2025-1": {"a": 1}}, 1),
        (("2025-Q5",), {"2025-Q5": {"a": 1}}, 1),
        (("2025-Q2", "2025-Q1"), {"2025-Q2": {"a": 1}, "2025-Q1": {"a": 1}}, 2),
        (("2025-Q1",), {"2025-Q1": {"a": True}}, 1),
        (("2025-Q1",), {"2025-Q1": {"a": 1}}, True),
        (("2025-Q1",), {"2025-Q1": {"a": 1}}, -1),
        (("2025-Q1",), {"2025-Q1": {"a": 2}}, 1),
    ],
)
def test_quarterly_result_rejects_noncanonical_order_counts_and_totals(quarters, counts, total) -> None:
    with pytest.raises(ValueError):
        QuarterlyClusterCounts(("a",), quarters, counts, total)


def test_quarterly_result_requires_each_row_in_exact_fingerprint_order() -> None:
    with pytest.raises(ValueError, match="fingerprints"):
        QuarterlyClusterCounts(
            ("a", "b"), ("2025-Q1",), {"2025-Q1": {"b": 1, "a": 1}}, 2,
        )


def _reference_circular_bootstrap(labels, fingerprints, block_length, resamples, confidence, seed):
    import numpy as np

    rng = np.random.default_rng(seed)
    sample_count = len(labels)
    draws = {name: [] for name in fingerprints}
    blocks = math.ceil(sample_count / block_length)
    for _ in range(resamples):
        starts = rng.integers(0, sample_count, size=blocks)
        sampled = [labels[(int(start) + offset) % sample_count] for start in starts for offset in range(block_length)]
        sampled = sampled[:sample_count]
        for name in fingerprints:
            draws[name].append(sampled.count(name) / sample_count)
    alpha = (1 - confidence) / 2
    return {name: tuple(np.quantile(values, (alpha, 1 - alpha))) for name, values in draws.items()}


def test_circular_moving_block_bootstrap_is_deterministic_and_matches_reference() -> None:
    args = (("a", "a", "b", "b", "a"), ("a", "b"))
    first = bootstrap_cluster_share_intervals(*args, block_length=3, resamples=40, confidence=.8, seed=11)
    second = bootstrap_cluster_share_intervals(*args, block_length=3, resamples=40, confidence=.8, seed=11)
    reference = _reference_circular_bootstrap(*args, 3, 40, .8, 11)

    assert first == second
    assert first.block_length == 3
    assert first.resamples == 40
    for name, interval in first.intervals.items():
        assert (interval.lower, interval.upper) == pytest.approx(reference[name])
        assert interval.lower <= interval.point <= interval.upper


def test_bootstrap_defaults_report_all_5000_resamples() -> None:
    result = bootstrap_cluster_share_intervals(("a", "b", "a"), ("a", "b"))
    assert (result.block_length, result.resamples, result.confidence, result.seed) == (3, 5000, .95, 20260714)


def test_bootstrap_and_ess_results_reject_impossible_metadata() -> None:
    interval = ClusterShareInterval(.5, .25, .75)
    with pytest.raises(ValueError, match="metadata"):
        BootstrapClusterShareIntervals(("a",), {"a": interval}, 0, 1, 10, .95, 1)
    with pytest.raises(ValueError, match="metadata"):
        EffectiveSampleSizes(("a",), {"a": 1.0}, 1.0, 0, 1)


@pytest.mark.parametrize("kwargs", [{"block_length": 0}, {"block_length": 4}, {"resamples": 0}, {"confidence": 1}, {"seed": True}])
def test_bootstrap_rejects_invalid_parameters(kwargs) -> None:
    with pytest.raises(ValueError):
        bootstrap_cluster_share_intervals(("a", "b", "a"), ("a", "b"), **kwargs)


def test_effective_sample_size_detects_persistence_and_handles_zero_variance_fail_closed() -> None:
    alternating = effective_sample_sizes(tuple("ab"[i % 2] for i in range(100)), ("a", "b"), max_lag=20)
    persistent = effective_sample_sizes(("a",) * 50 + ("b",) * 50, ("a", "b", "c"), max_lag=20)

    assert persistent.minimum < alternating.minimum
    assert persistent.values["c"] == 1
    all_one = effective_sample_sizes(("a",) * 20, ("a", "b"), max_lag=10)
    assert dict(all_one.values) == {"a": 1.0, "b": 1.0}
    with pytest.raises(ValueError):
        effective_sample_sizes(("a", "b"), ("a", "b"), max_lag=0)


def test_effective_sample_size_uses_both_positive_pairs_and_max_lag_truncation() -> None:
    labels = tuple("b" if bit == "1" else "a" for bit in "0000011011")

    through_lag_four = effective_sample_sizes(labels, ("a", "b"), max_lag=4)
    through_lag_two = effective_sample_sizes(labels, ("a", "b"), max_lag=2)

    # Hand-computed rhos: (4/15, -1/20) and (3/10, -1/60).
    assert dict(through_lag_four.values) == pytest.approx({"a": 5.0, "b": 5.0})
    assert dict(through_lag_two.values) == pytest.approx({"a": 300 / 43, "b": 300 / 43})


def test_effective_sample_size_stops_before_first_nonpositive_pair() -> None:
    labels = tuple("b" if bit == "1" else "a" for bit in "00000011")

    result = effective_sample_sizes(labels, ("a", "b"), max_lag=4)

    # Pair one is 11/24 - 1/12 = 3/8; pair two is -1/8 - 1/6 < 0.
    assert dict(result.values) == pytest.approx({"a": 32 / 7, "b": 32 / 7})


def test_seed_stability_identity_permutation_and_difference() -> None:
    identity = seed_stability(("a", "a", "b", "b"), ("a", "a", "b", "b"), ("a", "b"), ("a", "b"))
    permutation = seed_stability(("a", "a", "b", "b"), ("y", "y", "x", "x"), ("a", "b"), ("x", "y"))
    different = seed_stability(("a", "a", "b", "b"), ("x", "y", "x", "y"), ("a", "b"), ("x", "y"))

    assert (identity.adjusted_rand_index, identity.normalized_mutual_information) == pytest.approx((1, 1))
    assert (permutation.adjusted_rand_index, permutation.normalized_mutual_information) == pytest.approx((1, 1))
    assert different.adjusted_rand_index < 1
    assert different.normalized_mutual_information < 1
    with pytest.raises(ValueError):
        seed_stability(("a",), ("x", "x"), ("a",), ("x",))


def test_centroid_projection_and_hungarian_matching() -> None:
    result = match_refit_centroids(
        primary_centroids=((0.0, 0.0), (2.0, 2.0)),
        refit_centroids=((0.0, 0.0), (0.0, 0.0)),
        primary_feature_names=("x", "y"),
        refit_feature_names=("x", "y"),
        primary_means=(10.0, 20.0),
        primary_scales=(2.0, 5.0),
        refit_means=(14.0, 30.0),
        refit_scales=(4.0, 10.0),
        primary_fingerprints=("p0", "p1"),
        refit_fingerprints=("r0", "r1"),
    )

    assert dict(result.refit_to_primary) == {"r0": "p1", "r1": "p0"}
    assert result.projected_refit_centroids == ((2.0, 2.0), (2.0, 2.0))
    assert result.mean_distance == pytest.approx(math.sqrt(8) / 2)
    assert result.maximum_distance == pytest.approx(math.sqrt(8))


@pytest.mark.parametrize(
    "override",
    [
        {"refit_to_primary": {}},
        {"refit_to_primary": {"r0": "p0", "r1": "p0"}},
        {"refit_to_primary": {"": "p0", "r1": "p1"}},
        {"projected_refit_centroids": ((0.0, 0.0),)},
        {"projected_refit_centroids": ((0.0, 0.0), (1.0,))},
        {"projected_refit_centroids": ((), ())},
        {"projected_refit_centroids": ((0.0, 0.0), (math.inf, 1.0))},
        {"distances": {"r0": 0.0}},
        {"mean_distance": .25},
        {"maximum_distance": 2.0},
    ],
)
def test_centroid_match_result_rejects_impossible_mapping_shape_and_summaries(override) -> None:
    values = dict(
        refit_to_primary={"r0": "p0", "r1": "p1"},
        projected_refit_centroids=((0.0, 0.0), (1.0, 1.0)),
        distances={"r0": 0.0, "r1": 1.0}, mean_distance=.5, maximum_distance=1.0,
    )
    values.update(override)
    with pytest.raises(ValueError):
        CentroidMatch(**values)


@pytest.mark.parametrize(
    "override",
    [
        {"refit_feature_names": ("y", "x")},
        {"primary_scales": (0.0, 1.0)},
        {"refit_centroids": ((0.0, 0.0),)},
        {"primary_fingerprints": ("p", "p")},
        {"refit_means": (math.nan, 0.0)},
    ],
)
def test_centroid_matching_rejects_invalid_shapes_and_values(override) -> None:
    inputs = dict(
        primary_centroids=((0.0, 0.0), (1.0, 1.0)), refit_centroids=((0.0, 0.0), (1.0, 1.0)),
        primary_feature_names=("x", "y"), refit_feature_names=("x", "y"),
        primary_means=(0.0, 0.0), primary_scales=(1.0, 1.0), refit_means=(0.0, 0.0), refit_scales=(1.0, 1.0),
        primary_fingerprints=("p0", "p1"), refit_fingerprints=("r0", "r1"),
    )
    inputs.update(override)
    with pytest.raises(ValueError):
        match_refit_centroids(**inputs)


def test_prevalence_drift_applies_matching_before_comparison() -> None:
    result = prevalence_drift(
        first_half_labels=("p0", "p0", "p0", "p1"),
        second_half_labels=("r0", "r0", "r1", "r1"),
        primary_fingerprints=("p0", "p1"),
        refit_fingerprints=("r0", "r1"),
        refit_to_primary={"r0": "p1", "r1": "p0"},
    )
    assert dict(result.absolute_share_changes) == pytest.approx({"p0": .25, "p1": .25})
    assert result.maximum == pytest.approx(.25)
    assert result.l1 == pytest.approx(.5)


def test_ranking_is_descriptive_stable_and_preserves_rejected_candidates() -> None:
    candidates = (
        BalanceCandidate("z", summarize_cluster_balance(("a", "a", "a", "b"), ("a", "b")), status="technical"),
        BalanceCandidate("a", summarize_cluster_balance(("a", "b", "c", "a"), ("a", "b", "c")), status="rejected"),
        BalanceCandidate("b", summarize_cluster_balance(("a", "b", "c", "a"), ("a", "b", "c")), status="accepted"),
    )
    ranked = rank_balance_candidates(candidates)

    assert tuple(value.config_identity for value in ranked) == ("a", "b", "z")
    assert {value.status for value in ranked} == {"technical", "rejected", "accepted"}
    with pytest.raises(ValueError):
        rank_balance_candidates((candidates[0], BalanceCandidate("z", candidates[1].balance)))
