"""Provenance-bound, local-only inputs for the frozen K4 failure diagnostic."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from urllib.parse import urlsplit

from scipy.stats import chi2

from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.frozen_k4_failure_diagnostics import FrozenK4InputIdentity
from src.domain.regime.model import RegimeModelConfig
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
    ThreeDayChartFeatureVector,
)
from src.domain.regime.three_day_daily_profile import PROFILE_ID
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
    DownloadResult,
    archive_url,
    iter_archive_requests,
    validate_archive_member_directory,
)
from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
    load_three_day_feature_history,
)
_ATTEMPT_FIELDS = frozenset(
    {
        "attempt_hash", "code_provenance_hash", "failed_gate_names", "feature_names",
        "first_usable_anchor_at", "fit_input_anchor_count", "fit_input_vector_hash",
        "fit_interval", "last_usable_anchor_at", "model_config", "model_gates",
        "model_parameters", "profile_id", "schema_version", "source_provenance",
        "source_provenance_hash", "status",
    }
)
_FORBIDDEN_SECTIONS = frozenset(
    {"Mapping", "Strategy Mapping", "Validation", "Evidence", "candidate", "Test"}
)
_CUTOFF = datetime(2025, 6, 30, tzinfo=timezone.utc)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_PROVENANCE_FIELDS = frozenset({
    "period", "url", "member_identity", "bytes", "sha256", "expected_sha256",
    "checksum_verified", "source", "symbol", "timeframe", "granularity",
    "requested_start_at", "requested_end_at",
})
_FROZEN_FEATURE_NAMES = (
    "return_4h", "return_12h", "return_1d", "return_2d", "return_3d",
    "rv_4h", "rv_1d", "rv_3d", "rv_ratio_1d_3d", "range_ratio_3d",
    "close_location_3d", "directional_efficiency_1d", "directional_efficiency_3d",
    "sign_change_rate_1d", "sign_change_rate_3d", "return_autocorr_1d",
    "return_autocorr_3d", "max_drawdown_3d", "max_runup_3d",
    "breakout_rate_3d", "mean_body_ratio_3d", "mean_upper_wick_ratio_3d",
    "mean_lower_wick_ratio_3d", "volume_cv_3d", "volume_ratio_1d_3d",
)
_MODEL_PARAMETER_FIELDS = frozenset({
    "component_fingerprints", "converged", "covariances", "iterations", "lower_bound",
    "lower_bounds", "means", "medians", "scales", "upper_bounds", "weights",
})
_GATE_BOOL_FIELDS = frozenset({
    "all_chronological_blocks_represented", "all_chronological_blocks_represented_passed",
    "all_chronological_blocks_represented_required", "all_chronological_blocks_represented_threshold",
    "all_components_represented", "all_components_represented_passed",
    "all_components_represented_required", "all_components_represented_threshold",
    "converged", "convergence_required", "distance_result", "feature_family_cap_passed",
    "feature_registry_exact", "finite_model_parameters", "finite_model_parameters_required",
    "finite_scaler", "finite_scaler_required", "maximum_distance_exceedance_rate_passed",
    "maximum_low_confidence_rate_passed", "maximum_matched_centroid_distance_passed",
    "maximum_prevalence_drift_passed", "minimum_adjusted_rand_index_passed",
    "minimum_normalized_mutual_information_passed", "nondegenerate_confidence", "passed",
    "positive_weights_required",
})
_GATE_INT_FIELDS = frozenset({
    "component_count", "component_count_expected", "feature_family_cap_maximum_count",
    "feature_family_observed_maximum_count", "iterations",
})
_GATE_FLOAT_FIELDS = frozenset({
    "covariance_floor_threshold", "distance_exceedance_rate", "distance_threshold",
    "feature_family_cap_maximum_share", "feature_family_observed_maximum_share",
    "gmm_margin_threshold", "gmm_probability_threshold", "low_confidence_rate", "lower_bound",
    "maximum_distance_exceedance_rate", "maximum_distance_exceedance_rate_threshold",
    "maximum_low_confidence_rate", "maximum_low_confidence_rate_threshold",
    "maximum_matched_centroid_distance", "maximum_matched_centroid_distance_threshold",
    "maximum_prevalence_drift", "maximum_prevalence_drift_threshold",
    "minimum_adjusted_rand_index", "minimum_adjusted_rand_index_threshold", "minimum_covariance",
    "minimum_normalized_mutual_information", "minimum_normalized_mutual_information_threshold",
    "minimum_observed_dominant_probability", "minimum_observed_probability_margin",
    "minimum_weight", "weight_sum", "weight_sum_expected", "weight_sum_tolerance",
})
_GATE_STR_FIELDS = frozenset({"distance_threshold_policy", "feature_registry_version_expected"})
_GATE_FIELDS = _GATE_BOOL_FIELDS | _GATE_INT_FIELDS | _GATE_FLOAT_FIELDS | _GATE_STR_FIELDS


@dataclass(frozen=True)
class _FrozenK4SourceProfile:
    raw_start_at: datetime
    fit_start_at: datetime
    fit_end_at: datetime
    expected_anchor_count: int
    production: bool
    symbol: str = "BTCUSDT"

    def __post_init__(self) -> None:
        for value in (self.raw_start_at, self.fit_start_at, self.fit_end_at):
            if (
                value.tzinfo != timezone.utc or value.hour or value.minute
                or value.second or value.microsecond
            ):
                raise ValueError("source profile timestamps must be canonical UTC midnights")
        if self.symbol != "BTCUSDT" or self.raw_start_at != self.fit_start_at - timedelta(days=3):
            raise ValueError("source profile must preserve the frozen symbol and 4320-minute lookback")
        expected = (self.fit_end_at - self.fit_start_at).days
        if self.fit_end_at <= self.fit_start_at or self.expected_anchor_count != expected:
            raise ValueError("source profile anchor count must match its half-open daily interval")
        if self.fit_end_at > _CUTOFF:
            raise ValueError("source profile cannot cross the frozen cutoff")
        if self.production and (
            self.raw_start_at != datetime(2020, 12, 29, tzinfo=timezone.utc)
            or self.fit_start_at != datetime(2021, 1, 1, tzinfo=timezone.utc)
            or self.fit_end_at != _CUTOFF or self.expected_anchor_count != 1_641
        ):
            raise ValueError("production source profile is immutable")

    @classmethod
    def testing(
        cls, *, raw_start_at: datetime, fit_start_at: datetime,
        fit_end_at: datetime, expected_anchor_count: int,
    ) -> "_FrozenK4SourceProfile":
        return cls(raw_start_at, fit_start_at, fit_end_at, expected_anchor_count, False)


_PRODUCTION_PROFILE = _FrozenK4SourceProfile(
    datetime(2020, 12, 29, tzinfo=timezone.utc),
    datetime(2021, 1, 1, tzinfo=timezone.utc),
    _CUTOFF,
    1_641,
    True,
)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _three_day_vector_hash(vectors: tuple[ThreeDayChartFeatureVector, ...]) -> str:
    """Reproduce the publisher's exact canonical fit-vector identity."""
    return _hash({
        "schema_version": vectors[0].schema_version if vectors else None,
        "registry_names": [spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1],
        "vectors": [
            {
                "symbol": vector.symbol,
                "anchor_at": vector.anchor_at.isoformat(),
                "window_start_at": vector.window_start_at.isoformat(),
                "values": list(vector.values.items()),
            }
            for vector in vectors
        ],
    })


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a canonical UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc or parsed.microsecond:
        raise ValueError(f"{field} must be a canonical UTC timestamp")
    return parsed


