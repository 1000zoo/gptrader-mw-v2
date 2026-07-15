"""Pure diagnostics for replaying frozen three-day GMM regime fits."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re
from types import MappingProxyType
from typing import Mapping, Sequence

import numpy as np
from threadpoolctl import threadpool_limits

from src.application.services.regime_balance_diagnostics import (
    BootstrapClusterShareIntervals,
    ClusterBalanceSummary,
    EffectiveSampleSizes,
    QuarterlyClusterCounts,
    bootstrap_cluster_share_intervals,
    effective_sample_sizes,
    quarterly_cluster_counts,
    summarize_cluster_balance,
)
from src.domain.regime.chart_features import ChartFeatureSpec
from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.daily_temporal import DailyRegimeEpisode
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    ThreeDayChartFeatureVector,
)
from src.infrastructure.regime.sklearn_cluster_diagnostic import SklearnClusterDiagnostic


QUANTILE_METHOD = "linear"
_DISTRIBUTION_QUANTILES = (("p05", .05), ("p50", .5), ("p95", .95), ("p995", .995))
_HISTORICAL_FIRST_ANCHOR = datetime(2021, 1, 4, tzinfo=timezone.utc)
_HISTORICAL_LAST_ANCHOR = datetime(2024, 6, 30, tzinfo=timezone.utc)
_HISTORICAL_SAMPLE_COUNT = 1274
_HISTORICAL_QUARTERS = tuple(
    f"{year}-Q{quarter}"
    for year in range(2021, 2025)
    for quarter in range(1, 5)
    if year < 2024 or quarter <= 2
)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _names(values: Sequence[str], *, sorted_required: bool = False) -> tuple[str, ...]:
    result = tuple(values)
    if (
        not result
        or any(not isinstance(value, str) or not value or value != value.strip() for value in result)
        or len(set(result)) != len(result)
        or (sorted_required and result != tuple(sorted(result)))
    ):
        raise ValueError("fingerprints must be nonempty, unique, canonical, and deterministically ordered")
    return result


def _immutable(values: Mapping) -> MappingProxyType:
    return MappingProxyType(dict(values))


def _quantiles(values: Sequence[float]) -> Mapping[str, float]:
    array = np.asarray(tuple(values), dtype=float)
    if array.ndim != 1 or not len(array) or not np.isfinite(array).all():
        raise ValueError("quantile values must be nonempty and finite")
    return _immutable({key: float(np.quantile(array, q, method=QUANTILE_METHOD)) for key, q in _DISTRIBUTION_QUANTILES})


@dataclass(frozen=True)
class FeatureEnvelopeExceedance:
    lower_count: int
    upper_count: int
    lower_share: float
    upper_share: float

    def __post_init__(self) -> None:
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (self.lower_count, self.upper_count)):
            raise ValueError("envelope counts must be nonnegative integers")
        if any(not _finite(value) or not 0 <= value <= 1 for value in (self.lower_share, self.upper_share)):
            raise ValueError("envelope shares must be finite proportions")


@dataclass(frozen=True)
class TrainingEnvelopeSummary:
    feature_names: tuple[str, ...]
    sample_count: int
    per_feature: Mapping[str, FeatureEnvelopeExceedance]
    any_feature_exceedance_count: int
    any_feature_exceedance_share: float
    clipped_dimension_quantiles: Mapping[str, float]
    quantile_method: str = QUANTILE_METHOD

    def __post_init__(self) -> None:
        names = _names(self.feature_names)
        rows = dict(self.per_feature)
        quantiles = dict(self.clipped_dimension_quantiles)
        if not isinstance(self.sample_count, int) or isinstance(self.sample_count, bool) or self.sample_count <= 0:
            raise ValueError("envelope sample count must be positive")
        if tuple(rows) != names or any(not isinstance(row, FeatureEnvelopeExceedance) for row in rows.values()):
            raise ValueError("envelope feature rows must exactly follow feature names")
        if (
            not isinstance(self.any_feature_exceedance_count, int)
            or isinstance(self.any_feature_exceedance_count, bool)
            or not 0 <= self.any_feature_exceedance_count <= self.sample_count
            or not _finite(self.any_feature_exceedance_share)
            or not math.isclose(self.any_feature_exceedance_share, self.any_feature_exceedance_count / self.sample_count)
        ):
            raise ValueError("any-feature envelope summary is inconsistent")
        for row in rows.values():
            if row.lower_count > self.sample_count or row.upper_count > self.sample_count:
                raise ValueError("per-feature envelope count exceeds sample count")
            if not math.isclose(row.lower_share, row.lower_count / self.sample_count) or not math.isclose(
                row.upper_share, row.upper_count / self.sample_count
            ):
                raise ValueError("per-feature envelope shares are not count-derived")
        feature_exceedance_total = sum(row.lower_count + row.upper_count for row in rows.values())
        if (
            any(row.lower_count + row.upper_count > self.sample_count for row in rows.values())
            or self.any_feature_exceedance_count < max(
                row.lower_count + row.upper_count for row in rows.values()
            )
            or not self.any_feature_exceedance_count <= feature_exceedance_total
            or feature_exceedance_total > self.any_feature_exceedance_count * len(names)
        ):
            raise ValueError("envelope cross-field counts are inconsistent")
        if tuple(quantiles) != ("p50", "p95", "max") or any(
            not _finite(value) or not 0 <= value <= len(names) for value in quantiles.values()
        ):
            raise ValueError("clipped-dimension quantiles are invalid")
        if (
            not quantiles["p50"] <= quantiles["p95"] <= quantiles["max"]
            or quantiles["max"] != int(quantiles["max"])
            or (feature_exceedance_total == 0 and any(value != 0 for value in quantiles.values()))
            or (feature_exceedance_total > 0 and quantiles["max"] < 1)
            or (
                self.any_feature_exceedance_count > 0
                and quantiles["max"] < math.ceil(feature_exceedance_total / self.any_feature_exceedance_count)
            )
        ):
            raise ValueError("clipped-dimension quantiles are cross-field inconsistent")
        if self.quantile_method != QUANTILE_METHOD:
            raise ValueError("unsupported quantile method")
        object.__setattr__(self, "feature_names", names)
        object.__setattr__(self, "per_feature", _immutable(rows))
        object.__setattr__(self, "clipped_dimension_quantiles", _immutable(quantiles))


def summarize_training_envelope(
    raw_matrix: Sequence[Sequence[float]] | np.ndarray,
    feature_names: Sequence[str],
    lower_bounds: Sequence[float],
    upper_bounds: Sequence[float],
) -> TrainingEnvelopeSummary:
    names = _names(feature_names)
    raw_objects = np.asarray(raw_matrix, dtype=object)
    lower_values = tuple(lower_bounds)
    upper_values = tuple(upper_bounds)
    bound_objects = (*lower_values, *upper_values)
    if any(isinstance(value, (bool, np.bool_)) for value in raw_objects.flat) or any(
        isinstance(value, (bool, np.bool_)) for value in bound_objects
    ):
        raise ValueError("raw feature matrix and bounds cannot contain booleans")
    matrix = np.asarray(raw_matrix, dtype=float)
    lower = np.asarray(lower_values, dtype=float)
    upper = np.asarray(upper_values, dtype=float)
    if (
        matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] != len(names)
        or lower.shape != (len(names),) or upper.shape != (len(names),)
        or not np.isfinite(matrix).all() or not np.isfinite(lower).all() or not np.isfinite(upper).all()
        or np.any(lower >= upper)
    ):
        raise ValueError("envelope matrix and bounds must be finite with compatible positive-width dimensions")
    below = matrix < lower
    above = matrix > upper
    clipped_counts = np.count_nonzero(below | above, axis=1)
    total = len(matrix)
    rows = {
        name: FeatureEnvelopeExceedance(
            int(np.count_nonzero(below[:, index])),
            int(np.count_nonzero(above[:, index])),
            float(np.count_nonzero(below[:, index]) / total),
            float(np.count_nonzero(above[:, index]) / total),
        )
        for index, name in enumerate(names)
    }
    any_count = int(np.count_nonzero(clipped_counts))
    quantiles = {
        "p50": float(np.quantile(clipped_counts, .5, method=QUANTILE_METHOD)),
        "p95": float(np.quantile(clipped_counts, .95, method=QUANTILE_METHOD)),
        "max": float(np.max(clipped_counts)),
    }
    return TrainingEnvelopeSummary(names, total, rows, any_count, any_count / total, quantiles)


@dataclass(frozen=True)
class ReplayAssignmentDiagnostic:
    anchor_at: datetime
    fingerprint: str
    dominant_probability: float
    probability_margin: float
    mahalanobis_distance: float
    clipped_dimension_count: int

    def __post_init__(self) -> None:
        anchor = self.anchor_at
        if (
            not isinstance(anchor, datetime) or anchor.tzinfo is not timezone.utc
            or any(getattr(anchor, field) != 0 for field in ("hour", "minute", "second", "microsecond"))
        ):
            raise ValueError("diagnostic anchor must be canonical midnight UTC")
        if not isinstance(self.fingerprint, str) or not self.fingerprint or self.fingerprint != self.fingerprint.strip():
            raise ValueError("diagnostic fingerprint must be canonical")
        if (
            not _finite(self.dominant_probability) or not .0 <= self.dominant_probability <= 1.0
            or not _finite(self.probability_margin) or not .0 <= self.probability_margin <= self.dominant_probability
            or not _finite(self.mahalanobis_distance) or self.mahalanobis_distance < 0
            or not isinstance(self.clipped_dimension_count, int) or isinstance(self.clipped_dimension_count, bool)
            or self.clipped_dimension_count < 0
        ):
            raise ValueError("assignment diagnostic values are invalid")


def diagnose_gmm_assignments(
    fit: ClusterDiagnosticFit,
    vectors: Sequence[ThreeDayChartFeatureVector],
    registry: Sequence[ChartFeatureSpec],
) -> tuple[ReplayAssignmentDiagnostic, ...]:
    if not isinstance(fit, ClusterDiagnosticFit) or fit.config.model_type != "gmm" or fit.config.covariance_type != "diag":
        raise ValueError("historical replay requires a fixed diagonal GMM diagnostic fit")
    values = tuple(vectors)
    specs = tuple(registry)
    if not values or any(not isinstance(value, ThreeDayChartFeatureVector) for value in values):
        raise ValueError("replay vectors must be nonempty three-day feature vectors")
    if specs != THREE_DAY_CHART_FEATURE_REGISTRY_V1:
        raise ValueError("replay registry must be the frozen three-day registry")
    anchors = tuple(value.anchor_at for value in values)
    if any(current <= previous for previous, current in zip(anchors, anchors[1:])):
        raise ValueError("replay vectors must be chronological and unique")
    registry_names = tuple(spec.name for spec in specs)
    if any(tuple(vector.values) != registry_names for vector in values):
        raise ValueError("replay vector dimensions or order do not match the registry")
    if any(vector.symbol != fit.symbol or vector.schema_version != fit.schema_version for vector in values):
        raise ValueError("replay vectors do not match the fixed fit identity")
    indices = tuple(registry_names.index(name) for name in fit.feature_names)
    with threadpool_limits(1):
        raw = np.asarray([[tuple(vector.values.values())[index] for index in indices] for vector in values], dtype=float)
        lower = np.asarray(fit.lower_bounds, dtype=float)
        upper = np.asarray(fit.upper_bounds, dtype=float)
        clipped_counts = np.count_nonzero((raw < lower) | (raw > upper), axis=1)
        scaled = (np.clip(raw, lower, upper) - np.asarray(fit.medians)) / np.asarray(fit.scales)
        assignments = SklearnClusterDiagnostic().assign(fit, values, specs)
        if len(assignments) != len(values):
            raise ValueError("diagnostic adapter returned the wrong assignment count")
        results = []
        for index, assignment in enumerate(assignments):
            if assignment.fingerprint not in fit.fingerprints:
                raise ValueError("diagnostic adapter returned an unknown fingerprint")
            component = fit.fingerprints.index(assignment.fingerprint)
            delta = scaled[index] - np.asarray(fit.means[component])
            covariance = np.asarray(fit.covariances[component])
            distance = float(np.sqrt(np.sum(delta * delta / covariance)))
            margin = float(assignment.dominant_probability - assignment.second_probability)
            results.append(ReplayAssignmentDiagnostic(
                values[index].anchor_at,
                assignment.fingerprint,
                float(assignment.dominant_probability),
                margin,
                distance,
                int(clipped_counts[index]),
            ))
        if any(not np.isfinite((row.dominant_probability, row.probability_margin, row.mahalanobis_distance)).all() for row in results):
            raise ValueError("assignment diagnostics must be finite")
        return tuple(results)


@dataclass(frozen=True)
class ConfidenceReference:
    fingerprints: tuple[str, ...]
    sample_count: int
    posterior_fifth_percentile: float
    margin_fifth_percentile: float
    component_distance_995: Mapping[str, float]
    posterior_quantiles: Mapping[str, float]
    margin_quantiles: Mapping[str, float]
    distance_quantiles: Mapping[str, float]
    quantile_method: str = QUANTILE_METHOD

    def __post_init__(self) -> None:
        names = _names(self.fingerprints, sorted_required=True)
        distances = dict(self.component_distance_995)
        quantile_maps = tuple(dict(value) for value in (self.posterior_quantiles, self.margin_quantiles, self.distance_quantiles))
        if not isinstance(self.sample_count, int) or isinstance(self.sample_count, bool) or self.sample_count <= 0:
            raise ValueError("confidence reference sample count must be positive")
        if tuple(distances) != names or any(not _finite(value) or value < 0 for value in distances.values()):
            raise ValueError("component distance references must follow frozen fingerprints")
        if any(tuple(row) != tuple(key for key, _ in _DISTRIBUTION_QUANTILES) or any(not _finite(value) for value in row.values()) for row in quantile_maps):
            raise ValueError("confidence quantiles are invalid")
        if not _finite(self.posterior_fifth_percentile) or not math.isclose(self.posterior_fifth_percentile, quantile_maps[0]["p05"]):
            raise ValueError("posterior reference is inconsistent")
        if not _finite(self.margin_fifth_percentile) or not math.isclose(self.margin_fifth_percentile, quantile_maps[1]["p05"]):
            raise ValueError("margin reference is inconsistent")
        if self.quantile_method != QUANTILE_METHOD:
            raise ValueError("unsupported quantile method")
        object.__setattr__(self, "fingerprints", names)
        object.__setattr__(self, "component_distance_995", _immutable(distances))
        object.__setattr__(self, "posterior_quantiles", _immutable(quantile_maps[0]))
        object.__setattr__(self, "margin_quantiles", _immutable(quantile_maps[1]))
        object.__setattr__(self, "distance_quantiles", _immutable(quantile_maps[2]))


def _validate_diagnostics(values: Sequence[ReplayAssignmentDiagnostic], fingerprints: tuple[str, ...]) -> tuple[ReplayAssignmentDiagnostic, ...]:
    rows = tuple(values)
    if not rows or any(not isinstance(row, ReplayAssignmentDiagnostic) for row in rows):
        raise ValueError("assignment diagnostics must be nonempty canonical diagnostics")
    if any(row.fingerprint not in fingerprints for row in rows):
        raise ValueError("assignment diagnostic contains an unknown fingerprint")
    if any(current.anchor_at <= previous.anchor_at for previous, current in zip(rows, rows[1:])):
        raise ValueError("assignment diagnostics must be chronological and unique")
    return rows


def build_confidence_reference(
    training: Sequence[ReplayAssignmentDiagnostic], fingerprints: Sequence[str]
) -> ConfidenceReference:
    names = _names(fingerprints, sorted_required=True)
    rows = _validate_diagnostics(training, names)
    missing = [name for name in names if not any(row.fingerprint == name for row in rows)]
    if missing:
        raise ValueError("every frozen component requires training assignments")
    posterior = _quantiles([row.dominant_probability for row in rows])
    margin = _quantiles([row.probability_margin for row in rows])
    distance = _quantiles([row.mahalanobis_distance for row in rows])
    component = {
        name: float(np.quantile(
            [row.mahalanobis_distance for row in rows if row.fingerprint == name],
            .995,
            method=QUANTILE_METHOD,
        ))
        for name in names
    }
    return ConfidenceReference(names, len(rows), posterior["p05"], margin["p05"], component, posterior, margin, distance)


@dataclass(frozen=True)
class ConfidenceComparison:
    sample_count: int
    posterior_below_reference_count: int
    posterior_below_reference_share: float
    margin_below_reference_count: int
    margin_below_reference_share: float
    component_distance_above_reference_count: int
    component_distance_above_reference_share: float
    posterior_quantiles: Mapping[str, float] | None = None
    margin_quantiles: Mapping[str, float] | None = None
    distance_quantiles: Mapping[str, float] | None = None
    quantile_method: str = QUANTILE_METHOD

    def __post_init__(self) -> None:
        if not isinstance(self.sample_count, int) or isinstance(self.sample_count, bool) or self.sample_count <= 0:
            raise ValueError("confidence comparison sample count must be positive")
        for count, share in (
            (self.posterior_below_reference_count, self.posterior_below_reference_share),
            (self.margin_below_reference_count, self.margin_below_reference_share),
            (self.component_distance_above_reference_count, self.component_distance_above_reference_share),
        ):
            if (
                not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= self.sample_count
                or not _finite(share) or not math.isclose(share, count / self.sample_count)
            ):
                raise ValueError("confidence tail share must be count-derived")
        for name in ("posterior_quantiles", "margin_quantiles", "distance_quantiles"):
            value = getattr(self, name)
            if value is None:
                continue
            copied = dict(value)
            if tuple(copied) != tuple(key for key, _ in _DISTRIBUTION_QUANTILES) or any(not _finite(item) for item in copied.values()):
                raise ValueError("historical confidence quantiles are invalid")
            object.__setattr__(self, name, _immutable(copied))
        if self.quantile_method != QUANTILE_METHOD:
            raise ValueError("unsupported quantile method")


def compare_confidence_to_training(
    historical: Sequence[ReplayAssignmentDiagnostic], reference: ConfidenceReference
) -> ConfidenceComparison:
    if not isinstance(reference, ConfidenceReference):
        raise ValueError("confidence reference must be canonical")
    rows = _validate_diagnostics(historical, reference.fingerprints)
    posterior_count = sum(row.dominant_probability < reference.posterior_fifth_percentile for row in rows)
    margin_count = sum(row.probability_margin < reference.margin_fifth_percentile for row in rows)
    distance_count = sum(row.mahalanobis_distance > reference.component_distance_995[row.fingerprint] for row in rows)
    total = len(rows)
    return ConfidenceComparison(
        total, posterior_count, posterior_count / total, margin_count, margin_count / total,
        distance_count, distance_count / total,
        _quantiles([row.dominant_probability for row in rows]),
        _quantiles([row.probability_margin for row in rows]),
        _quantiles([row.mahalanobis_distance for row in rows]),
    )


def jensen_shannon_divergence(
    training_shares: Mapping[str, float], historical_shares: Mapping[str, float], fingerprints: Sequence[str]
) -> float:
    names = _names(fingerprints, sorted_required=True)
    p_map, q_map = dict(training_shares), dict(historical_shares)
    if tuple(p_map) != names or tuple(q_map) != names:
        raise ValueError("JSD shares must exactly follow frozen fingerprint order")
    if any(not _finite(value) or value < 0 for value in (*p_map.values(), *q_map.values())):
        raise ValueError("JSD shares must be finite and nonnegative")
    if not math.isclose(math.fsum(p_map.values()), 1.0, abs_tol=1e-12) or not math.isclose(math.fsum(q_map.values()), 1.0, abs_tol=1e-12):
        raise ValueError("JSD distributions must sum to one")
    p, q = np.asarray(tuple(p_map.values())), np.asarray(tuple(q_map.values()))
    middle = (p + q) / 2
    result = .5 * sum(float(value * math.log(value / middle[index])) for index, value in enumerate(p) if value > 0)
    result += .5 * sum(float(value * math.log(value / middle[index])) for index, value in enumerate(q) if value > 0)
    if not math.isfinite(result) or result < -1e-15:
        raise ValueError("JSD calculation produced an invalid result")
    return max(0.0, float(result))


@dataclass(frozen=True)
class QuarterWarning:
    quarter: str
    zero_count_fingerprints: tuple[str, ...]
    concentrated_fingerprints: tuple[str, ...]

    def __post_init__(self) -> None:
        zero = tuple(self.zero_count_fingerprints)
        concentrated = tuple(self.concentrated_fingerprints)
        if not isinstance(self.quarter, str) or re.fullmatch(r"\d{4}-Q[1-4]", self.quarter) is None:
            raise ValueError("quarter warning key must be canonical")
        if any(
            not isinstance(value, str) or not value or value != value.strip()
            for value in (*zero, *concentrated)
        ) or len(set(zero)) != len(zero) or len(set(concentrated)) != len(concentrated):
            raise ValueError("quarter warning fingerprints must be canonical and unique")
        if not zero and not concentrated:
            raise ValueError("quarter warning must describe an actual warning")
        object.__setattr__(self, "zero_count_fingerprints", zero)
        object.__setattr__(self, "concentrated_fingerprints", concentrated)


@dataclass(frozen=True)
class HistoricalReplayCandidateResult:
    identity: str
    cluster_count: int
    fingerprints: tuple[str, ...]
    envelope: TrainingEnvelopeSummary
    confidence: ConfidenceComparison
    balance: ClusterBalanceSummary
    quarterly: QuarterlyClusterCounts
    quarter_warnings: tuple[QuarterWarning, ...]
    bootstrap: BootstrapClusterShareIntervals
    effective_sample_sizes: EffectiveSampleSizes
    jensen_shannon_divergence: float
    diagnostics: tuple[ReplayAssignmentDiagnostic, ...]

    def __post_init__(self) -> None:
        names = _names(self.fingerprints, sorted_required=True)
        if not isinstance(self.identity, str) or not self.identity or self.identity != self.identity.strip():
            raise ValueError("candidate identity must be canonical")
        if not isinstance(self.cluster_count, int) or isinstance(self.cluster_count, bool) or self.cluster_count != len(names):
            raise ValueError("candidate cluster count must match fingerprints")
        if self.identity != f"gmm-diag-k{self.cluster_count}":
            raise ValueError("candidate identity must match a fixed diagonal GMM cluster count")
        if any(not isinstance(value, expected) for value, expected in (
            (self.envelope, TrainingEnvelopeSummary), (self.confidence, ConfidenceComparison),
            (self.balance, ClusterBalanceSummary), (self.quarterly, QuarterlyClusterCounts),
            (self.bootstrap, BootstrapClusterShareIntervals), (self.effective_sample_sizes, EffectiveSampleSizes),
        )):
            raise ValueError("candidate summaries must use canonical result types")
        diagnostics = _validate_diagnostics(self.diagnostics, names)
        _validate_historical_anchors(diagnostics)
        clipped_counts = tuple(row.clipped_dimension_count for row in diagnostics)
        expected_any_count = sum(count > 0 for count in clipped_counts)
        expected_clipped_quantiles = {
            "p50": float(np.quantile(clipped_counts, .5, method=QUANTILE_METHOD)),
            "p95": float(np.quantile(clipped_counts, .95, method=QUANTILE_METHOD)),
            "max": float(max(clipped_counts)),
        }
        if not _finite(self.jensen_shannon_divergence) or not 0 <= self.jensen_shannon_divergence <= math.log(2) + 1e-12:
            raise ValueError("candidate JSD is invalid")
        labels = tuple(row.fingerprint for row in diagnostics)
        if self.balance != summarize_cluster_balance(labels, names):
            raise ValueError("candidate balance is not diagnostic-derived")
        expected_episodes = tuple(DailyRegimeEpisode(
            row.anchor_at, row.anchor_at - timedelta(days=3), row.anchor_at, row.anchor_at + timedelta(days=1)
        ) for row in diagnostics)
        if self.quarterly != quarterly_cluster_counts(expected_episodes, labels, names):
            raise ValueError("candidate quarterly counts are not diagnostic-derived")
        if self.confidence.sample_count != len(diagnostics) or self.envelope.sample_count != len(diagnostics):
            raise ValueError("candidate summary sample counts disagree")
        if (
            self.envelope.any_feature_exceedance_count != expected_any_count
            or dict(self.envelope.clipped_dimension_quantiles) != expected_clipped_quantiles
        ):
            raise ValueError("candidate envelope is not per-anchor-diagnostic-derived")
        if self.quarterly.total != len(diagnostics) or self.bootstrap.sample_count != len(diagnostics) or self.effective_sample_sizes.sample_count != len(diagnostics):
            raise ValueError("candidate overlap-aware summary counts disagree")
        if self.quarterly.quarters != _HISTORICAL_QUARTERS:
            raise ValueError("candidate replay must contain exactly the 14 canonical quarters")
        if tuple(self.balance.fingerprints) != names or tuple(self.quarterly.fingerprints) != names:
            raise ValueError("candidate summaries do not follow frozen fingerprints")
        if any(not isinstance(value, QuarterWarning) for value in self.quarter_warnings):
            raise ValueError("quarter warnings must be canonical")
        expected_warnings = []
        for quarter in self.quarterly.quarters:
            counts = self.quarterly.counts[quarter]
            total = sum(counts.values())
            zero = tuple(name for name in names if counts[name] == 0)
            concentrated = tuple(name for name in names if counts[name] / total > .5)
            if zero or concentrated:
                expected_warnings.append(QuarterWarning(quarter, zero, concentrated))
        if self.quarter_warnings != tuple(expected_warnings):
            raise ValueError("quarter warnings are not quarterly-count-derived")
        if (
            tuple(self.bootstrap.fingerprints) != names
            or tuple(self.effective_sample_sizes.fingerprints) != names
            or self.bootstrap.block_length != 3 or self.bootstrap.resamples != 5000
            or self.bootstrap.confidence != .95 or self.bootstrap.seed != 20260714
            or self.effective_sample_sizes.max_lag != 30
        ):
            raise ValueError("candidate overlap-aware diagnostics do not use the frozen contract")
        if self.effective_sample_sizes != effective_sample_sizes(labels, names, max_lag=30):
            raise ValueError("candidate effective sample sizes are not diagnostic-derived")
        if any(
            not math.isclose(self.bootstrap.intervals[name].point, self.balance.shares[name], rel_tol=1e-12, abs_tol=1e-12)
            for name in names
        ):
            raise ValueError("candidate bootstrap points are not diagnostic-derived")
        object.__setattr__(self, "fingerprints", names)
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def quarter_warning_count(self) -> int:
        return sum(bool(item.zero_count_fingerprints) for item in self.quarter_warnings)


def summarize_historical_replay_candidate(
    *, identity: str, fit: ClusterDiagnosticFit, vectors: Sequence[ThreeDayChartFeatureVector],
    diagnostics: Sequence[ReplayAssignmentDiagnostic], reference: ConfidenceReference,
    training_shares: Mapping[str, float],
) -> HistoricalReplayCandidateResult:
    with threadpool_limits(1):
        return _summarize_historical_replay_candidate_single_thread(
            identity=identity, fit=fit, vectors=vectors, diagnostics=diagnostics,
            reference=reference, training_shares=training_shares,
        )


def _summarize_historical_replay_candidate_single_thread(
    *, identity: str, fit: ClusterDiagnosticFit, vectors: Sequence[ThreeDayChartFeatureVector],
    diagnostics: Sequence[ReplayAssignmentDiagnostic], reference: ConfidenceReference,
    training_shares: Mapping[str, float],
) -> HistoricalReplayCandidateResult:
    if (
        not isinstance(fit, ClusterDiagnosticFit)
        or fit.config.model_type != "gmm"
        or fit.config.covariance_type != "diag"
    ):
        raise ValueError("candidate fit must be a fixed diagonal GMM diagnostic fit")
    expected_identity = f"gmm-diag-k{fit.config.cluster_count}"
    if identity != expected_identity:
        raise ValueError("candidate identity must match the fixed diagonal GMM fit")
    values = tuple(vectors)
    rows = _validate_diagnostics(diagnostics, fit.fingerprints)
    _validate_historical_anchors(rows)
    if len(values) != len(rows) or any(vector.anchor_at != row.anchor_at for vector, row in zip(values, rows)):
        raise ValueError("candidate vectors and diagnostics must align exactly")
    registry_names = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    indices = tuple(registry_names.index(name) for name in fit.feature_names)
    matrix = np.asarray([[tuple(vector.values.values())[index] for index in indices] for vector in values], dtype=float)
    envelope = summarize_training_envelope(matrix, fit.feature_names, fit.lower_bounds, fit.upper_bounds)
    labels = tuple(row.fingerprint for row in rows)
    balance = summarize_cluster_balance(labels, fit.fingerprints)
    episodes = tuple(DailyRegimeEpisode(
        row.anchor_at, row.anchor_at - timedelta(days=3), row.anchor_at, row.anchor_at + timedelta(days=1)
    ) for row in rows)
    quarterly = quarterly_cluster_counts(episodes, labels, fit.fingerprints)
    warnings = []
    for quarter in quarterly.quarters:
        counts = quarterly.counts[quarter]
        total = sum(counts.values())
        zero = tuple(name for name in fit.fingerprints if counts[name] == 0)
        concentrated = tuple(name for name in fit.fingerprints if counts[name] / total > .5)
        if zero or concentrated:
            warnings.append(QuarterWarning(quarter, zero, concentrated))
    bootstrap = bootstrap_cluster_share_intervals(labels, fit.fingerprints, block_length=3, resamples=5000, confidence=.95, seed=20260714)
    ess = effective_sample_sizes(labels, fit.fingerprints, max_lag=30)
    confidence = compare_confidence_to_training(rows, reference)
    divergence = jensen_shannon_divergence(training_shares, balance.shares, fit.fingerprints)
    return HistoricalReplayCandidateResult(
        identity, fit.config.cluster_count, fit.fingerprints, envelope, confidence, balance, quarterly,
        tuple(warnings), bootstrap, ess, divergence, rows,
    )


def rank_historical_replay_candidates(
    results: Sequence[HistoricalReplayCandidateResult],
) -> tuple[HistoricalReplayCandidateResult, ...]:
    values = tuple(results)
    if not values or any(not isinstance(value, HistoricalReplayCandidateResult) for value in values):
        raise ValueError("historical replay candidates must be nonempty canonical results")
    if len({value.identity for value in values}) != len(values):
        raise ValueError("historical replay candidate identities must be unique")
    for value in values:
        _revalidate_candidate_result(value)
    return tuple(sorted(values, key=lambda item: _research_preference_key(
        item.envelope.any_feature_exceedance_share,
        item.confidence.margin_below_reference_share,
        item.confidence.component_distance_above_reference_share,
        item.quarter_warning_count,
        item.effective_sample_sizes.minimum,
        item.jensen_shannon_divergence,
        item.cluster_count,
        item.identity,
    )))


def _research_preference_key(
    clipping_share: float, margin_tail_share: float, distance_tail_share: float,
    empty_quarter_warning_count: int, minimum_effective_sample_size: float,
    divergence: float, cluster_count: int, identity: str,
) -> tuple[float, float, float, int, float, float, int, str]:
    shares = (clipping_share, margin_tail_share, distance_tail_share)
    if any(not _finite(value) or not 0 <= value <= 1 for value in shares):
        raise ValueError("research preference shares must be finite proportions")
    if (
        not isinstance(empty_quarter_warning_count, int) or isinstance(empty_quarter_warning_count, bool)
        or empty_quarter_warning_count < 0
        or not _finite(minimum_effective_sample_size) or minimum_effective_sample_size < 1
        or not _finite(divergence) or not 0 <= divergence <= math.log(2) + 1e-12
        or not isinstance(cluster_count, int) or isinstance(cluster_count, bool) or cluster_count <= 0
        or not isinstance(identity, str) or not identity or identity != identity.strip()
    ):
        raise ValueError("research preference values are invalid")
    return (
        clipping_share, margin_tail_share, distance_tail_share,
        empty_quarter_warning_count, -minimum_effective_sample_size,
        divergence, cluster_count, identity,
    )


def _validate_historical_anchors(diagnostics: Sequence[ReplayAssignmentDiagnostic]) -> None:
    anchors = tuple(row.anchor_at for row in diagnostics)
    if (
        len(anchors) != _HISTORICAL_SAMPLE_COUNT
        or anchors[0] != _HISTORICAL_FIRST_ANCHOR
        or anchors[-1] != _HISTORICAL_LAST_ANCHOR
        or any(current != previous + timedelta(days=1) for previous, current in zip(anchors, anchors[1:]))
    ):
        raise ValueError("candidate replay must use the 1,274 canonical historical daily anchors")


def _revalidate_candidate_result(value: HistoricalReplayCandidateResult) -> None:
    HistoricalReplayCandidateResult(
        value.identity, value.cluster_count, value.fingerprints, value.envelope,
        value.confidence, value.balance, value.quarterly, value.quarter_warnings,
        value.bootstrap, value.effective_sample_sizes, value.jensen_shannon_divergence,
        value.diagnostics,
    )


__all__ = [
    "ConfidenceComparison", "ConfidenceReference", "FeatureEnvelopeExceedance",
    "HistoricalReplayCandidateResult", "QUANTILE_METHOD", "QuarterWarning",
    "ReplayAssignmentDiagnostic", "TrainingEnvelopeSummary", "build_confidence_reference",
    "compare_confidence_to_training", "diagnose_gmm_assignments", "jensen_shannon_divergence",
    "rank_historical_replay_candidates", "summarize_historical_replay_candidate",
    "summarize_training_envelope",
]
