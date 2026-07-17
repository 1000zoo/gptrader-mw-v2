"""Provenance-bound, local-only inputs for the frozen K4 failure diagnostic."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

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
    validate_archive_member_directory,
)
from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
    load_three_day_feature_history,
)
from src.infrastructure.regime.three_day_k4_model_artifact import (
    validate_three_day_k4_source_provenance,
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


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


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
    def __init__(self, rows: tuple[Mapping[str, object], ...]) -> None:
        self._rows = {str(row["url"]): row for row in rows}

    def download(
        self, url: str, destination: Path, *, source: str | None = None,
        max_bytes: int | None = None,
    ) -> DownloadResult:
        del max_bytes
        row = self._rows.get(url)
        if row is None:
            raise ValueError("archive URL is not present in frozen source provenance")
        destination = Path(destination)
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


def _validate_attempt(payload: object) -> dict[str, object]:
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
    if (
        payload["schema_version"] != "three-day-k4-model-attempt-v1"
        or payload["profile_id"] != PROFILE_ID
        or payload["status"] != "failed-model-gates"
        or payload["fit_input_anchor_count"] != 1_641
    ):
        raise ValueError("failed-model attempt profile is incompatible")
    first = _parse_time(payload["first_usable_anchor_at"], "first usable anchor")
    last = _parse_time(payload["last_usable_anchor_at"], "last usable anchor")
    if first != datetime(2021, 1, 1, tzinfo=timezone.utc) or last >= _CUTOFF:
        raise ValueError("source anchors must remain before the frozen cutoff")
    interval = payload["fit_interval"]
    if not isinstance(interval, dict) or set(interval) != {"start_at", "end_at"}:
        raise ValueError("fit interval is incompatible")
    if _parse_time(interval["start_at"], "fit start") != first or _parse_time(interval["end_at"], "fit end") != _CUTOFF:
        raise ValueError("fit interval is incompatible")
    provenance = validate_three_day_k4_source_provenance(payload["source_provenance"])
    if payload["source_provenance_hash"] != _hash(list(map(dict, provenance))):
        raise ValueError("source provenance hash mismatch")
    payload["source_provenance"] = [dict(row) for row in provenance]
    return payload


def _numeric_tuple(value: object, field: str) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise ValueError(f"primary {field} is incompatible")
    try:
        return tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"primary {field} is incompatible") from exc


def _restore_primary_fit(payload: Mapping[str, object]) -> ClusterDiagnosticFit:
    config_payload = payload["model_config"]
    parameters = payload["model_parameters"]
    if not isinstance(config_payload, dict) or set(config_payload) != {
        "cluster_count", "covariance_type", "model_type", "random_seed", "regularization"
    }:
        raise ValueError("primary model config is incompatible")
    expected_parameters = {
        "component_fingerprints", "converged", "covariances", "iterations", "lower_bound",
        "lower_bounds", "means", "medians", "scales", "upper_bounds", "weights",
    }
    if not isinstance(parameters, dict) or set(parameters) != expected_parameters:
        raise ValueError("primary model parameters are incompatible")
    names = payload["feature_names"]
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("primary feature schema is incompatible")
    config = RegimeModelConfig(**config_payload)
    return ClusterDiagnosticFit(
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


def load_frozen_k4_diagnostic_source(
    attempt_path: Path, raw_root: Path
) -> FrozenK4DiagnosticSource:
    attempt_path = Path(attempt_path)
    raw = attempt_path.read_bytes()
    try:
        decoded = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("failed-model attempt JSON is invalid") from exc
    payload = _validate_attempt(decoded)
    fit = _restore_primary_fit(payload)
    provenance = tuple(payload["source_provenance"])
    start = datetime(2021, 1, 1, tzinfo=timezone.utc) - timedelta(days=3)
    vectors, loaded_provenance = load_three_day_feature_history(
        symbol="BTCUSDT", start=start, end=_CUTOFF, raw_root=Path(raw_root),
        expected_anchor_count=1_641,
        downloader=_LocalProvenanceDownloader(provenance),
    )
    if tuple(map(dict, loaded_provenance)) != tuple(map(dict, provenance)):
        raise ValueError("loaded archive provenance differs from the frozen attempt")
    vector_payload = [
        {
            "symbol": vector.symbol,
            "anchor_at": vector.anchor_at.isoformat().replace("+00:00", "Z"),
            "window_start_at": vector.window_start_at.isoformat().replace("+00:00", "Z"),
            "values": dict(vector.values),
        }
        for vector in vectors
    ]
    anchors = [item["anchor_at"] for item in vector_payload]
    parameters = payload["model_parameters"]
    dependency_metadata = {
        name: importlib.metadata.version(name) for name in ("numpy", "scipy", "scikit-learn")
    }
    identity = FrozenK4InputIdentity(
        failed_model_attempt_sha256=payload["attempt_hash"],
        model_file_sha256=hashlib.sha256(raw).hexdigest(),
        primary_parameters_sha256=_hash({
            key: parameters[key] for key in (
                "component_fingerprints", "converged", "covariances", "iterations",
                "lower_bound", "means", "weights"
            )
        }),
        scaler_sha256=_hash({"medians": parameters["medians"], "scales": parameters["scales"]}),
        clipping_bounds_sha256=_hash({"lower_bounds": parameters["lower_bounds"], "upper_bounds": parameters["upper_bounds"]}),
        feature_schema_sha256=_hash({"schema_version": fit.schema_version, "feature_names": list(fit.feature_names), "registry": _registry_payload()}),
        source_provenance_sha256=_hash(list(map(dict, loaded_provenance))),
        source_anchor_manifest_sha256=_hash(anchors),
        feature_vectors_sha256=_hash(vector_payload),
        dependency_metadata_sha256=_hash(dependency_metadata),
        split_at="2023-04-01T00:00:00Z",
        half_a_range=("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
        half_b_range=("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z"),
    )
    return FrozenK4DiagnosticSource(_deep_freeze(payload), fit, vectors, identity)


__all__ = ["FrozenK4DiagnosticSource", "load_frozen_k4_diagnostic_source"]
