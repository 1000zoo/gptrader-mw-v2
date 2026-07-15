"""Strict restoration of fixed research-only fits for historical replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from src.domain.regime.chart_features import ChartFeatureSpec
from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.model import RegimeModelConfig
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)


_KIND = "three_day_regime_balance_diagnostic"
_VERSION = "three-day-regime-balance-diagnostic-v1"
_SYMBOL = "BTCUSDT"
_SAMPLE_COUNT = 727
_START_TEXT = "2024-07-01T00:00:00Z"
_END_TEXT = "2026-07-01T00:00:00Z"
_START = datetime(2024, 7, 1, tzinfo=timezone.utc)
_END = datetime(2026, 7, 1, tzinfo=timezone.utc)
_SELECTED_IDENTITIES = ("gmm-diag-k4", "gmm-diag-k8")
_CANDIDATE_IDENTITIES = (
    *(f"kmeans-k{count}" for count in range(3, 9)),
    *(identity for count in range(3, 9) for identity in (f"gmm-diag-k{count}", f"gmm-tied-k{count}")),
)
_REMOVED_NAMES = ("atr_ratio_1d", "atr_ratio_3d", "top_decile_volume_share_3d")
_RETAINED_NAMES = tuple(
    spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1 if spec.name not in _REMOVED_NAMES
)
_EXPECTED_TRAINING_COUNTS = {
    "gmm-diag-k4": {
        "0f705f28e5bf54678ca0ebe3": 116,
        "6d0d1affcd5a616a8daf784b": 188,
        "717c5b1f6e6900bf9f2a7d48": 187,
        "baed8e58c11ce3b4f680e945": 236,
    },
    "gmm-diag-k8": {
        "021cf5da658bbb8a891d3803": 104,
        "340255b9bb291b2c8bf6951c": 58,
        "4c135e31ff2eb6abf8897fc3": 83,
        "50a4d2af865d577c31b3c85f": 100,
        "7e2850f05408573738b5e3d5": 88,
        "98ee2ae3b65563954026199d": 86,
        "be23e3975752ecc63885bc0d": 138,
        "e27a95030541d7f7555832b9": 70,
    },
}


@dataclass(frozen=True)
class HistoricalReplaySource:
    """Immutable research source containing no runtime artifact."""

    report_sha256: str
    training_start_at: datetime
    training_end_at: datetime
    registry: tuple[ChartFeatureSpec, ...]
    fits: Mapping[str, ClusterDiagnosticFit]
    training_counts: Mapping[str, Mapping[str, int]]

    def __post_init__(self) -> None:
        copied_fits = MappingProxyType(dict(self.fits))
        copied_counts = MappingProxyType(
            {
                identity: MappingProxyType(dict(counts))
                for identity, counts in self.training_counts.items()
            }
        )
        object.__setattr__(self, "registry", tuple(self.registry))
        object.__setattr__(self, "fits", copied_fits)
        object.__setattr__(self, "training_counts", copied_counts)


def load_historical_replay_source(
    path: Path, *, expected_sha256: str
) -> HistoricalReplaySource:
    """Validate a committed diagnostic report and restore its fixed K4/K8 fits."""

    raw = Path(path).read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError("source diagnostic report hash mismatch")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("source diagnostic report is not canonical JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("source diagnostic report must be an object")

    _validate_report_header(payload)
    _validate_feature_schema(payload.get("feature_schema"))
    candidates = _validate_candidate_registry(payload.get("candidate_configs"))

    fits: dict[str, ClusterDiagnosticFit] = {}
    training_counts: dict[str, Mapping[str, int]] = {}
    for identity in _SELECTED_IDENTITIES:
        candidate = candidates[identity]
        fit = _restore_fit(candidate)
        counts = _restore_training_counts(candidate, fit)
        fits[identity] = fit
        training_counts[identity] = counts

    return HistoricalReplaySource(
        report_sha256=actual_sha256,
        training_start_at=_START,
        training_end_at=_END,
        registry=THREE_DAY_CHART_FEATURE_REGISTRY_V1,
        fits=fits,
        training_counts=training_counts,
    )


def _validate_report_header(payload: Mapping[str, object]) -> None:
    if payload.get("kind") != _KIND:
        raise ValueError("source diagnostic report kind is incompatible")
    if payload.get("version") != _VERSION:
        raise ValueError("source diagnostic report version is incompatible")
    if payload.get("symbol") != _SYMBOL:
        raise ValueError("source diagnostic report symbol is incompatible")
    if payload.get("interval") != {
        "start_inclusive": _START_TEXT,
        "end_exclusive": _END_TEXT,
    }:
        raise ValueError("source diagnostic report interval is incompatible")
    sample_count = payload.get("sample_count")
    if sample_count != _SAMPLE_COUNT or isinstance(sample_count, bool):
        raise ValueError("source diagnostic report sample count is incompatible")
    if (
        payload.get("strategy_outcomes_read") is not False
        or payload.get("strategy_outcomes_evaluated") is not False
        or payload.get("production_model_selected") is not False
        or payload.get("outcome_evaluation") != "reserved_not_evaluated"
        or payload.get("ranking_purpose") != "descriptive_only"
    ):
        raise ValueError("source diagnostic report outcome flags are incompatible")


def _validate_feature_schema(value: object) -> None:
    if not isinstance(value, dict):
        raise ValueError("source feature schema is missing")
    if value.get("version") != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION:
        raise ValueError("source feature schema version is incompatible")
    registry = _restore_feature_registry(value.get("registry"))
    if registry != THREE_DAY_CHART_FEATURE_REGISTRY_V1:
        raise ValueError("source feature registry is incompatible")
    expected_retained = {
        identity: list(_RETAINED_NAMES) for identity in _CANDIDATE_IDENTITIES
    }
    expected_removed = {
        identity: list(_REMOVED_NAMES) for identity in _CANDIDATE_IDENTITIES
    }
    if value.get("retained_by_candidate") != expected_retained:
        raise ValueError("source retained feature names are incompatible")
    if value.get("removed_by_candidate") != expected_removed:
        raise ValueError("source removed feature names are incompatible")


def _validate_candidate_registry(value: object) -> dict[str, Mapping[str, object]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("source candidate registry is incompatible")
    identities = tuple(item.get("identity") for item in value)
    if identities != _CANDIDATE_IDENTITIES:
        raise ValueError("source candidate registry is incomplete or duplicated")

    candidates: dict[str, Mapping[str, object]] = {}
    for candidate in value:
        identity = candidate["identity"]
        config = _restore_config(candidate.get("model"))
        if identity != _config_identity(config):
            raise ValueError("source candidate identity disagrees with model config")
        if not _type_strict_mapping_equal(
            candidate.get("model"), _expected_model_config(identity)
        ):
            raise ValueError("source candidate model config is incompatible")
        if candidate.get("status") != "accepted":
            raise ValueError("source candidate status is not accepted")
        if candidate.get("rejections") != []:
            raise ValueError("source candidate contains a technical rejection")
        candidates[identity] = candidate
    return candidates


def _restore_config(value: object) -> RegimeModelConfig:
    if not isinstance(value, dict) or set(value) != {
        "model_type",
        "cluster_count",
        "random_seed",
        "covariance_type",
        "regularization",
    }:
        raise ValueError("source candidate model config is incompatible")
    try:
        return RegimeModelConfig(
            model_type=value["model_type"],
            cluster_count=value["cluster_count"],
            random_seed=value["random_seed"],
            covariance_type=value["covariance_type"],
            regularization=value["regularization"],
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("source candidate model config is incompatible") from exc


def _config_identity(config: RegimeModelConfig) -> str:
    if config.model_type == "kmeans":
        return f"kmeans-k{config.cluster_count}"
    return f"gmm-{config.covariance_type}-k{config.cluster_count}"


def _expected_model_config(identity: str) -> dict[str, object]:
    model, count_text = identity.rsplit("-k", 1)
    if model == "kmeans":
        model_type = "kmeans"
        covariance_type = None
    else:
        model_type = "gmm"
        covariance_type = model.removeprefix("gmm-")
    return {
        "model_type": model_type,
        "cluster_count": int(count_text),
        "random_seed": 20260714,
        "covariance_type": covariance_type,
        "regularization": 1e-6,
    }


def _type_strict_mapping_equal(value: object, expected: Mapping[str, object]) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(expected)
        and all(
            type(value[key]) is type(expected_value) and value[key] == expected_value
            for key, expected_value in expected.items()
        )
    )


def _restore_feature_registry(value: object) -> tuple[ChartFeatureSpec, ...]:
    if not isinstance(value, list):
        raise ValueError("source feature registry is incompatible")
    field_types = {
        "name": str,
        "family": str,
        "aggregation_minutes": int,
        "lookback_minutes": int,
        "formula": str,
        "null_policy": str,
        "clipping_policy": str,
        "scale_invariant": bool,
    }
    restored: list[ChartFeatureSpec] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != set(field_types)
            or any(
                type(item[field]) is not expected
                for field, expected in field_types.items()
            )
        ):
            raise ValueError("source feature registry is incompatible")
        restored.append(ChartFeatureSpec(**item))
    return tuple(restored)


def _restore_fit(candidate: Mapping[str, object]) -> ClusterDiagnosticFit:
    identity = candidate["identity"]
    config = _restore_config(candidate.get("model"))
    if identity not in _SELECTED_IDENTITIES or config.model_type != "gmm" or config.covariance_type != "diag":
        raise ValueError("source selected fit config is incompatible")
    value = candidate.get("fit")
    expected_keys = {
        "covariances",
        "fingerprints",
        "lower_bounds",
        "means",
        "medians",
        "retained_feature_names",
        "scales",
        "upper_bounds",
        "weights",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ValueError("source selected diagnostic fit is incompatible")
    if value.get("retained_feature_names") != list(_RETAINED_NAMES):
        raise ValueError("source selected retained feature names are incompatible")
    try:
        return ClusterDiagnosticFit(
            schema_version=THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
            symbol=_SYMBOL,
            config=config,
            feature_names=tuple(value["retained_feature_names"]),
            lower_bounds=_numeric_tuple(value["lower_bounds"]),
            upper_bounds=_numeric_tuple(value["upper_bounds"]),
            medians=_numeric_tuple(value["medians"]),
            scales=_numeric_tuple(value["scales"]),
            fingerprints=tuple(value["fingerprints"]),
            means=_numeric_matrix(value["means"]),
            weights=_numeric_tuple(value["weights"]),
            covariances=_numeric_matrix(value["covariances"]),
            distance_thresholds=(),
        )
    except (KeyError, TypeError, ValueError) as exc:
        message = str(exc)
        if "weight" in message:
            raise ValueError("source selected fit weights are incompatible") from exc
        if "fingerprint" in message:
            raise ValueError("source selected fit fingerprint is incompatible") from exc
        raise ValueError("source selected diagnostic fit is incompatible") from exc


def _restore_training_counts(
    candidate: Mapping[str, object], fit: ClusterDiagnosticFit
) -> Mapping[str, int]:
    identity = candidate["identity"]
    metrics = candidate.get("metrics")
    counts = metrics.get("counts") if isinstance(metrics, dict) else None
    expected = _EXPECTED_TRAINING_COUNTS[identity]
    if (
        not isinstance(counts, dict)
        or counts != expected
        or tuple(counts) != fit.fingerprints
        or any(not isinstance(count, int) or isinstance(count, bool) or count < 0 for count in counts.values())
        or sum(counts.values()) != _SAMPLE_COUNT
    ):
        raise ValueError("source selected fit training counts are incompatible")
    return dict(counts)


def _numeric_tuple(value: object) -> tuple[float, ...]:
    if not isinstance(value, list):
        raise ValueError("numeric sequence must be a list")
    return tuple(value)


def _numeric_matrix(value: object) -> tuple[tuple[float, ...], ...]:
    if not isinstance(value, list) or any(not isinstance(row, list) for row in value):
        raise ValueError("numeric matrix must contain lists")
    return tuple(tuple(row) for row in value)


__all__ = ["HistoricalReplaySource", "load_historical_replay_source"]
