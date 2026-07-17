"""Descriptive Component 0 OOD cause summary for the frozen K4 diagnosis."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from statistics import median
from typing import Sequence

from src.application.services.frozen_k4_failure_decomposition import FrozenK4Decomposition
from src.domain.regime import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)


_ANALYSIS_SCOPE = "component_zero_strict_ood_feature_contribution"
_COMPONENT_INDEX = 0
_ASSIGNED_SAMPLE_COUNT = 409
_OOD_SAMPLE_COUNT = 24
_SINGLE_FEATURE_THRESHOLD = 0.50
_VOLATILITY_FAMILY_THRESHOLD = 0.70
_RECURRENT_FEATURE_THRESHOLD = 0.50


def _is_finite_nonnegative(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _at_least(value: float, threshold: float) -> bool:
    return value >= threshold or math.isclose(value, threshold, rel_tol=0, abs_tol=1e-12)


def _validate_scope_identity(scope: str, component_index: int, fingerprint: str) -> None:
    if scope != _ANALYSIS_SCOPE or component_index != _COMPONENT_INDEX:
        raise ValueError("Component 0 OOD analysis identity is not canonical")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 24
        or fingerprint != fingerprint.lower()
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ValueError("component fingerprint is not canonical")


def _validate_registry_identity(schema_version: str, registry_sha256: str) -> None:
    if schema_version != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION:
        raise ValueError("registry schema version is not canonical")
    if (
        not isinstance(registry_sha256, str)
        or len(registry_sha256) != 64
        or registry_sha256 != registry_sha256.lower()
        or any(character not in "0123456789abcdef" for character in registry_sha256)
    ):
        raise ValueError("registry hash is not canonical")


@dataclass(frozen=True)
class OODFeatureSummaryRow:
    analysis_scope: str
    primary_component_index: int
    primary_component_fingerprint: str
    feature_name: str
    registry_family: str
    registry_schema_version: str
    registry_sha256: str
    contribution_sum: float
    contribution_ratio: float
    contribution_mean: float
    contribution_median: float
    top1_count: int
    top1_ratio: float
    top5_count: int
    top5_ratio: float
    rank: int

    def __post_init__(self) -> None:
        _validate_scope_identity(
            self.analysis_scope,
            self.primary_component_index,
            self.primary_component_fingerprint,
        )
        _validate_registry_identity(self.registry_schema_version, self.registry_sha256)
        if not self.feature_name or not self.registry_family:
            raise ValueError("feature row registry identity must be nonblank")
        for value in (
            self.contribution_sum,
            self.contribution_ratio,
            self.contribution_mean,
            self.contribution_median,
            self.top1_ratio,
            self.top5_ratio,
        ):
            if not _is_finite_nonnegative(value):
                raise ValueError("feature contribution statistics must be finite and nonnegative")
        if self.contribution_ratio > 1 or self.top1_ratio > 1 or self.top5_ratio > 1:
            raise ValueError("feature ratios must be at most one")
        if not math.isclose(
            self.contribution_mean,
            self.contribution_sum / _OOD_SAMPLE_COUNT,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("feature contribution mean does not reconcile with its sum")
        if (
            not isinstance(self.top1_count, int)
            or isinstance(self.top1_count, bool)
            or not 0 <= self.top1_count <= _OOD_SAMPLE_COUNT
            or not isinstance(self.top5_count, int)
            or isinstance(self.top5_count, bool)
            or not 0 <= self.top5_count <= _OOD_SAMPLE_COUNT
            or self.top1_count > self.top5_count
            or not math.isclose(self.top1_ratio, self.top1_count / _OOD_SAMPLE_COUNT, abs_tol=1e-15)
            or not math.isclose(self.top5_ratio, self.top5_count / _OOD_SAMPLE_COUNT, abs_tol=1e-15)
            or not isinstance(self.rank, int)
            or isinstance(self.rank, bool)
            or self.rank < 1
        ):
            raise ValueError("feature counts, ratios, or rank are inconsistent")


@dataclass(frozen=True)
class OODFamilySummaryRow:
    analysis_scope: str
    primary_component_index: int
    primary_component_fingerprint: str
    family_name: str
    family_feature_names: tuple[str, ...]
    registry_schema_version: str
    registry_sha256: str
    contribution_sum: float
    contribution_ratio: float
    concentration_threshold: float
    concentration_rule_applies: bool
    concentration_result: bool

    def __post_init__(self) -> None:
        _validate_scope_identity(
            self.analysis_scope,
            self.primary_component_index,
            self.primary_component_fingerprint,
        )
        _validate_registry_identity(self.registry_schema_version, self.registry_sha256)
        if (
            not self.family_name
            or not isinstance(self.family_feature_names, tuple)
            or not self.family_feature_names
            or len(set(self.family_feature_names)) != len(self.family_feature_names)
            or any(not name for name in self.family_feature_names)
        ):
            raise ValueError("family identity must contain unique feature names")
        if not _is_finite_nonnegative(self.contribution_sum):
            raise ValueError("family contribution must be finite and nonnegative")
        if not _is_finite_nonnegative(self.contribution_ratio) or self.contribution_ratio > 1:
            raise ValueError("family contribution ratio must be in [0, 1]")
        if self.concentration_threshold != _VOLATILITY_FAMILY_THRESHOLD:
            raise ValueError("family concentration threshold is not canonical")
        expected_applies = self.family_name == "volatility"
        expected_result = expected_applies and _at_least(
            self.contribution_ratio, self.concentration_threshold
        )
        if self.concentration_rule_applies is not expected_applies or self.concentration_result is not expected_result:
            raise ValueError("family concentration flags are inconsistent")


@dataclass(frozen=True)
class ComponentZeroOODAnalysis:
    analysis_scope: str
    primary_component_index: int
    primary_component_fingerprint: str
    assigned_sample_count: int
    ood_sample_count: int
    registry_schema_version: str
    registry_sha256: str
    feature_rows: tuple[OODFeatureSummaryRow, ...]
    family_rows: tuple[OODFamilySummaryRow, ...]
    top_five_features: tuple[str, ...]
    single_feature_concentration: bool
    volatility_family_concentration: bool
    recurrent_feature_dominance: bool
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        _validate_scope_identity(
            self.analysis_scope,
            self.primary_component_index,
            self.primary_component_fingerprint,
        )
        _validate_registry_identity(self.registry_schema_version, self.registry_sha256)
        if self.assigned_sample_count != _ASSIGNED_SAMPLE_COUNT or self.ood_sample_count != _OOD_SAMPLE_COUNT:
            raise ValueError("Component 0 population receipt is not canonical")
        if (
            not isinstance(self.feature_rows, tuple)
            or not self.feature_rows
            or not isinstance(self.family_rows, tuple)
            or not self.family_rows
            or not isinstance(self.top_five_features, tuple)
            or self.diagnostic_only is not True
        ):
            raise ValueError("analysis contents must be immutable and diagnostic-only")
        feature_names = tuple(row.feature_name for row in self.feature_rows)
        family_names = tuple(row.family_name for row in self.family_rows)
        if len(set(feature_names)) != len(feature_names) or len(set(family_names)) != len(family_names):
            raise ValueError("analysis row identities must be unique")
        if tuple(row.rank for row in self.feature_rows) != tuple(range(1, len(self.feature_rows) + 1)):
            raise ValueError("feature rows must be in rank order")
        if self.top_five_features != feature_names[:5]:
            raise ValueError("top-five features must reproduce feature rank order")
        if any(
            row.analysis_scope != self.analysis_scope
            or row.primary_component_fingerprint != self.primary_component_fingerprint
            or row.registry_sha256 != self.registry_sha256
            for row in (*self.feature_rows, *self.family_rows)
        ):
            raise ValueError("nested analysis provenance is inconsistent")
        if not math.isclose(sum(row.contribution_ratio for row in self.feature_rows), 1.0, abs_tol=1e-12):
            raise ValueError("feature contribution ratios do not reconcile")
        if not math.isclose(sum(row.contribution_ratio for row in self.family_rows), 1.0, abs_tol=1e-12):
            raise ValueError("family contribution ratios do not reconcile")
        total_sum = sum(row.contribution_sum for row in self.feature_rows)
        if total_sum <= 0 or any(
            not math.isclose(
                row.contribution_ratio,
                row.contribution_sum / total_sum,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            for row in self.feature_rows
        ):
            raise ValueError("feature contribution sums and ratios do not reconcile")
        family_features = tuple(
            name for row in self.family_rows for name in row.family_feature_names
        )
        if len(family_features) != len(set(family_features)) or set(family_features) != set(feature_names):
            raise ValueError("family rows must partition all retained features")
        feature_by_name = {row.feature_name: row for row in self.feature_rows}
        for family in self.family_rows:
            family_sum = sum(
                feature_by_name[name].contribution_sum
                for name in family.family_feature_names
            )
            if (
                any(
                    feature_by_name[name].registry_family != family.family_name
                    for name in family.family_feature_names
                )
                or not math.isclose(
                    family.contribution_sum, family_sum, rel_tol=1e-12, abs_tol=1e-12
                )
                or not math.isclose(
                    family.contribution_ratio,
                    family_sum / total_sum,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            ):
                raise ValueError("family membership and contribution statistics do not reconcile")
        expected_single = _at_least(
            max(row.contribution_ratio for row in self.feature_rows),
            _SINGLE_FEATURE_THRESHOLD,
        )
        volatility = next((row for row in self.family_rows if row.family_name == "volatility"), None)
        expected_volatility = volatility is not None and _at_least(
            volatility.contribution_ratio, _VOLATILITY_FAMILY_THRESHOLD
        )
        expected_recurrent = any(
            _at_least(row.top1_ratio, _RECURRENT_FEATURE_THRESHOLD)
            for row in self.feature_rows
        )
        if (
            self.single_feature_concentration is not expected_single
            or self.volatility_family_concentration is not expected_volatility
            or self.recurrent_feature_dominance is not expected_recurrent
        ):
            raise ValueError("analysis concentration flags are inconsistent")


def _registry_sha256(
    retained_feature_names: Sequence[str],
    registry: Sequence[object],
    registry_schema_version: str,
) -> str:
    payload = {
        "registry_schema_version": registry_schema_version,
        "retained_feature_names": list(retained_feature_names),
        "registry": [
            {
                "name": spec.name,
                "family": spec.family,
                "aggregation_minutes": spec.aggregation_minutes,
                "lookback_minutes": spec.lookback_minutes,
                "formula": spec.formula,
            }
            for spec in registry
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def summarize_component_zero_ood(
    decomposition: FrozenK4Decomposition,
    *,
    retained_feature_names: Sequence[str],
    registry: Sequence[object] = THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    registry_schema_version: str = THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
) -> ComponentZeroOODAnalysis:
    if not isinstance(decomposition, FrozenK4Decomposition):
        raise ValueError("Component 0 summary requires FrozenK4Decomposition")
    if tuple(registry) != THREE_DAY_CHART_FEATURE_REGISTRY_V1:
        raise ValueError("Component 0 summary requires the canonical V1 registry")
    if registry_schema_version != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION:
        raise ValueError("Component 0 summary requires the canonical registry schema")
    names = tuple(retained_feature_names)
    registry_names = tuple(spec.name for spec in registry)
    if (
        not names
        or len(set(names)) != len(names)
        or tuple(name for name in registry_names if name in set(names)) != names
        or any(name not in registry_names for name in names)
    ):
        raise ValueError("retained features must be a unique registry-order subsequence")

    component_rows = tuple(row for row in decomposition.ood_by_component if row.component_index == 0)
    if len(component_rows) != 1:
        raise ValueError("exactly one Component 0 OOD receipt is required")
    component = component_rows[0]
    if (
        component.sample_count != _ASSIGNED_SAMPLE_COUNT
        or component.exceedance_count != _OOD_SAMPLE_COUNT
        or not math.isclose(component.exceedance_rate, _OOD_SAMPLE_COUNT / _ASSIGNED_SAMPLE_COUNT, rel_tol=0, abs_tol=1e-15)
    ):
        raise ValueError("Component 0 OOD receipt must reproduce 24/409")
    _validate_scope_identity(_ANALYSIS_SCOPE, 0, component.component_fingerprint)

    samples = tuple(row for row in decomposition.ood_samples if row.component_index == 0)
    if len(samples) != _OOD_SAMPLE_COUNT or len({row.anchor_at for row in samples}) != len(samples):
        raise ValueError("exactly 24 uniquely identified Component 0 OOD samples are required")
    expected_keys = set(names)
    contributions_by_feature = {name: [] for name in names}
    top1_counts = dict.fromkeys(names, 0)
    top5_counts = dict.fromkeys(names, 0)
    registry_position = {name: index for index, name in enumerate(names)}
    for sample in samples:
        if sample.component_fingerprint != component.component_fingerprint:
            raise ValueError("Component 0 fingerprints do not agree")
        if not _is_finite_nonnegative(sample.squared_mahalanobis) or not _is_finite_nonnegative(sample.threshold):
            raise ValueError("OOD distances and thresholds must be finite and nonnegative")
        if sample.squared_mahalanobis <= sample.threshold:
            raise ValueError("Component 0 OOD sample is not a strict exceedance")
        contribution_map = sample.feature_contributions
        if len(contribution_map) != len(names) or set(contribution_map) != expected_keys:
            raise ValueError("sample contributions must exactly match retained features")
        values = []
        for name in names:
            value = contribution_map[name]
            if not _is_finite_nonnegative(value):
                raise ValueError("sample contributions must be finite and nonnegative")
            numeric = float(value)
            contributions_by_feature[name].append(numeric)
            values.append(numeric)
        if not math.isclose(sum(values), sample.squared_mahalanobis, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("sample contributions do not reproduce squared Mahalanobis distance")
        ordered = sorted(names, key=lambda name: (-float(contribution_map[name]), registry_position[name]))
        top1_counts[ordered[0]] += 1
        for name in ordered[:5]:
            top5_counts[name] += 1

    total = sum(sum(values) for values in contributions_by_feature.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("total OOD feature contribution must be positive and finite")
    totals = {name: sum(contributions_by_feature[name]) for name in names}
    ranked_names = tuple(sorted(names, key=lambda name: (-totals[name], registry_position[name])))
    registry_by_name = {spec.name: spec for spec in registry}
    registry_hash = _registry_sha256(names, registry, registry_schema_version)
    feature_rows = tuple(
        OODFeatureSummaryRow(
            _ANALYSIS_SCOPE,
            0,
            component.component_fingerprint,
            name,
            registry_by_name[name].family,
            registry_schema_version,
            registry_hash,
            totals[name],
            totals[name] / total,
            totals[name] / _OOD_SAMPLE_COUNT,
            median(contributions_by_feature[name]),
            top1_counts[name],
            top1_counts[name] / _OOD_SAMPLE_COUNT,
            top5_counts[name],
            top5_counts[name] / _OOD_SAMPLE_COUNT,
            rank,
        )
        for rank, name in enumerate(ranked_names, start=1)
    )

    family_names = tuple(dict.fromkeys(registry_by_name[name].family for name in names))
    family_rows = []
    for family_name in family_names:
        family_features = tuple(name for name in names if registry_by_name[name].family == family_name)
        family_total = sum(totals[name] for name in family_features)
        family_ratio = family_total / total
        family_rows.append(
            OODFamilySummaryRow(
                _ANALYSIS_SCOPE,
                0,
                component.component_fingerprint,
                family_name,
                family_features,
                registry_schema_version,
                registry_hash,
                family_total,
                family_ratio,
                _VOLATILITY_FAMILY_THRESHOLD,
                family_name == "volatility",
                family_name == "volatility"
                and _at_least(family_ratio, _VOLATILITY_FAMILY_THRESHOLD),
            )
        )
    frozen_families = tuple(family_rows)
    volatility = next((row for row in frozen_families if row.family_name == "volatility"), None)
    return ComponentZeroOODAnalysis(
        _ANALYSIS_SCOPE,
        0,
        component.component_fingerprint,
        _ASSIGNED_SAMPLE_COUNT,
        _OOD_SAMPLE_COUNT,
        registry_schema_version,
        registry_hash,
        feature_rows,
        frozen_families,
        ranked_names[:5],
        _at_least(feature_rows[0].contribution_ratio, _SINGLE_FEATURE_THRESHOLD),
        volatility is not None
        and _at_least(volatility.contribution_ratio, _VOLATILITY_FAMILY_THRESHOLD),
        any(_at_least(row.top1_ratio, _RECURRENT_FEATURE_THRESHOLD) for row in feature_rows),
    )


__all__ = [
    "ComponentZeroOODAnalysis",
    "OODFamilySummaryRow",
    "OODFeatureSummaryRow",
    "summarize_component_zero_ood",
]