class _LocalProvenanceDownloader:
    def __init__(self, rows: tuple[Mapping[str, object], ...], raw_root: Path) -> None:
        self._rows = {str(row["url"]): row for row in rows}
        self._raw_root = Path(raw_root).resolve()

    def download(
        self, url: str, destination: Path, *, source: str | None = None,
        max_bytes: int | None = None,
    ) -> DownloadResult:
        del max_bytes
        row = self._rows.get(url)
        if row is None:
            raise ValueError("archive URL is not present in frozen source provenance")
        destination = Path(destination)
        resolved_destination = destination.resolve()
        try:
            resolved_destination.relative_to(self._raw_root)
        except ValueError as exc:
            raise ValueError("local archive destination escapes the resolved raw root") from exc
        if destination.is_symlink():
            raise ValueError("local archive symlink indirection is forbidden")
        destination = resolved_destination
        basename = Path(urlsplit(url).path).name
        if not basename or basename != destination.name:
            raise ValueError("archive URL basename does not match local archive destination")
        if source != "klines":
            raise ValueError("frozen diagnostic source permits only kline archives")
        if not destination.is_file():
            raise FileNotFoundError(f"required local archive is missing: {destination}")
        size = destination.stat().st_size
        if size != row["bytes"]:
            raise ValueError(f"archive bytes mismatch for {basename}")
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if digest != row["sha256"] or digest != row["expected_sha256"]:
            raise ValueError(f"archive sha256 mismatch for {basename}")
        member = validate_archive_member_directory(
            destination, expected_archive_filename=basename
        )
        if member != row["member_identity"]:
            raise ValueError(f"archive member identity mismatch for {basename}")
        return DownloadResult("cached", destination, digest, size, digest, member)


