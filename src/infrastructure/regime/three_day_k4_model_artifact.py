"""Frozen, fail-closed artifact for the fold-local three-day K4 research model."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Mapping

import numpy as np

from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.model import ClusterAssignment, RegimeModelConfig, component_fingerprint
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
    ThreeDayChartFeatureVector,
)
from src.domain.regime.three_day_daily_profile import (
    PROFILE_ID,
    ThreeDayDailyResearchProfile,
)
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
    iter_archive_requests,
)


THREE_DAY_K4_MODEL_ARTIFACT_VERSION = "three-day-k4-model-v1"
THREE_DAY_FEATURE_REGISTRY_VERSION = "three-day-chart-feature-registry-v1"
THREE_DAY_FEATURE_HISTORY_CONTRACT_VERSION = "three-day-feature-history-v1"
THREE_DAY_FEATURE_EXTRACTOR_VERSION = "three-day-chart-feature-extractor-v1"
MISSING_VALUE_POLICY = "reject_nonfinite_no_imputation"
FAMILY_CAP_POLICY = "maximum_five_and_no_more_than_half"
ASSIGNMENT_CONFIDENCE_POLICY = "gmm_top_two_posterior_v1"
_HEX24 = re.compile(r"[0-9a-f]{24}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_REGISTRY_NAMES = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
_TOP_FIELDS = frozenset(
    {
        "artifact_version", "profile_id", "profile_version", "profile", "feature_registry_version",
        "feature_history_contract_version", "feature_extractor_version",
        "feature_schema_version", "feature_registry", "symbol", "timeframe",
        "training_start_at", "training_end_at", "first_usable_anchor_at",
        "last_usable_anchor_at", "usable_anchor_count", "retained_feature_names",
        "family_cap_policy", "missing_value_policy", "lower_bounds", "upper_bounds",
        "medians", "scales", "model_type", "covariance_type", "cluster_count",
        "random_seed", "regularization", "converged", "iterations", "lower_bound",
        "weights", "means", "covariances", "component_fingerprints",
        "numeric_index_to_fingerprint", "canonical_fingerprint_order",
        "assignment_confidence_policy", "source_provenance", "source_combined_hash",
        "feature_history_hash", "fit_input_vector_hash", "code_provenance_hash",
        "model_gates", "artifact_hash",
    }
)


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _parse_time(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{name.replace('_', ' ')} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{name.replace('_', ' ')} must be canonical UTC") from exc
    if _time(parsed) != value:
        raise ValueError(f"{name.replace('_', ' ')} must be canonical UTC")
    return parsed


def _registry_payload() -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "family": spec.family,
            "aggregation_minutes": spec.aggregation_minutes,
            "lookback_minutes": spec.lookback_minutes,
            "formula": spec.formula,
            "null_policy": spec.null_policy,
            "clipping_policy": spec.clipping_policy,
            "scale_invariant": spec.scale_invariant,
        }
        for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1
    ]


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _original_space_fingerprints(fit: ClusterDiagnosticFit) -> tuple[str, ...]:
    return tuple(
        component_fingerprint(
            model_type="gmm",
            feature_schema_version=fit.schema_version,
            feature_names=fit.feature_names,
            mean=tuple(
                mean[index] * fit.scales[index] + fit.medians[index]
                for index in range(len(fit.feature_names))
            ),
            covariance=tuple(
                covariance[index] * fit.scales[index] ** 2
                for index in range(len(fit.feature_names))
            ),
            weight=fit.weights[component],
        )
        for component, (mean, covariance) in enumerate(zip(fit.means, fit.covariances))
    )


def _standardized_fingerprints(
    *, schema_version: str, feature_names: tuple[str, ...], means: tuple[tuple[float, ...], ...],
    covariances: tuple[tuple[float, ...], ...], weights: tuple[float, ...],
) -> tuple[str, ...]:
    return tuple(
        component_fingerprint(
            model_type="gmm", feature_schema_version=schema_version,
            feature_names=feature_names, mean=mean, covariance=covariances[index],
            weight=weights[index],
        )
        for index, mean in enumerate(means)
    )


def validate_three_day_k4_source_provenance(
    provenance: tuple[Mapping[str, object], ...] | list[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    profile = ThreeDayDailyResearchProfile()
    start = profile.fold.cluster_fit.start_at - timedelta(days=3)
    end = profile.fold.cluster_fit.end_at
    requests = tuple(iter_archive_requests("klines", "BTCUSDT", start, end, now=end + timedelta(days=32)))
    rows = tuple(provenance)
    if len(rows) != len(requests):
        raise ValueError("source provenance must match the exact ordered archive request count")
    expected_fields = {
        "period", "url", "member_identity", "bytes", "sha256", "expected_sha256",
        "checksum_verified", "source", "symbol", "timeframe", "granularity",
        "requested_start_at", "requested_end_at",
    }
    expected_start = _time(start)
    expected_end = _time(end)
    identities: set[tuple[str, str]] = set()
    copied = []
    for row, request in zip(rows, requests):
        if not isinstance(row, Mapping) or set(row) != expected_fields:
            raise ValueError("source provenance fields are incompatible")
        expected_member = request.filename.removesuffix(".zip") + ".csv"
        expected_identity = (request.period, request.url)
        if expected_identity in identities:
            raise ValueError("source provenance archive identity is duplicated")
        identities.add(expected_identity)
        if (
            row["period"] != request.period or row["url"] != request.url
            or row["member_identity"] != expected_member
            or row["granularity"] != request.granularity
            or row["source"] != "klines" or row["symbol"] != "BTCUSDT"
            or row["timeframe"] != "1m"
            or row["requested_start_at"] != expected_start
            or row["requested_end_at"] != expected_end
        ):
            raise ValueError("source provenance order, coverage, or archive identity is incompatible")
        if not isinstance(row["bytes"], int) or isinstance(row["bytes"], bool) or row["bytes"] <= 0:
            raise ValueError("source provenance bytes are invalid")
        if row["checksum_verified"] is not True:
            raise ValueError("source provenance checksum was not verified")
        for name in ("sha256", "expected_sha256"):
            value = row[name]
            if not isinstance(value, str) or not _HEX64.fullmatch(value):
                raise ValueError(f"source provenance {name} is invalid")
        if row["sha256"] != row["expected_sha256"]:
            raise ValueError("source provenance content and expected checksums differ")
        copied.append(MappingProxyType(dict(row)))
    return tuple(copied)


@dataclass(frozen=True)
class ThreeDayK4ModelArtifact:
    fit: ClusterDiagnosticFit
    training_start_at: datetime
    training_end_at: datetime
    first_usable_anchor_at: datetime
    last_usable_anchor_at: datetime
    usable_anchor_count: int
    source_provenance: tuple[Mapping[str, object], ...]
    feature_history_hash: str
    fit_input_vector_hash: str
    code_provenance_hash: str
    model_gates: Mapping[str, object]
    artifact_version: str = THREE_DAY_K4_MODEL_ARTIFACT_VERSION
    profile_id: str = PROFILE_ID
    profile_version: str = PROFILE_ID
    feature_registry_version: str = THREE_DAY_FEATURE_REGISTRY_VERSION
    feature_history_contract_version: str = THREE_DAY_FEATURE_HISTORY_CONTRACT_VERSION
    feature_extractor_version: str = THREE_DAY_FEATURE_EXTRACTOR_VERSION
    timeframe: str = "1d"
    missing_value_policy: str = MISSING_VALUE_POLICY
    family_cap_policy: str = FAMILY_CAP_POLICY
    assignment_confidence_policy: str = ASSIGNMENT_CONFIDENCE_POLICY
    artifact_hash: str = field(init=False)

    def __post_init__(self) -> None:
        profile = ThreeDayDailyResearchProfile()
        if self.artifact_version != THREE_DAY_K4_MODEL_ARTIFACT_VERSION:
            raise ValueError("unsupported artifact version")
        if self.profile_id != PROFILE_ID or self.profile_version != PROFILE_ID:
            raise ValueError("profile id is incompatible")
        if self.feature_registry_version != THREE_DAY_FEATURE_REGISTRY_VERSION:
            raise ValueError("feature registry version is incompatible")
        if (
            self.feature_history_contract_version != THREE_DAY_FEATURE_HISTORY_CONTRACT_VERSION
            or self.feature_extractor_version != THREE_DAY_FEATURE_EXTRACTOR_VERSION
        ):
            raise ValueError("feature history contract or extractor version is incompatible")
        if self.timeframe != "1d" or self.missing_value_policy != MISSING_VALUE_POLICY:
            raise ValueError("timeframe or missing value policy is incompatible")
        if self.family_cap_policy != FAMILY_CAP_POLICY or self.assignment_confidence_policy != ASSIGNMENT_CONFIDENCE_POLICY:
            raise ValueError("family cap or assignment confidence policy is incompatible")
        if not isinstance(self.fit, ClusterDiagnosticFit):
            raise ValueError("fit must be a ClusterDiagnosticFit")
        config = self.fit.config
        if (
            self.fit.schema_version != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
            or config != RegimeModelConfig("gmm", 4, profile.random_seed, "diag", profile.regularization)
        ):
            raise ValueError("model or feature schema is incompatible")
        if self.fit.symbol != "BTCUSDT":
            raise ValueError("symbol is incompatible")
        positions = tuple(_REGISTRY_NAMES.index(name) for name in self.fit.feature_names if name in _REGISTRY_NAMES)
        if len(positions) != len(self.fit.feature_names) or positions != tuple(sorted(positions)):
            raise ValueError("retained feature names are incompatible with registry order")
        families = {spec.name: spec.family for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
        counts = Counter(families[name] for name in self.fit.feature_names)
        if any(count > 5 or count > len(self.fit.feature_names) / 2 for count in counts.values()):
            raise ValueError("retained feature family cap is violated")
        if any(not _HEX24.fullmatch(value) for value in self.fit.fingerprints):
            raise ValueError("component fingerprints must be lowercase 24-hex")
        expected_interval = profile.fold.cluster_fit
        if self.training_start_at != expected_interval.start_at or self.training_end_at != expected_interval.end_at:
            raise ValueError("training interval is incompatible")
        for value, name in (
            (self.first_usable_anchor_at, "first usable anchor"),
            (self.last_usable_anchor_at, "last usable anchor"),
        ):
            if value.tzinfo is not timezone.utc or value.time() != datetime.min.time():
                raise ValueError(f"{name} must be canonical midnight UTC")
        if (
            self.first_usable_anchor_at != self.training_start_at
            or self.last_usable_anchor_at != self.training_end_at - timedelta(days=1)
            or self.usable_anchor_count != (self.training_end_at - self.training_start_at).days
        ):
            raise ValueError("usable anchor coverage is incompatible with Cluster Fit")
        provenance = validate_three_day_k4_source_provenance(self.source_provenance)
        for value, name in (
            (self.feature_history_hash, "feature history hash"),
            (self.fit_input_vector_hash, "fit input vector hash"),
            (self.code_provenance_hash, "code provenance hash"),
        ):
            if not isinstance(value, str) or not _HEX64.fullmatch(value):
                raise ValueError(f"{name} is invalid")
        if self.feature_history_hash != self.fit_input_vector_hash:
            raise ValueError("feature history and fit input vector hashes must match exact Cluster Fit inputs")
        gates = MappingProxyType(dict(self.model_gates))
        required_gates = {
            "convergence_required", "converged", "iterations", "lower_bound",
            "finite_scaler_required", "finite_scaler", "finite_model_parameters_required",
            "finite_model_parameters", "positive_weights_required", "minimum_weight",
            "weight_sum_expected", "weight_sum_tolerance", "weight_sum",
            "covariance_floor_threshold", "minimum_covariance",
            "component_count_expected", "component_count",
            "all_components_represented_required", "all_components_represented",
            "all_chronological_blocks_represented_required", "all_chronological_blocks_represented",
            "minimum_adjusted_rand_index", "minimum_adjusted_rand_index_threshold",
            "minimum_normalized_mutual_information", "minimum_normalized_mutual_information_threshold",
            "maximum_matched_centroid_distance", "maximum_matched_centroid_distance_threshold",
            "maximum_prevalence_drift", "maximum_prevalence_drift_threshold",
            "gmm_probability_threshold", "gmm_margin_threshold", "distance_threshold_policy",
            "minimum_observed_dominant_probability", "minimum_observed_probability_margin",
            "distance_threshold", "distance_result",
            "low_confidence_rate", "maximum_low_confidence_rate_threshold", "nondegenerate_confidence",
            "feature_registry_version_expected", "feature_registry_exact",
            "feature_family_cap_maximum_count", "feature_family_cap_maximum_share",
            "feature_family_observed_maximum_count", "feature_family_observed_maximum_share",
            "feature_family_cap_passed", "passed",
        }
        if set(gates) != required_gates:
            raise ValueError("stability gate fields are incompatible")
        required_true = (
            "convergence_required", "converged", "finite_scaler_required", "finite_scaler",
            "finite_model_parameters_required", "finite_model_parameters", "positive_weights_required",
            "all_components_represented_required", "all_components_represented",
            "all_chronological_blocks_represented_required", "all_chronological_blocks_represented",
            "nondegenerate_confidence", "feature_registry_exact", "feature_family_cap_passed", "passed",
        )
        if any(gates[name] is not True for name in required_true):
            raise ValueError("model stability gates did not pass")
        nonnumeric = set(required_true) | {
            "distance_threshold_policy", "distance_threshold", "distance_result",
            "feature_registry_version_expected",
        }
        numeric = tuple(gates[name] for name in required_gates - nonnumeric)
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in numeric):
            raise ValueError("stability gate numeric results must be finite")
        if not isinstance(gates["iterations"], int) or gates["iterations"] <= 0:
            raise ValueError("stability gate iterations must be positive")
        expected_thresholds = {
            "minimum_adjusted_rand_index_threshold": 0.8,
            "minimum_normalized_mutual_information_threshold": 0.8,
            "maximum_matched_centroid_distance_threshold": 0.5,
            "maximum_prevalence_drift_threshold": 0.2,
            "maximum_low_confidence_rate_threshold": 0.25,
            "weight_sum_expected": 1.0,
            "weight_sum_tolerance": 1e-8,
            "covariance_floor_threshold": 1e-6,
            "component_count_expected": 4,
            "gmm_probability_threshold": 0.65,
            "gmm_margin_threshold": 0.10,
            "feature_family_cap_maximum_count": 5,
            "feature_family_cap_maximum_share": 0.5,
        }
        if any(gates[name] != value for name, value in expected_thresholds.items()):
            raise ValueError("model stability gate thresholds are incompatible")
        if not -1 <= gates["minimum_adjusted_rand_index"] <= 1:
            raise ValueError("adjusted rand gate result is outside its valid range")
        if not 0 <= gates["minimum_normalized_mutual_information"] <= 1:
            raise ValueError("normalized mutual information gate result is outside its valid range")
        if gates["maximum_matched_centroid_distance"] < 0:
            raise ValueError("centroid distance gate result cannot be negative")
        if not 0 <= gates["maximum_prevalence_drift"] <= 1 or not 0 <= gates["low_confidence_rate"] <= 1:
            raise ValueError("prevalence and confidence gate results must be shares")
        if (
            gates["minimum_adjusted_rand_index"] < 0.8
            or gates["minimum_normalized_mutual_information"] < 0.8
            or gates["maximum_matched_centroid_distance"] > 0.5
            or gates["maximum_prevalence_drift"] > 0.2
            or gates["low_confidence_rate"] > 0.25
        ):
            raise ValueError("serialized model gate results do not pass frozen thresholds")
        finite_scaler = all(math.isfinite(value) for values in (self.fit.lower_bounds, self.fit.upper_bounds, self.fit.medians, self.fit.scales) for value in values)
        finite_model = all(math.isfinite(value) for values in (*self.fit.means, self.fit.weights, *self.fit.covariances) for value in values)
        if (
            gates["distance_threshold_policy"] != "not_applicable_for_gmm"
            or gates["distance_threshold"] != "not_applicable_for_gmm"
            or gates["distance_result"] != "not_applicable_for_gmm"
            or gates["feature_registry_version_expected"] != THREE_DAY_FEATURE_REGISTRY_VERSION
            or gates["finite_scaler"] != finite_scaler
            or gates["finite_model_parameters"] != finite_model
            or gates["minimum_weight"] != min(self.fit.weights)
            or gates["weight_sum"] != math.fsum(self.fit.weights)
            or not math.isclose(gates["weight_sum"], 1.0, rel_tol=1e-8, abs_tol=1e-8)
            or gates["minimum_covariance"] != min(value for row in self.fit.covariances for value in row)
            or gates["minimum_covariance"] < 1e-6
            or gates["component_count"] != 4
            or gates["feature_family_observed_maximum_count"] != max(counts.values())
            or gates["feature_family_observed_maximum_share"] != max(counts.values()) / len(self.fit.feature_names)
        ):
            raise ValueError("serialized fixed model gate results do not match fitted parameters")
        if (
            not 0 <= gates["minimum_observed_dominant_probability"] <= 1
            or not 0 <= gates["minimum_observed_probability_margin"] <= 1
        ):
            raise ValueError("assignment confidence gate results must be probabilities")
        if (
            gates["converged"] != self.fit.converged
            or gates["iterations"] != self.fit.iterations
            or gates["lower_bound"] != self.fit.lower_bound
        ):
            raise ValueError("fit convergence metadata does not match stability gates")
        object.__setattr__(self, "source_provenance", provenance)
        object.__setattr__(self, "model_gates", gates)
        object.__setattr__(self, "artifact_hash", _hash(self._payload(include_hash=False)))

    @classmethod
    def from_fit(cls, fit: ClusterDiagnosticFit, **kwargs: object) -> "ThreeDayK4ModelArtifact":
        return cls(fit=fit, **kwargs)

    @property
    def component_fingerprints(self) -> tuple[str, ...]:
        return self.canonical_fingerprint_order

    @property
    def symbol(self) -> str:
        return self.fit.symbol

    @property
    def feature_schema_version(self) -> str:
        return self.fit.schema_version

    @property
    def retained_feature_names(self) -> tuple[str, ...]:
        return self.fit.feature_names

    feature_names = retained_feature_names

    @property
    def config(self) -> RegimeModelConfig:
        return self.fit.config

    @property
    def lower_bounds(self) -> tuple[float, ...]:
        return self.fit.lower_bounds

    @property
    def upper_bounds(self) -> tuple[float, ...]:
        return self.fit.upper_bounds

    @property
    def medians(self) -> tuple[float, ...]:
        return self.fit.medians

    @property
    def scales(self) -> tuple[float, ...]:
        return self.fit.scales

    @property
    def weights(self) -> tuple[float, ...]:
        return self.fit.weights

    @property
    def means(self) -> tuple[tuple[float, ...], ...]:
        return self.fit.means

    @property
    def covariances(self) -> tuple[tuple[float, ...], ...]:
        return self.fit.covariances

    @property
    def numeric_index_to_fingerprint(self) -> Mapping[int, str]:
        return MappingProxyType(dict(enumerate(_original_space_fingerprints(self.fit))))

    @property
    def canonical_fingerprint_order(self) -> tuple[str, ...]:
        return tuple(sorted(_original_space_fingerprints(self.fit)))

    @property
    def source_combined_hash(self) -> str:
        return _hash({"archives": [dict(row) for row in self.source_provenance]})

    def assign(self, vector: ThreeDayChartFeatureVector) -> ClusterAssignment:
        if not isinstance(vector, ThreeDayChartFeatureVector):
            raise ValueError("assignment requires a three-day chart feature vector")
        if vector.symbol != self.fit.symbol:
            raise ValueError("assignment vector symbol does not match artifact")
        if tuple(vector.values) != _REGISTRY_NAMES or vector.schema_version != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION:
            raise ValueError("assignment vector registry is incompatible")
        selected = np.asarray([float(vector.values[name]) for name in self.fit.feature_names])
        clipped = np.clip(selected, self.fit.lower_bounds, self.fit.upper_bounds)
        scaled = (clipped - np.asarray(self.fit.medians)) / np.asarray(self.fit.scales)
        means = np.asarray(self.fit.means)
        covariances = np.asarray(self.fit.covariances)
        delta = scaled[None, :] - means
        log_probabilities = (
            np.log(np.asarray(self.fit.weights))
            - 0.5
            * (
                len(self.fit.feature_names) * math.log(2 * math.pi)
                + np.log(covariances).sum(axis=1)
                + np.sum(delta * delta / covariances, axis=1)
            )
        )
        probabilities = np.exp(log_probabilities - np.max(log_probabilities))
        probabilities /= probabilities.sum()
        order = np.argsort(-probabilities, kind="stable")
        winner, runner_up = int(order[0]), int(order[1])
        return ClusterAssignment(
            fingerprint=self.numeric_index_to_fingerprint[winner],
            dominant_probability=float(probabilities[winner]),
            second_probability=float(probabilities[runner_up]),
            distance=None,
        )

    def _payload(self, *, include_hash: bool) -> dict[str, object]:
        profile = ThreeDayDailyResearchProfile()
        gates = dict(self.model_gates)
        payload: dict[str, object] = {
            "artifact_version": self.artifact_version,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile": profile.canonical_payload(),
            "feature_registry_version": self.feature_registry_version,
            "feature_history_contract_version": self.feature_history_contract_version,
            "feature_extractor_version": self.feature_extractor_version,
            "feature_schema_version": self.fit.schema_version,
            "feature_registry": _registry_payload(),
            "symbol": self.fit.symbol,
            "timeframe": self.timeframe,
            "training_start_at": _time(self.training_start_at),
            "training_end_at": _time(self.training_end_at),
            "first_usable_anchor_at": _time(self.first_usable_anchor_at),
            "last_usable_anchor_at": _time(self.last_usable_anchor_at),
            "usable_anchor_count": self.usable_anchor_count,
            "retained_feature_names": list(self.fit.feature_names),
            "family_cap_policy": self.family_cap_policy,
            "missing_value_policy": self.missing_value_policy,
            "lower_bounds": list(self.fit.lower_bounds), "upper_bounds": list(self.fit.upper_bounds),
            "medians": list(self.fit.medians), "scales": list(self.fit.scales),
            "model_type": self.fit.config.model_type, "covariance_type": self.fit.config.covariance_type,
            "cluster_count": self.fit.config.cluster_count, "random_seed": self.fit.config.random_seed,
            "regularization": self.fit.config.regularization,
            "converged": gates["converged"], "iterations": gates["iterations"], "lower_bound": gates["lower_bound"],
            "weights": list(self.fit.weights), "means": [list(row) for row in self.fit.means],
            "covariances": [list(row) for row in self.fit.covariances],
            "component_fingerprints": list(self.canonical_fingerprint_order),
            "numeric_index_to_fingerprint": {str(i): value for i, value in self.numeric_index_to_fingerprint.items()},
            "canonical_fingerprint_order": list(self.canonical_fingerprint_order),
            "assignment_confidence_policy": self.assignment_confidence_policy,
            "source_provenance": [dict(row) for row in self.source_provenance],
            "source_combined_hash": self.source_combined_hash,
            "feature_history_hash": self.feature_history_hash,
            "fit_input_vector_hash": self.fit_input_vector_hash,
            "code_provenance_hash": self.code_provenance_hash,
            "model_gates": gates,
        }
        if include_hash:
            payload["artifact_hash"] = self.artifact_hash
        return payload

    def canonical_payload(self) -> Mapping[str, object]:
        return MappingProxyType(self._payload(include_hash=True))

    def to_json(self) -> str:
        return _canonical_json(self._payload(include_hash=True))

    serialize = to_json

    @classmethod
    def from_json(cls, encoded: str | bytes) -> "ThreeDayK4ModelArtifact":
        try:
            payload = json.loads(encoded, object_pairs_hook=_pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"nonfinite JSON number: {value}")))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("artifact JSON is invalid") from exc
        if not isinstance(payload, dict) or set(payload) != _TOP_FIELDS:
            raise ValueError("artifact fields are missing or unknown")
        supplied_hash = payload.pop("artifact_hash")
        if not isinstance(supplied_hash, str) or not _HEX64.fullmatch(supplied_hash) or _hash(payload) != supplied_hash:
            raise ValueError("artifact hash mismatch")
        profile = ThreeDayDailyResearchProfile()
        fixed = {
            "artifact_version": THREE_DAY_K4_MODEL_ARTIFACT_VERSION,
            "profile_id": PROFILE_ID,
            "profile_version": PROFILE_ID,
            "profile": profile.canonical_payload(),
            "feature_registry_version": THREE_DAY_FEATURE_REGISTRY_VERSION,
            "feature_history_contract_version": THREE_DAY_FEATURE_HISTORY_CONTRACT_VERSION,
            "feature_extractor_version": THREE_DAY_FEATURE_EXTRACTOR_VERSION,
            "feature_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
            "feature_registry": _registry_payload(),
            "timeframe": "1d", "missing_value_policy": MISSING_VALUE_POLICY,
            "family_cap_policy": FAMILY_CAP_POLICY,
            "assignment_confidence_policy": ASSIGNMENT_CONFIDENCE_POLICY,
            "model_type": "gmm", "covariance_type": "diag", "cluster_count": 4,
            "random_seed": 20260714, "regularization": 1e-6,
        }
        for name, expected in fixed.items():
            if payload[name] != expected:
                raise ValueError(f"{name.replace('_', ' ')} is incompatible")
        artifact_fingerprints = tuple(payload["component_fingerprints"])
        if payload["canonical_fingerprint_order"] != list(artifact_fingerprints) or artifact_fingerprints != tuple(sorted(artifact_fingerprints)):
            raise ValueError("canonical component fingerprint order is incompatible")
        if payload["source_combined_hash"] != _hash({"archives": payload["source_provenance"]}):
            raise ValueError("source provenance combined hash mismatch")
        gates = dict(payload["model_gates"])
        for key in ("converged", "iterations", "lower_bound"):
            if payload[key] != gates[key]:
                raise ValueError(f"{key.replace('_', ' ')} gate mismatch")
        config = RegimeModelConfig("gmm", 4, 20260714, "diag", 1e-6)
        feature_names = tuple(payload["retained_feature_names"])
        means = tuple(tuple(row) for row in payload["means"])
        covariances = tuple(tuple(row) for row in payload["covariances"])
        weights = tuple(payload["weights"])
        fit = ClusterDiagnosticFit(
            schema_version=payload["feature_schema_version"], symbol=payload["symbol"], config=config,
            feature_names=feature_names,
            lower_bounds=tuple(payload["lower_bounds"]), upper_bounds=tuple(payload["upper_bounds"]),
            medians=tuple(payload["medians"]), scales=tuple(payload["scales"]),
            fingerprints=_standardized_fingerprints(
                schema_version=payload["feature_schema_version"], feature_names=feature_names,
                means=means, covariances=covariances, weights=weights,
            ),
            means=means, weights=weights, covariances=covariances,
            distance_thresholds=(),
            converged=payload["converged"], iterations=payload["iterations"],
            lower_bound=payload["lower_bound"],
        )
        artifact = cls(
            fit=fit,
            training_start_at=_parse_time(payload["training_start_at"], "training_start_at"),
            training_end_at=_parse_time(payload["training_end_at"], "training_end_at"),
            first_usable_anchor_at=_parse_time(payload["first_usable_anchor_at"], "first_usable_anchor_at"),
            last_usable_anchor_at=_parse_time(payload["last_usable_anchor_at"], "last_usable_anchor_at"),
            usable_anchor_count=payload["usable_anchor_count"], source_provenance=tuple(payload["source_provenance"]),
            feature_history_hash=payload["feature_history_hash"], fit_input_vector_hash=payload["fit_input_vector_hash"],
            code_provenance_hash=payload["code_provenance_hash"], model_gates=gates,
        )
        if artifact.artifact_hash != supplied_hash:
            raise ValueError("artifact hash mismatch after reconstruction")
        if payload["numeric_index_to_fingerprint"] != {
            str(index): value for index, value in artifact.numeric_index_to_fingerprint.items()
        } or artifact_fingerprints != artifact.canonical_fingerprint_order:
            raise ValueError("component index mapping is incompatible")
        canonical_input = encoded.decode("utf-8") if isinstance(encoded, bytes) else encoded
        if canonical_input != artifact.to_json():
            raise ValueError("artifact JSON must use exact canonical encoding")
        return artifact

    deserialize = from_json


__all__ = [
    "THREE_DAY_K4_MODEL_ARTIFACT_VERSION", "ThreeDayK4ModelArtifact",
    "validate_three_day_k4_source_provenance",
]
