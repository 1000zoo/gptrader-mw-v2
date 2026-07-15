"""Pure descriptive statistics for overlapping daily regime assignments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import math
import re
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from src.domain.regime.daily_temporal import DailyRegimeEpisode


def _immutable_mapping(values: Mapping) -> MappingProxyType:
    return MappingProxyType(dict(values))


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _fingerprints(values: Sequence[str], *, name: str = "fingerprints") -> tuple[str, ...]:
    result = tuple(values)
    if (
        not result
        or any(not isinstance(value, str) or not value or value != value.strip() for value in result)
        or len(set(result)) != len(result)
    ):
        raise ValueError(f"{name} must be nonempty, unique, ordered, and nonblank")
    return result


def _labels(values: Sequence[str], fingerprints: tuple[str, ...], *, allow_empty: bool = False) -> tuple[str, ...]:
    result = tuple(values)
    if not result and not allow_empty:
        raise ValueError("labels must be nonempty")
    if any(not isinstance(value, str) or value not in fingerprints for value in result):
        raise ValueError("every label must be a known fingerprint")
    return result


@dataclass(frozen=True)
class ClusterBalanceSummary:
    fingerprints: tuple[str, ...]
    total: int
    counts: Mapping[str, int]
    shares: Mapping[str, float]
    normalized_entropy: float
    minimum_share: float
    maximum_share: float

    def __post_init__(self) -> None:
        names = _fingerprints(self.fingerprints)
        counts = dict(self.counts)
        shares = dict(self.shares)
        if not isinstance(self.total, int) or isinstance(self.total, bool) or self.total <= 0:
            raise ValueError("balance total must be a positive integer")
        if tuple(counts) != names or tuple(shares) != names:
            raise ValueError("balance mappings must exactly follow fingerprints")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts.values()):
            raise ValueError("balance counts must be nonnegative integers")
        numeric = (*shares.values(), self.normalized_entropy, self.minimum_share, self.maximum_share)
        if any(not _finite(value) for value in numeric):
            raise ValueError("balance statistics must be finite")
        if sum(counts.values()) != self.total or not math.isclose(math.fsum(shares.values()), 1.0, abs_tol=1e-12):
            raise ValueError("balance counts and shares must sum to their totals")
        if any(
            not math.isclose(shares[name], counts[name] / self.total, rel_tol=1e-12, abs_tol=1e-12)
            for name in names
        ):
            raise ValueError("balance shares must be count-derived")
        if any(value < 0 or value > 1 for value in shares.values()):
            raise ValueError("balance shares must lie in [0, 1]")
        if not math.isclose(self.minimum_share, min(shares.values())) or not math.isclose(
            self.maximum_share, max(shares.values())
        ):
            raise ValueError("balance share extrema are inconsistent")
        if not 0 <= self.normalized_entropy <= 1 + 1e-12:
            raise ValueError("normalized entropy must lie in [0, 1]")
        entropy = -math.fsum(share * math.log(share) for share in shares.values() if share > 0)
        expected_entropy = 0.0 if len(names) == 1 else entropy / math.log(len(names))
        if not math.isclose(self.normalized_entropy, expected_entropy, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("normalized entropy is inconsistent with stored shares")
        object.__setattr__(self, "fingerprints", names)
        object.__setattr__(self, "counts", _immutable_mapping(counts))
        object.__setattr__(self, "shares", _immutable_mapping(shares))


def summarize_cluster_balance(labels: Sequence[str], fingerprints: Sequence[str]) -> ClusterBalanceSummary:
    names = _fingerprints(fingerprints)
    assignments = _labels(labels, names)
    counts = {name: assignments.count(name) for name in names}
    total = len(assignments)
    shares = {name: count / total for name, count in counts.items()}
    entropy = -math.fsum(share * math.log(share) for share in shares.values() if share > 0)
    normalized = 0.0 if len(names) == 1 else entropy / math.log(len(names))
    return ClusterBalanceSummary(names, total, counts, shares, normalized, min(shares.values()), max(shares.values()))


@dataclass(frozen=True)
class QuarterlyClusterCounts:
    fingerprints: tuple[str, ...]
    quarters: tuple[str, ...]
    counts: Mapping[str, Mapping[str, int]]
    total: int

    def __post_init__(self) -> None:
        names = _fingerprints(self.fingerprints)
        quarters = tuple(self.quarters)
        if (
            not quarters
            or any(not isinstance(value, str) or re.fullmatch(r"\d{4}-Q[1-4]", value) is None for value in quarters)
            or tuple(sorted(quarters, key=lambda value: (int(value[:4]), int(value[-1])))) != quarters
            or len(set(quarters)) != len(quarters)
        ):
            raise ValueError("quarters must be nonempty canonical unique chronological keys")
        if not isinstance(self.total, int) or isinstance(self.total, bool) or self.total < 0:
            raise ValueError("quarter total must be a nonnegative integer")
        copied = {}
        for quarter in quarters:
            row = dict(self.counts.get(quarter, {}))
            if tuple(row) != names or any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in row.values()
            ):
                raise ValueError("quarter counts must be nonnegative and match fingerprints")
            copied[quarter] = _immutable_mapping(row)
        if set(self.counts) != set(quarters) or sum(sum(row.values()) for row in copied.values()) != self.total:
            raise ValueError("quarter totals are inconsistent")
        object.__setattr__(self, "fingerprints", names)
        object.__setattr__(self, "quarters", quarters)
        object.__setattr__(self, "counts", _immutable_mapping(copied))


def quarterly_cluster_counts(
    episodes: Sequence[DailyRegimeEpisode], labels: Sequence[str], fingerprints: Sequence[str] | None = None
) -> QuarterlyClusterCounts:
    episode_values = tuple(episodes)
    assignments = tuple(labels)
    if not episode_values or len(episode_values) != len(assignments):
        raise ValueError("episodes and labels must be nonempty and equal length")
    if fingerprints is None:
        if any(not isinstance(value, str) or not value or value != value.strip() for value in assignments):
            raise ValueError("labels must be nonblank canonical fingerprints")
        names = tuple(dict.fromkeys(assignments))
    else:
        names = _fingerprints(fingerprints)
    assignments = _labels(assignments, names)
    if any(not isinstance(episode, DailyRegimeEpisode) for episode in episode_values):
        raise ValueError("episodes must be canonical daily regime episodes")
    if any(
        current.anchor_at != previous.anchor_at + timedelta(days=1)
        for previous, current in zip(episode_values, episode_values[1:])
    ):
        raise ValueError("episode anchors must be unique chronological contiguous daily anchors")
    rows: dict[str, dict[str, int]] = {}
    for episode, label in zip(episode_values, assignments):
        quarter = f"{episode.anchor_at.year}-Q{(episode.anchor_at.month - 1) // 3 + 1}"
        rows.setdefault(quarter, {name: 0 for name in names})[label] += 1
    return QuarterlyClusterCounts(names, tuple(rows), rows, len(episode_values))


@dataclass(frozen=True)
class ClusterShareInterval:
    """Observed share with percentile bounds widened to contain that point."""

    point: float
    lower: float
    upper: float

    def __post_init__(self) -> None:
        if any(not _finite(value) for value in (self.point, self.lower, self.upper)) or not (
            0 <= self.lower <= self.point <= self.upper <= 1
        ):
            raise ValueError("share interval must be finite, ordered, and lie in [0, 1]")


@dataclass(frozen=True)
class BootstrapClusterShareIntervals:
    fingerprints: tuple[str, ...]
    intervals: Mapping[str, ClusterShareInterval]
    sample_count: int
    block_length: int
    resamples: int
    confidence: float
    seed: int

    def __post_init__(self) -> None:
        names = _fingerprints(self.fingerprints)
        intervals = dict(self.intervals)
        if tuple(intervals) != names or any(not isinstance(value, ClusterShareInterval) for value in intervals.values()):
            raise ValueError("bootstrap intervals must exactly match fingerprints")
        if (
            not isinstance(self.sample_count, int) or isinstance(self.sample_count, bool) or self.sample_count <= 0
            or not isinstance(self.block_length, int) or isinstance(self.block_length, bool)
            or not 1 <= self.block_length <= self.sample_count
            or not isinstance(self.resamples, int) or isinstance(self.resamples, bool) or self.resamples <= 0
            or not _finite(self.confidence) or not 0 < self.confidence < 1
            or not isinstance(self.seed, int) or isinstance(self.seed, bool)
        ):
            raise ValueError("bootstrap metadata is invalid")
        object.__setattr__(self, "fingerprints", names)
        object.__setattr__(self, "intervals", _immutable_mapping(intervals))


def bootstrap_cluster_share_intervals(
    labels: Sequence[str], fingerprints: Sequence[str], *, block_length: int = 3,
    resamples: int = 5000, confidence: float = .95, seed: int = 20260714,
) -> BootstrapClusterShareIntervals:
    names = _fingerprints(fingerprints)
    assignments = _labels(labels, names)
    sample_count = len(assignments)
    if not isinstance(block_length, int) or isinstance(block_length, bool) or not 1 <= block_length <= sample_count:
        raise ValueError("block length must be an integer from 1 through sample count")
    if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples <= 0:
        raise ValueError("resamples must be a positive integer")
    if not _finite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must lie strictly between zero and one")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("seed must be an integer")
    rng = np.random.default_rng(seed)
    block_count = math.ceil(sample_count / block_length)
    draws = {name: np.empty(resamples, dtype=float) for name in names}
    for index in range(resamples):
        starts = rng.integers(0, sample_count, size=block_count)
        sampled = [assignments[(int(start) + offset) % sample_count] for start in starts for offset in range(block_length)]
        sampled = sampled[:sample_count]
        for name in names:
            draws[name][index] = sampled.count(name) / sample_count
    alpha = (1 - confidence) / 2
    points = {name: assignments.count(name) / sample_count for name in names}
    intervals = {}
    for name in names:
        lower, upper = np.quantile(draws[name], (alpha, 1 - alpha))
        point = points[name]
        intervals[name] = ClusterShareInterval(point, max(0.0, min(float(lower), point)), min(1.0, max(float(upper), point)))
    return BootstrapClusterShareIntervals(names, intervals, sample_count, block_length, resamples, float(confidence), seed)


@dataclass(frozen=True)
class EffectiveSampleSizes:
    fingerprints: tuple[str, ...]
    values: Mapping[str, float]
    minimum: float
    sample_count: int
    max_lag: int

    def __post_init__(self) -> None:
        names = _fingerprints(self.fingerprints)
        values = dict(self.values)
        if (
            not isinstance(self.sample_count, int) or isinstance(self.sample_count, bool) or self.sample_count <= 0
            or not isinstance(self.max_lag, int) or isinstance(self.max_lag, bool) or self.max_lag < 1
            or (self.sample_count > 1 and self.max_lag >= self.sample_count)
        ):
            raise ValueError("effective sample size metadata is invalid")
        if tuple(values) != names or any(not _finite(value) or not 1 <= value <= self.sample_count for value in values.values()):
            raise ValueError("effective sample sizes must be finite and lie in [1, N]")
        if not _finite(self.minimum) or not math.isclose(
            self.minimum, min(values.values()), rel_tol=1e-12, abs_tol=1e-12,
        ):
            raise ValueError("minimum effective sample size is inconsistent")
        object.__setattr__(self, "fingerprints", names)
        object.__setattr__(self, "values", _immutable_mapping(values))


def effective_sample_sizes(
    labels: Sequence[str], fingerprints: Sequence[str], *, max_lag: int = 30
) -> EffectiveSampleSizes:
    names = _fingerprints(fingerprints)
    assignments = _labels(labels, names)
    sample_count = len(assignments)
    if not isinstance(max_lag, int) or isinstance(max_lag, bool) or max_lag < 1 or (sample_count > 1 and max_lag >= sample_count):
        raise ValueError("max lag must be a positive integer smaller than sample count")
    values = {}
    for name in names:
        series = np.fromiter((label == name for label in assignments), dtype=float)
        centered = series - series.mean()
        denominator = float(centered @ centered)
        if denominator == 0:
            values[name] = 1.0
            continue
        correlations = [float(centered[:-lag] @ centered[lag:] / denominator) for lag in range(1, max_lag + 1)]
        accepted_sum = 0.0
        for offset in range(0, len(correlations) - 1, 2):
            pair = correlations[offset] + correlations[offset + 1]
            if not math.isfinite(pair) or pair <= 0:
                break
            accepted_sum += pair
        tau = max(1.0, 1 + 2 * accepted_sum)
        values[name] = min(float(sample_count), max(1.0, sample_count / tau))
    return EffectiveSampleSizes(names, values, min(values.values()), sample_count, max_lag)


@dataclass(frozen=True)
class BalanceCandidate:
    config_identity: str
    balance: ClusterBalanceSummary
    status: str = "accepted"

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value or value != value.strip() for value in (self.config_identity, self.status)):
            raise ValueError("candidate identity and status must be nonblank canonical strings")
        if not isinstance(self.balance, ClusterBalanceSummary):
            raise ValueError("candidate balance must be a cluster balance summary")


def rank_balance_candidates(candidates: Sequence[BalanceCandidate]) -> tuple[BalanceCandidate, ...]:
    values = tuple(candidates)
    if not values or any(not isinstance(value, BalanceCandidate) for value in values):
        raise ValueError("candidates must be nonempty balance candidates")
    if len({value.config_identity for value in values}) != len(values):
        raise ValueError("candidate config identities must be unique")
    return tuple(sorted(values, key=lambda value: (
        -value.balance.normalized_entropy, -value.balance.minimum_share, value.balance.maximum_share,
        len(value.balance.fingerprints), value.config_identity,
    )))


@dataclass(frozen=True)
class SeedStability:
    adjusted_rand_index: float
    normalized_mutual_information: float

    def __post_init__(self) -> None:
        if any(not _finite(value) for value in (self.adjusted_rand_index, self.normalized_mutual_information)):
            raise ValueError("seed stability metrics must be finite")
        if not -1 <= self.adjusted_rand_index <= 1 or not 0 <= self.normalized_mutual_information <= 1:
            raise ValueError("seed stability metrics are outside their theoretical ranges")


def seed_stability(
    primary_labels: Sequence[str], refit_labels: Sequence[str],
    primary_fingerprints: Sequence[str], refit_fingerprints: Sequence[str],
) -> SeedStability:
    primary_names = _fingerprints(primary_fingerprints, name="primary fingerprints")
    refit_names = _fingerprints(refit_fingerprints, name="refit fingerprints")
    primary = _labels(primary_labels, primary_names)
    refit = _labels(refit_labels, refit_names)
    if len(primary) != len(refit):
        raise ValueError("primary and refit labels must have equal length")
    ari = float(adjusted_rand_score(primary, refit))
    nmi = float(normalized_mutual_info_score(primary, refit))
    return SeedStability(ari, nmi)


@dataclass(frozen=True)
class CentroidMatch:
    refit_to_primary: Mapping[str, str]
    projected_refit_centroids: tuple[tuple[float, ...], ...]
    distances: Mapping[str, float]
    mean_distance: float
    maximum_distance: float

    def __post_init__(self) -> None:
        mapping = dict(self.refit_to_primary)
        distances = dict(self.distances)
        if (
            not mapping
            or any(
                not isinstance(key, str) or not key or key != key.strip()
                or not isinstance(value, str) or not value or value != value.strip()
                for key, value in mapping.items()
            )
            or len(set(mapping.values())) != len(mapping)
        ):
            raise ValueError("centroid mapping must be a nonempty canonical bijection")
        if tuple(mapping) != tuple(distances) or any(not _finite(value) or value < 0 for value in distances.values()):
            raise ValueError("centroid mapping and distances must be finite and aligned")
        projected = tuple(tuple(row) for row in self.projected_refit_centroids)
        if (
            len(projected) != len(mapping)
            or not projected[0]
            or any(len(row) != len(projected[0]) for row in projected)
            or any(not _finite(value) for row in projected for value in row)
        ):
            raise ValueError("projected centroids must be finite with consistent nonzero dimensions")
        if not _finite(self.mean_distance) or not _finite(self.maximum_distance):
            raise ValueError("centroid distance summaries must be finite")
        if not math.isclose(self.mean_distance, math.fsum(distances.values()) / len(distances)) or not math.isclose(
            self.maximum_distance, max(distances.values())
        ):
            raise ValueError("centroid distance summaries are inconsistent")
        object.__setattr__(self, "refit_to_primary", _immutable_mapping(mapping))
        object.__setattr__(self, "projected_refit_centroids", projected)
        object.__setattr__(self, "distances", _immutable_mapping(distances))


def match_refit_centroids(
    *, primary_centroids: Sequence[Sequence[float]], refit_centroids: Sequence[Sequence[float]],
    primary_feature_names: Sequence[str], refit_feature_names: Sequence[str],
    primary_means: Sequence[float], primary_scales: Sequence[float],
    refit_means: Sequence[float], refit_scales: Sequence[float],
    primary_fingerprints: Sequence[str], refit_fingerprints: Sequence[str],
) -> CentroidMatch:
    primary_names = _fingerprints(primary_fingerprints, name="primary fingerprints")
    refit_names = _fingerprints(refit_fingerprints, name="refit fingerprints")
    feature_names = _fingerprints(primary_feature_names, name="feature names")
    if tuple(refit_feature_names) != feature_names:
        raise ValueError("retained feature names and order must match")
    feature_count = len(feature_names)
    primary = tuple(tuple(row) for row in primary_centroids)
    refit = tuple(tuple(row) for row in refit_centroids)
    vectors = tuple(tuple(values) for values in (primary_means, primary_scales, refit_means, refit_scales))
    if len(primary) != len(refit) or len(primary) != len(primary_names) or len(refit) != len(refit_names):
        raise ValueError("primary and refit cluster counts must be equal")
    if any(len(row) != feature_count for row in (*primary, *refit)) or any(len(row) != feature_count for row in vectors):
        raise ValueError("centroid and preprocessing dimensions must match retained features")
    if any(not _finite(value) for row in (*primary, *refit, *vectors) for value in row):
        raise ValueError("centroid and preprocessing values must be finite")
    if any(value <= 0 for value in (*primary_scales, *refit_scales)):
        raise ValueError("centroid scales must be positive")
    projected = tuple(tuple(
        ((refit_value * refit_scales[index] + refit_means[index]) - primary_means[index]) / primary_scales[index]
        for index, refit_value in enumerate(row)
    ) for row in refit)
    cost = np.linalg.norm(np.asarray(projected)[:, None, :] - np.asarray(primary)[None, :, :], axis=2)
    refit_indices, primary_indices = linear_sum_assignment(cost)
    mapping = {refit_names[int(r)]: primary_names[int(p)] for r, p in zip(refit_indices, primary_indices)}
    distances = {refit_names[int(r)]: float(cost[r, p]) for r, p in zip(refit_indices, primary_indices)}
    return CentroidMatch(mapping, projected, distances, math.fsum(distances.values()) / len(distances), max(distances.values()))


@dataclass(frozen=True)
class PrevalenceDrift:
    absolute_share_changes: Mapping[str, float]
    maximum: float
    l1: float

    def __post_init__(self) -> None:
        changes = dict(self.absolute_share_changes)
        _fingerprints(tuple(changes), name="prevalence drift fingerprints")
        if any(not _finite(value) or not 0 <= value <= 1 for value in changes.values()):
            raise ValueError("prevalence changes must be finite shares")
        if (
            not _finite(self.maximum) or not 0 <= self.maximum <= 1
            or not _finite(self.l1) or not 0 <= self.l1 <= 2
        ):
            raise ValueError("prevalence drift summaries are outside valid ranges")
        if not math.isclose(
            self.maximum, max(changes.values()), rel_tol=1e-12, abs_tol=1e-12,
        ) or not math.isclose(
            self.l1, math.fsum(changes.values()), rel_tol=1e-12, abs_tol=1e-12,
        ):
            raise ValueError("prevalence drift summaries are inconsistent")
        object.__setattr__(self, "absolute_share_changes", _immutable_mapping(changes))


def prevalence_drift(
    *, first_half_labels: Sequence[str], second_half_labels: Sequence[str],
    primary_fingerprints: Sequence[str], refit_fingerprints: Sequence[str], refit_to_primary: Mapping[str, str],
) -> PrevalenceDrift:
    primary_names = _fingerprints(primary_fingerprints, name="primary fingerprints")
    refit_names = _fingerprints(refit_fingerprints, name="refit fingerprints")
    first = _labels(first_half_labels, primary_names)
    second = _labels(second_half_labels, refit_names)
    mapping = dict(refit_to_primary)
    if set(mapping) != set(refit_names) or set(mapping.values()) != set(primary_names) or len(set(mapping.values())) != len(mapping):
        raise ValueError("refit-to-primary mapping must be a complete bijection")
    first_shares = {name: first.count(name) / len(first) for name in primary_names}
    mapped_second = tuple(mapping[label] for label in second)
    second_shares = {name: mapped_second.count(name) / len(mapped_second) for name in primary_names}
    changes = {name: abs(second_shares[name] - first_shares[name]) for name in primary_names}
    return PrevalenceDrift(changes, max(changes.values()), math.fsum(changes.values()))


__all__ = [
    "BalanceCandidate", "BootstrapClusterShareIntervals", "CentroidMatch", "ClusterBalanceSummary",
    "ClusterShareInterval", "EffectiveSampleSizes", "PrevalenceDrift", "QuarterlyClusterCounts", "SeedStability",
    "bootstrap_cluster_share_intervals", "effective_sample_sizes", "match_refit_centroids", "prevalence_drift",
    "quarterly_cluster_counts", "rank_balance_candidates", "seed_stability", "summarize_cluster_balance",
]