@dataclass(frozen=True)
class FrozenK4DiagnosticSource:
    attempt_payload: Mapping[str, object]
    primary_fit: ClusterDiagnosticFit
    vectors: tuple[ThreeDayChartFeatureVector, ...]
    identity: FrozenK4InputIdentity

    def __post_init__(self) -> None:
        if not isinstance(self.attempt_payload, MappingProxyType):
            object.__setattr__(self, "attempt_payload", _deep_freeze(self.attempt_payload))
        object.__setattr__(self, "vectors", tuple(self.vectors))


@dataclass(frozen=True)
class _LoadedK4DiagnosticInputs:
    attempt_payload: Mapping[str, object]
    primary_fit: ClusterDiagnosticFit
    vectors: tuple[ThreeDayChartFeatureVector, ...]
    identity_hashes: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_payload", _deep_freeze(self.attempt_payload))
        object.__setattr__(self, "vectors", tuple(self.vectors))
        object.__setattr__(self, "identity_hashes", MappingProxyType(dict(self.identity_hashes)))


def _is_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _require_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ValueError(f"{field} must be a canonical SHA-256")
    return value


def _validate_model_gates(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _GATE_FIELDS:
        raise ValueError("model gates fields are missing or unknown")
    if any(type(value[name]) is not bool for name in _GATE_BOOL_FIELDS):
        raise ValueError("model gates boolean types are incompatible")
    if any(type(value[name]) is not int for name in _GATE_INT_FIELDS):
        raise ValueError("model gates integer types are incompatible")
    if any(type(value[name]) is not float or not math.isfinite(value[name]) for name in _GATE_FLOAT_FIELDS):
        raise ValueError("model gates numeric types are incompatible")
    if any(not isinstance(value[name], str) or not value[name] for name in _GATE_STR_FIELDS):
        raise ValueError("model gates string types are incompatible")
    checks = {
        "all_components_represented": value["all_components_represented"],
        "all_chronological_blocks_represented": value["all_chronological_blocks_represented"],
        "minimum_adjusted_rand_index": value["minimum_adjusted_rand_index"] >= value["minimum_adjusted_rand_index_threshold"],
        "minimum_normalized_mutual_information": value["minimum_normalized_mutual_information"] >= value["minimum_normalized_mutual_information_threshold"],
        "maximum_matched_centroid_distance": value["maximum_matched_centroid_distance"] <= value["maximum_matched_centroid_distance_threshold"],
        "maximum_prevalence_drift": value["maximum_prevalence_drift"] <= value["maximum_prevalence_drift_threshold"],
        "maximum_low_confidence_rate": value["nondegenerate_confidence"],
        "maximum_distance_exceedance_rate": value["distance_result"],
    }
    if any(value[f"{name}_passed"] is not passed for name, passed in checks.items()):
        raise ValueError("model gates passed relationships are incompatible")
    if value["maximum_low_confidence_rate"] != value["low_confidence_rate"] or value["maximum_distance_exceedance_rate"] != value["distance_exceedance_rate"]:
        raise ValueError("model gates enriched value relationships are incompatible")
    if value["passed"] is not all(checks.values()):
        raise ValueError("model gates overall relationship is incompatible")
    return checks


def _validate_provenance(
    value: object, profile: _FrozenK4SourceProfile,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list):
        raise ValueError("source provenance must be an ordered list")
    requests = tuple(iter_archive_requests(
        "klines", profile.symbol, profile.raw_start_at, profile.fit_end_at,
        now=profile.fit_end_at + timedelta(days=32),
    ))
    if len(value) != len(requests):
        raise ValueError("source provenance must match the exact ordered archive request count")
    copied = []
    requested_start = profile.raw_start_at.isoformat().replace("+00:00", "Z")
    requested_end = profile.fit_end_at.isoformat().replace("+00:00", "Z")
    for row, request in zip(value, requests):
        if not isinstance(row, dict) or set(row) != _PROVENANCE_FIELDS:
            raise ValueError("source provenance fields are incompatible")
        expected_member = request.filename.removesuffix(".zip") + ".csv"
        if (
            row["period"] != request.period or row["url"] != request.url
            or Path(urlsplit(row["url"]).path).name != request.filename
            or row["member_identity"] != expected_member
            or row["source"] != "klines" or row["symbol"] != profile.symbol
            or row["timeframe"] != "1m" or row["granularity"] != request.granularity
            or row["requested_start_at"] != requested_start
            or row["requested_end_at"] != requested_end
        ):
            raise ValueError("source provenance URL basename, coverage, or identity is incompatible")
        if type(row["bytes"]) is not int or row["bytes"] <= 0 or row["checksum_verified"] is not True:
            raise ValueError("source provenance bytes or checksum receipt is incompatible")
        actual = _require_hash(row["sha256"], "source provenance sha256")
        expected = _require_hash(row["expected_sha256"], "source provenance expected sha256")
        if actual != expected:
            raise ValueError("source provenance checksums differ")
        copied.append(MappingProxyType(dict(row)))
    return tuple(copied)


def _validate_attempt(
    payload: object, profile: _FrozenK4SourceProfile,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("failed-model attempt must be a JSON object")
    forbidden = _FORBIDDEN_SECTIONS.intersection(payload)
    if forbidden:
        raise ValueError(f"forbidden diagnostic input section: {sorted(forbidden)[0]}")
    if set(payload) != _ATTEMPT_FIELDS:
        raise ValueError("failed-model attempt fields are missing or unknown")
    supplied_hash = payload.get("attempt_hash")
    without_hash = dict(payload)
    without_hash.pop("attempt_hash")
    if supplied_hash != _hash(without_hash):
        raise ValueError("failed-model attempt hash mismatch")
    _require_hash(payload["fit_input_vector_hash"], "fit input vector hash")
    _require_hash(payload["code_provenance_hash"], "code provenance hash")
    if (
        payload["schema_version"] != "three-day-k4-model-attempt-v1"
        or payload["profile_id"] != PROFILE_ID
        or payload["status"] != "failed-model-gates"
        or type(payload["fit_input_anchor_count"]) is not int
        or payload["fit_input_anchor_count"] != profile.expected_anchor_count
    ):
        raise ValueError("failed-model attempt profile is incompatible")
    first = _parse_time(payload["first_usable_anchor_at"], "first usable anchor")
    last = _parse_time(payload["last_usable_anchor_at"], "last usable anchor")
    if first != profile.fit_start_at or last != profile.fit_end_at - timedelta(days=1) or last >= _CUTOFF:
        raise ValueError("source anchors must remain before the frozen cutoff")
    interval = payload["fit_interval"]
    if not isinstance(interval, dict) or set(interval) != {"start_at", "end_at"}:
        raise ValueError("fit interval is incompatible")
    if _parse_time(interval["start_at"], "fit start") != profile.fit_start_at or _parse_time(interval["end_at"], "fit end") != profile.fit_end_at:
        raise ValueError("fit interval is incompatible")
    if payload["feature_names"] != list(_FROZEN_FEATURE_NAMES):
        raise ValueError("primary feature names must match the exact frozen registry order")
    checks = _validate_model_gates(payload["model_gates"])
    failed = payload["failed_gate_names"]
    expected_failed = sorted(name for name, passed in checks.items() if not passed)
    if not isinstance(failed, list) or any(not isinstance(name, str) for name in failed) or failed != expected_failed:
        raise ValueError("failed gate names do not match model gate relationships")
    provenance = _validate_provenance(payload["source_provenance"], profile)
    if payload["source_provenance_hash"] != _hash(list(map(dict, provenance))):
        raise ValueError("source provenance hash mismatch")
    payload["source_provenance"] = [dict(row) for row in provenance]
    return payload


def _numeric_tuple(value: object, field: str) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise ValueError(f"primary {field} is incompatible")
    if any(not _is_number(item) for item in value):
        raise ValueError(f"primary {field} numeric values are incompatible")
    return tuple(value)


def _restore_primary_fit(payload: Mapping[str, object]) -> ClusterDiagnosticFit:
    config_payload = payload["model_config"]
    parameters = payload["model_parameters"]
    if not isinstance(config_payload, dict) or set(config_payload) != {
        "cluster_count", "covariance_type", "model_type", "random_seed", "regularization"
    }:
        raise ValueError("primary model config is incompatible")
    if not isinstance(parameters, dict) or set(parameters) != _MODEL_PARAMETER_FIELDS:
        raise ValueError("primary model parameters are incompatible")
    names = payload["feature_names"]
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("primary feature schema is incompatible")
    if names != list(_FROZEN_FEATURE_NAMES):
        raise ValueError("primary feature names must match the exact frozen registry order")
    if (
        config_payload != {
            "model_type": "gmm", "cluster_count": 4, "covariance_type": "diag",
            "random_seed": 20260714, "regularization": 1e-6,
        }
        or type(parameters["converged"]) is not bool
        or parameters["converged"] is not True
        or type(parameters["iterations"]) is not int
        or parameters["iterations"] <= 0
        or not _is_number(parameters["lower_bound"])
        or not isinstance(parameters["component_fingerprints"], list)
        or len(parameters["component_fingerprints"]) != 4
        or any(not isinstance(item, str) or len(item) != 24 for item in parameters["component_fingerprints"])
    ):
        raise ValueError("primary model parameters types or K4 shape are incompatible")
    feature_count = len(names)
    for field in ("lower_bounds", "upper_bounds", "medians", "scales"):
        values = parameters[field]
        if not isinstance(values, list) or len(values) != feature_count:
            raise ValueError(f"primary {field.replace('_', ' ')} dimensions are incompatible")
    if not isinstance(parameters["weights"], list) or len(parameters["weights"]) != 4:
        raise ValueError("primary weights dimensions are incompatible")
    for field in ("means", "covariances"):
        matrix = parameters[field]
        if not isinstance(matrix, list) or len(matrix) != 4 or any(
            not isinstance(row, list) or len(row) != feature_count for row in matrix
        ):
            raise ValueError(f"primary {field} GMM K4 dimensions are incompatible")
    config = RegimeModelConfig(**config_payload)
    fit = ClusterDiagnosticFit(
        schema_version=THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        symbol="BTCUSDT",
        config=config,
        feature_names=tuple(names),
        lower_bounds=_numeric_tuple(parameters["lower_bounds"], "lower bounds"),
        upper_bounds=_numeric_tuple(parameters["upper_bounds"], "upper bounds"),
        medians=_numeric_tuple(parameters["medians"], "medians"),
        scales=_numeric_tuple(parameters["scales"], "scales"),
        fingerprints=tuple(parameters["component_fingerprints"]),
        means=tuple(_numeric_tuple(row, "means") for row in parameters["means"]),
        weights=_numeric_tuple(parameters["weights"], "weights"),
        covariances=tuple(_numeric_tuple(row, "covariances") for row in parameters["covariances"]),
        distance_thresholds=(),
        converged=parameters["converged"],
        iterations=parameters["iterations"],
        lower_bound=parameters["lower_bound"],
    )
    _validate_complete_model_gates(payload["model_gates"], fit)
    return fit


def _validate_complete_model_gates(
    gates: Mapping[str, object], fit: ClusterDiagnosticFit,
) -> None:
    expected_constants = {
        "minimum_adjusted_rand_index_threshold": 0.8,
        "minimum_normalized_mutual_information_threshold": 0.8,
        "maximum_matched_centroid_distance_threshold": 0.5,
        "maximum_prevalence_drift_threshold": 0.2,
        "maximum_low_confidence_rate_threshold": 0.25,
        "maximum_distance_exceedance_rate_threshold": 0.02,
        "weight_sum_expected": 1.0,
        "weight_sum_tolerance": 1e-8,
        "covariance_floor_threshold": fit.config.regularization,
        "component_count_expected": 4,
        "gmm_probability_threshold": 0.65,
        "gmm_margin_threshold": 0.10,
        "feature_family_cap_maximum_count": 5,
        "feature_family_cap_maximum_share": 0.5,
        "distance_threshold_policy": "maximum_chi_square_995_squared_mahalanobis",
        "feature_registry_version_expected": "three-day-chart-feature-registry-v1",
    }
    if any(gates[name] != expected for name, expected in expected_constants.items()):
        raise ValueError("model gate constant or threshold is incompatible")
    required_true = (
        "convergence_required", "converged", "finite_scaler_required",
        "finite_model_parameters_required", "positive_weights_required",
        "all_components_represented_required", "all_components_represented",
        "all_chronological_blocks_represented_required",
        "all_chronological_blocks_represented", "feature_registry_exact",
        "feature_family_cap_passed", "all_components_represented_threshold",
        "all_chronological_blocks_represented_threshold",
    )
    if any(gates[name] is not True for name in required_true):
        raise ValueError("model gate required flags or frozen representation results are incompatible")

    finite_scaler = all(
        math.isfinite(value)
        for values in (fit.lower_bounds, fit.upper_bounds, fit.medians, fit.scales)
        for value in values
    )
    finite_model = all(
        math.isfinite(value)
        for values in (*fit.means, fit.weights, *fit.covariances)
        for value in values
    )
    family_counts = {
        family: sum(
            spec.family == family and spec.name in fit.feature_names
            for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1
        )
        for family in {spec.family for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
    }
    observed_count = max(family_counts.values())
    observed_share = observed_count / len(fit.feature_names)
    expected_distance = float(chi2.ppf(0.995, df=len(fit.feature_names)))
    derived_distance_result = (
        gates["distance_exceedance_rate"]
        <= gates["maximum_distance_exceedance_rate_threshold"]
    )
    derived_confidence = (
        gates["low_confidence_rate"] <= gates["maximum_low_confidence_rate_threshold"]
    )
    if (
        gates["finite_scaler"] is not finite_scaler
        or gates["finite_model_parameters"] is not finite_model
        or gates["converged"] is not fit.converged
        or gates["iterations"] != fit.iterations
        or gates["lower_bound"] != fit.lower_bound
        or gates["component_count"] != len(fit.fingerprints)
        or gates["minimum_weight"] != min(fit.weights)
        or gates["weight_sum"] != math.fsum(fit.weights)
        or not math.isclose(
            gates["weight_sum"], gates["weight_sum_expected"],
            rel_tol=gates["weight_sum_tolerance"], abs_tol=gates["weight_sum_tolerance"],
        )
        or gates["minimum_covariance"] != min(min(row) for row in fit.covariances)
        or gates["minimum_covariance"] < gates["covariance_floor_threshold"]
        or gates["feature_family_observed_maximum_count"] != observed_count
        or gates["feature_family_observed_maximum_share"] != observed_share
        or gates["feature_family_cap_passed"] is not (
            observed_count <= gates["feature_family_cap_maximum_count"]
            and observed_share <= gates["feature_family_cap_maximum_share"]
        )
        or not math.isclose(gates["distance_threshold"], expected_distance, rel_tol=1e-12, abs_tol=1e-12)
        or gates["distance_result"] is not derived_distance_result
        or gates["nondegenerate_confidence"] is not derived_confidence
    ):
        raise ValueError("model gate derived relationship does not match fit, registry, or thresholds")
    for name in (
        "minimum_adjusted_rand_index", "minimum_normalized_mutual_information",
        "maximum_prevalence_drift", "low_confidence_rate", "distance_exceedance_rate",
        "minimum_observed_dominant_probability", "minimum_observed_probability_margin",
    ):
        if not 0 <= gates[name] <= 1:
            raise ValueError("model gate rate or probability is outside its valid range")
    if gates["maximum_matched_centroid_distance"] < 0:
        raise ValueError("model gate centroid distance cannot be negative")


def _registry_payload() -> list[dict[str, object]]:
    return [
        {
            "name": spec.name, "family": spec.family,
            "aggregation_minutes": spec.aggregation_minutes,
            "lookback_minutes": spec.lookback_minutes, "formula": spec.formula,
            "null_policy": spec.null_policy, "clipping_policy": spec.clipping_policy,
            "scale_invariant": spec.scale_invariant,
        }
        for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1
    ]


def _load_frozen_k4_diagnostic_inputs(
    attempt_path: Path, raw_root: Path, profile: _FrozenK4SourceProfile,
) -> _LoadedK4DiagnosticInputs:
    if not isinstance(profile, _FrozenK4SourceProfile):
        raise ValueError("source profile must use the strict frozen profile contract")
    attempt_path = Path(attempt_path)
    raw = attempt_path.read_bytes()
    try:
        decoded = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("failed-model attempt JSON is invalid") from exc
    payload = _validate_attempt(decoded, profile)
    fit = _restore_primary_fit(payload)
    provenance = tuple(payload["source_provenance"])
    vectors, loaded_provenance = load_three_day_feature_history(
        symbol=profile.symbol, start=profile.raw_start_at,
        end=profile.fit_end_at, raw_root=Path(raw_root),
        expected_anchor_count=profile.expected_anchor_count,
        downloader=_LocalProvenanceDownloader(provenance, Path(raw_root)),
    )
    if tuple(map(dict, loaded_provenance)) != tuple(map(dict, provenance)):
        raise ValueError("loaded archive provenance differs from the frozen attempt")
    verified_vector_hash = _three_day_vector_hash(vectors)
    if verified_vector_hash != payload["fit_input_vector_hash"]:
        raise ValueError(f"fit input vector hash mismatch; reconstructed {verified_vector_hash}")
    anchors = [vector.anchor_at.isoformat() for vector in vectors]
    parameters = payload["model_parameters"]
    dependency_metadata = {
        name: importlib.metadata.version(name) for name in ("numpy", "scipy", "scikit-learn")
    }
    identity_hashes = {
        "failed_model_attempt_sha256": payload["attempt_hash"],
        "model_file_sha256": hashlib.sha256(raw).hexdigest(),
        "primary_parameters_sha256": _hash({
            key: parameters[key] for key in (
                "component_fingerprints", "converged", "covariances", "iterations",
                "lower_bound", "means", "weights"
            )
        }),
        "scaler_sha256": _hash({"medians": parameters["medians"], "scales": parameters["scales"]}),
        "clipping_bounds_sha256": _hash({"lower_bounds": parameters["lower_bounds"], "upper_bounds": parameters["upper_bounds"]}),
        "feature_schema_sha256": _hash({"schema_version": fit.schema_version, "feature_names": list(fit.feature_names), "registry": _registry_payload()}),
        "source_provenance_sha256": _hash(list(map(dict, loaded_provenance))),
        "source_anchor_manifest_sha256": _hash(anchors),
        "feature_vectors_sha256": verified_vector_hash,
        "dependency_metadata_sha256": _hash(dependency_metadata),
    }
    return _LoadedK4DiagnosticInputs(_deep_freeze(payload), fit, vectors, identity_hashes)


def load_frozen_k4_diagnostic_source(
    attempt_path: Path, raw_root: Path,
) -> FrozenK4DiagnosticSource:
    loaded = _load_frozen_k4_diagnostic_inputs(attempt_path, raw_root, _PRODUCTION_PROFILE)
    identity = FrozenK4InputIdentity(
        **loaded.identity_hashes,
        split_at="2023-04-01T00:00:00Z",
        half_a_range=("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
        half_b_range=("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z"),
    )
    return FrozenK4DiagnosticSource(
        loaded.attempt_payload, loaded.primary_fit, loaded.vectors, identity
    )


__all__ = ["FrozenK4DiagnosticSource", "load_frozen_k4_diagnostic_source"]
