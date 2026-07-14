"""Canonical, integrity-checked JSON persistence for frozen regime artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from src.domain.regime.mapping import (
    MAPPING_METRIC_NAMES,
    BootstrapConfig,
    CandidateMappingAssessment,
    MappingThresholds,
    StrategyMappingArtifact,
    StrategyMappingEntry,
)
from src.domain.regime.model import RegimeModelArtifact, RegimeModelConfig


_FORMAT = "gptrader-regime-artifact"
_FORMAT_VERSION = 1
_MODEL_FILE = "model.json"
_MAPPING_FILE = "mapping.json"
_ENVELOPE_FIELDS = {"format", "version", "kind", "payload", "artifact_hash"}


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("artifact contains a non-canonical JSON value") from error


def canonical_artifact_hash(payload: Mapping[str, object]) -> str:
    """Return SHA-256 over the exact canonical JSON payload (not its envelope)."""
    if not isinstance(payload, Mapping):
        raise ValueError("artifact payload must be an object")
    return hashlib.sha256(_canonical_bytes(dict(payload))).hexdigest()


def _model_payload(artifact: RegimeModelArtifact) -> dict[str, object]:
    return {
        "artifact_version": artifact.artifact_version,
        "symbol": artifact.symbol,
        "feature_schema_version": artifact.feature_schema_version,
        "config": {
            "model_type": artifact.config.model_type,
            "cluster_count": artifact.config.cluster_count,
            "random_seed": artifact.config.random_seed,
            "covariance_type": artifact.config.covariance_type,
            "regularization": float(artifact.config.regularization),
        },
        "feature_names": list(artifact.feature_names),
        "lower_bounds": [float(value) for value in artifact.lower_bounds],
        "upper_bounds": [float(value) for value in artifact.upper_bounds],
        "medians": [float(value) for value in artifact.medians],
        "scales": [float(value) for value in artifact.scales],
        "weights": [float(value) for value in artifact.weights],
        "means": [[float(value) for value in row] for row in artifact.means],
        "covariances": [[float(value) for value in row] for row in artifact.covariances],
        "fingerprints": list(artifact.fingerprints),
        "training_start_at": _datetime_text(artifact.training_start_at),
        "training_end_at": _datetime_text(artifact.training_end_at),
        "distance_thresholds": [float(value) for value in artifact.distance_thresholds],
    }


def model_artifact_hash(artifact: RegimeModelArtifact) -> str:
    return canonical_artifact_hash(_model_payload(artifact))


def model_fingerprint_hash(artifact: RegimeModelArtifact) -> str:
    """Hash ordered component fingerprints together with their model identity."""
    identity = {
        "artifact_version": artifact.artifact_version,
        "symbol": artifact.symbol,
        "feature_schema_version": artifact.feature_schema_version,
        "model_type": artifact.config.model_type,
        "cluster_count": artifact.config.cluster_count,
        "covariance_type": artifact.config.covariance_type,
        "feature_names": list(artifact.feature_names),
        "fingerprints": list(artifact.fingerprints),
    }
    return canonical_artifact_hash(identity)


def _decimal_text(value: Decimal) -> str:
    if value == Decimal("Infinity"):
        return "Infinity"
    if not value.is_finite():
        raise ValueError("only positive Infinity profit factor may be persisted")
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is not timezone.utc:
        raise ValueError("artifact datetime must use canonical UTC")
    return value.isoformat()


def _metrics_payload(metrics: Mapping[str, Decimal]) -> dict[str, str]:
    return {name: _decimal_text(value) for name, value in metrics.items()}


def _assessment_payload(value: CandidateMappingAssessment) -> dict[str, object]:
    return {
        "cluster_fingerprint": value.cluster_fingerprint,
        "candidate_id": value.candidate_id,
        "candidate_hash": value.candidate_hash,
        "weekly_episode_count": value.weekly_episode_count,
        "distinct_month_count": value.distinct_month_count,
        "closed_trade_count": value.closed_trade_count,
        "effective_episode_starts": [_datetime_text(item) for item in value.effective_episode_starts],
        "observed_mean": _decimal_text(value.observed_mean),
        "corrected_lower_bound": _decimal_text(value.corrected_lower_bound),
        "has_sufficient_consecutive_blocks": value.has_sufficient_consecutive_blocks,
        "eligible": value.eligible,
        "metrics": _metrics_payload(value.metrics),
        "rejection_reasons": list(value.rejection_reasons),
    }


def _entry_payload(value: StrategyMappingEntry) -> dict[str, object]:
    return {
        "cluster_fingerprint": value.cluster_fingerprint,
        "strategy_profile_id": value.strategy_profile_id,
        "decision": value.decision,
        "weekly_episode_count": value.weekly_episode_count,
        "distinct_month_count": value.distinct_month_count,
        "closed_trade_count": value.closed_trade_count,
        "corrected_lower_bound": _decimal_text(value.corrected_lower_bound),
        "metrics": _metrics_payload(value.metrics),
        "rejection_reasons": list(value.rejection_reasons),
    }


def _mapping_payload(artifact: StrategyMappingArtifact) -> dict[str, object]:
    return {
        "artifact_version": artifact.artifact_version,
        "regime_model_artifact_hash": artifact.regime_model_artifact_hash,
        "regime_model_fingerprint_hash": artifact.regime_model_fingerprint_hash,
        "candidate_definition_hash": artifact.candidate_definition_hash,
        "candidate_universe_hash": artifact.candidate_universe_hash,
        "candidate_hashes": dict(artifact.candidate_hashes),
        "data_provenance_hash": artifact.data_provenance_hash,
        "common_initial_equity": _decimal_text(artifact.common_initial_equity),
        "cluster_fingerprints": list(artifact.cluster_fingerprints),
        "entries": {key: _entry_payload(value) for key, value in artifact.entries.items()},
        "candidate_assessments": {
            cluster: {key: _assessment_payload(value) for key, value in items.items()}
            for cluster, items in artifact.candidate_assessments.items()
        },
        "thresholds": {
            "minimum_weekly_episodes": artifact.thresholds.minimum_weekly_episodes,
            "minimum_distinct_months": artifact.thresholds.minimum_distinct_months,
            "minimum_trade_count": artifact.thresholds.minimum_trade_count,
        },
        "bootstrap": {
            "block_length_weeks": artifact.bootstrap.block_length_weeks,
            "confidence": _decimal_text(artifact.bootstrap.confidence),
            "resamples": artifact.bootstrap.resamples,
            "random_seed": artifact.bootstrap.random_seed,
            "bootstrap_missingness_policy": artifact.bootstrap.bootstrap_missingness_policy,
            "insufficient_evidence_lcb_policy": artifact.bootstrap.insufficient_evidence_lcb_policy,
        },
        "profit_factor_zero_loss_policy": artifact.profit_factor_zero_loss_policy,
    }


class JsonRegimeArtifactRepository:
    """Persist model.json and mapping.json beneath one caller-selected directory."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self._directory = Path(directory)

    def save_model(self, artifact: RegimeModelArtifact) -> str:
        if not isinstance(artifact, RegimeModelArtifact):
            raise ValueError("model artifact has an invalid type")
        payload = _model_payload(artifact)
        artifact_hash = canonical_artifact_hash(payload)
        self._write_envelope(self._directory / _MODEL_FILE, "regime_model", payload, artifact_hash)
        return artifact_hash

    def load_model(
        self,
        *,
        expected_symbol: str,
        expected_schema: str,
        expected_artifact_hash: str | None = None,
        expected_fingerprint_hash: str | None = None,
    ) -> RegimeModelArtifact:
        payload, artifact_hash = self._read_envelope(self._directory / _MODEL_FILE, "regime_model")
        artifact = _decode_model(payload)
        if artifact.symbol != expected_symbol:
            raise ValueError("model symbol does not match expected symbol")
        if artifact.feature_schema_version != expected_schema:
            raise ValueError("model schema does not match expected schema")
        if expected_artifact_hash is not None and artifact_hash != expected_artifact_hash:
            raise ValueError("model artifact hash does not match expected model artifact hash")
        fingerprint_hash = model_fingerprint_hash(artifact)
        if expected_fingerprint_hash is not None and fingerprint_hash != expected_fingerprint_hash:
            raise ValueError("model fingerprint hash does not match expected model fingerprint hash")
        return artifact

    def save_mapping(
        self,
        artifact: StrategyMappingArtifact,
        *,
        expected_model_artifact_hash: str | None = None,
        expected_model_fingerprint_hash: str | None = None,
    ) -> str:
        if not isinstance(artifact, StrategyMappingArtifact):
            raise ValueError("mapping artifact has an invalid type")
        self._validate_model_link(
            artifact,
            expected_model_artifact_hash=expected_model_artifact_hash,
            expected_model_fingerprint_hash=expected_model_fingerprint_hash,
        )
        payload = _mapping_payload(artifact)
        artifact_hash = canonical_artifact_hash(payload)
        self._write_envelope(self._directory / _MAPPING_FILE, "strategy_mapping", payload, artifact_hash)
        return artifact_hash

    def load_mapping(
        self,
        *,
        expected_candidate_definition_hash: str | None = None,
        expected_candidate_universe_hash: str | None = None,
        expected_data_provenance_hash: str | None = None,
        expected_model_artifact_hash: str | None = None,
        expected_model_fingerprint_hash: str | None = None,
        expected_artifact_hash: str | None = None,
    ) -> StrategyMappingArtifact:
        payload, artifact_hash = self._read_envelope(self._directory / _MAPPING_FILE, "strategy_mapping")
        artifact = _decode_mapping(payload)
        if expected_artifact_hash is not None and artifact_hash != expected_artifact_hash:
            raise ValueError("mapping artifact hash does not match expected mapping artifact hash")
        expectations = (
            ("candidate definition hash", artifact.candidate_definition_hash, expected_candidate_definition_hash),
            ("candidate universe hash", artifact.candidate_universe_hash, expected_candidate_universe_hash),
            ("data provenance hash", artifact.data_provenance_hash, expected_data_provenance_hash),
        )
        for label, actual, expected in expectations:
            if expected is not None and actual != expected:
                raise ValueError(f"{label} does not match expected {label}")
        self._validate_model_link(
            artifact,
            expected_model_artifact_hash=expected_model_artifact_hash,
            expected_model_fingerprint_hash=expected_model_fingerprint_hash,
        )
        return artifact

    def _validate_model_link(
        self,
        mapping: StrategyMappingArtifact,
        *,
        expected_model_artifact_hash: str | None,
        expected_model_fingerprint_hash: str | None,
    ) -> None:
        if (
            expected_model_artifact_hash is not None
            and mapping.regime_model_artifact_hash != expected_model_artifact_hash
        ):
            raise ValueError("model artifact hash does not match expected model artifact hash")
        if (
            expected_model_fingerprint_hash is not None
            and mapping.regime_model_fingerprint_hash != expected_model_fingerprint_hash
        ):
            raise ValueError("model fingerprint hash does not match expected model fingerprint hash")

        model_path = self._directory / _MODEL_FILE
        if model_path.exists():
            payload, linked_hash = self._read_envelope(model_path, "regime_model")
            model = _decode_model(payload)
            linked_fingerprint_hash = model_fingerprint_hash(model)
            linked_cluster_fingerprints = model.fingerprints
        else:
            if expected_model_artifact_hash is None or expected_model_fingerprint_hash is None:
                raise ValueError("standalone mapping requires expected model artifact and fingerprint hashes")
            linked_hash = expected_model_artifact_hash
            linked_fingerprint_hash = expected_model_fingerprint_hash
            linked_cluster_fingerprints = None
        if mapping.regime_model_artifact_hash != linked_hash:
            raise ValueError("mapping model artifact hash does not match linked model artifact hash")
        if mapping.regime_model_fingerprint_hash != linked_fingerprint_hash:
            raise ValueError("mapping model fingerprint hash does not match linked model fingerprint hash")
        if (
            linked_cluster_fingerprints is not None
            and mapping.cluster_fingerprints != linked_cluster_fingerprints
        ):
            raise ValueError("mapping cluster fingerprints do not match linked model cluster fingerprints")

    def _write_envelope(
        self,
        target: Path,
        kind: str,
        payload: Mapping[str, object],
        artifact_hash: str,
    ) -> None:
        envelope = {
            "format": _FORMAT,
            "version": _FORMAT_VERSION,
            "kind": kind,
            "payload": dict(payload),
            "artifact_hash": artifact_hash,
        }
        data = _canonical_bytes(envelope) + b"\n"
        self._directory.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=self._directory
            )
            temporary = Path(raw_path)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            temporary = None
            _fsync_directory(self._directory)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _read_envelope(path: Path, expected_kind: str) -> tuple[dict[str, object], str]:
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ValueError(f"cannot read artifact JSON: {path.name}") from error
        try:
            value = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, UnicodeError) as error:
            raise ValueError("artifact contains malformed JSON") from error
        if not isinstance(value, dict):
            raise ValueError("artifact envelope must be a JSON object")
        _exact_fields(value, _ENVELOPE_FIELDS, "artifact envelope")
        if value["format"] != _FORMAT:
            raise ValueError("unsupported artifact format")
        if type(value["version"]) is not int or value["version"] != _FORMAT_VERSION:
            raise ValueError("unsupported artifact format version")
        if value["kind"] != expected_kind:
            raise ValueError("artifact kind does not match requested artifact")
        payload = value["payload"]
        artifact_hash = value["artifact_hash"]
        if not isinstance(payload, dict) or not isinstance(artifact_hash, str):
            raise ValueError("artifact envelope payload or hash has an invalid type")
        if canonical_artifact_hash(payload) != artifact_hash:
            raise ValueError("artifact hash does not match canonical payload")
        return payload, artifact_hash


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _exact_fields(value: Mapping[str, object], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unknown:
            details.append(f"unknown {', '.join(unknown)}")
        raise ValueError(f"{label} fields are invalid: {'; '.join(details)}")


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _dict(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object with string keys")
    return value


def _text(value: object, field: str, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a JSON number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _decimal(value: object, field: str, *, allow_infinity: bool = False) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a Decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{field} must be a canonical Decimal string") from error
    if result == Decimal("Infinity") and allow_infinity:
        return result
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    if _decimal_text(result) != value:
        raise ValueError(f"{field} must be a canonical Decimal string")
    return result


def _datetime(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO UTC timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO UTC timestamp") from error
    if result.tzinfo is not timezone.utc or result.isoformat() != value:
        raise ValueError(f"{field} must use canonical UTC +00:00")
    return result


def _decode_model(payload: dict[str, object]) -> RegimeModelArtifact:
    fields = {
        "artifact_version", "symbol", "feature_schema_version", "config", "feature_names",
        "lower_bounds", "upper_bounds", "medians", "scales", "weights", "means",
        "covariances", "fingerprints", "training_start_at", "training_end_at",
        "distance_thresholds",
    }
    _exact_fields(payload, fields, "model payload")
    config_data = _dict(payload["config"], "model config")
    _exact_fields(
        config_data,
        {"model_type", "cluster_count", "random_seed", "covariance_type", "regularization"},
        "model config",
    )
    covariance_type = _text(config_data["covariance_type"], "covariance_type", nullable=True)
    config = RegimeModelConfig(
        model_type=_text(config_data["model_type"], "model_type"),
        cluster_count=_integer(config_data["cluster_count"], "cluster_count"),
        random_seed=_integer(config_data["random_seed"], "random_seed"),
        covariance_type=covariance_type,
        regularization=_number(config_data["regularization"], "regularization"),
    )

    def floats(name: str) -> tuple[float, ...]:
        return tuple(_number(item, name) for item in _list(payload[name], name))

    def matrix(name: str) -> tuple[tuple[float, ...], ...]:
        return tuple(
            tuple(_number(item, name) for item in _list(row, name))
            for row in _list(payload[name], name)
        )

    return RegimeModelArtifact(
        artifact_version=_text(payload["artifact_version"], "artifact_version"),
        symbol=_text(payload["symbol"], "symbol"),
        feature_schema_version=_text(payload["feature_schema_version"], "feature_schema_version"),
        config=config,
        feature_names=tuple(_text(item, "feature_name") for item in _list(payload["feature_names"], "feature_names")),
        lower_bounds=floats("lower_bounds"),
        upper_bounds=floats("upper_bounds"),
        medians=floats("medians"),
        scales=floats("scales"),
        weights=floats("weights"),
        means=matrix("means"),
        covariances=matrix("covariances"),
        fingerprints=tuple(_text(item, "fingerprint") for item in _list(payload["fingerprints"], "fingerprints")),
        training_start_at=_datetime(payload["training_start_at"], "training_start_at"),
        training_end_at=_datetime(payload["training_end_at"], "training_end_at"),
        distance_thresholds=floats("distance_thresholds"),
    )


def _decode_metrics(value: object) -> dict[str, Decimal]:
    data = _dict(value, "metrics")
    _exact_fields(data, set(MAPPING_METRIC_NAMES), "metrics")
    return {
        name: _decimal(data[name], f"metric {name}", allow_infinity=name == "profit_factor")
        for name in MAPPING_METRIC_NAMES
    }


def _decode_assessment(value: object) -> CandidateMappingAssessment:
    data = _dict(value, "candidate assessment")
    fields = {
        "cluster_fingerprint", "candidate_id", "candidate_hash", "weekly_episode_count",
        "distinct_month_count", "closed_trade_count", "effective_episode_starts",
        "observed_mean", "corrected_lower_bound", "has_sufficient_consecutive_blocks",
        "eligible", "metrics", "rejection_reasons",
    }
    _exact_fields(data, fields, "candidate assessment")
    sufficient = data["has_sufficient_consecutive_blocks"]
    eligible = data["eligible"]
    if type(sufficient) is not bool or type(eligible) is not bool:
        raise ValueError("assessment flags must be booleans")
    return CandidateMappingAssessment(
        cluster_fingerprint=_text(data["cluster_fingerprint"], "cluster_fingerprint"),
        candidate_id=_text(data["candidate_id"], "candidate_id"),
        candidate_hash=_text(data["candidate_hash"], "candidate_hash"),
        weekly_episode_count=_integer(data["weekly_episode_count"], "weekly_episode_count"),
        distinct_month_count=_integer(data["distinct_month_count"], "distinct_month_count"),
        closed_trade_count=_integer(data["closed_trade_count"], "closed_trade_count"),
        effective_episode_starts=tuple(
            _datetime(item, "effective_episode_start")
            for item in _list(data["effective_episode_starts"], "effective_episode_starts")
        ),
        observed_mean=_decimal(data["observed_mean"], "observed_mean"),
        corrected_lower_bound=_decimal(data["corrected_lower_bound"], "corrected_lower_bound"),
        has_sufficient_consecutive_blocks=sufficient,
        eligible=eligible,
        metrics=_decode_metrics(data["metrics"]),
        rejection_reasons=tuple(
            _text(item, "rejection_reason")
            for item in _list(data["rejection_reasons"], "rejection_reasons")
        ),
    )


def _decode_entry(value: object) -> StrategyMappingEntry:
    data = _dict(value, "mapping entry")
    fields = {
        "cluster_fingerprint", "strategy_profile_id", "decision", "weekly_episode_count",
        "distinct_month_count", "closed_trade_count", "corrected_lower_bound", "metrics",
        "rejection_reasons",
    }
    _exact_fields(data, fields, "mapping entry")
    return StrategyMappingEntry(
        cluster_fingerprint=_text(data["cluster_fingerprint"], "cluster_fingerprint"),
        strategy_profile_id=_text(data["strategy_profile_id"], "strategy_profile_id", nullable=True),
        decision=_text(data["decision"], "decision"),
        weekly_episode_count=_integer(data["weekly_episode_count"], "weekly_episode_count"),
        distinct_month_count=_integer(data["distinct_month_count"], "distinct_month_count"),
        closed_trade_count=_integer(data["closed_trade_count"], "closed_trade_count"),
        corrected_lower_bound=_decimal(data["corrected_lower_bound"], "corrected_lower_bound"),
        metrics=_decode_metrics(data["metrics"]),
        rejection_reasons=tuple(
            _text(item, "rejection_reason")
            for item in _list(data["rejection_reasons"], "rejection_reasons")
        ),
    )


def _decode_mapping(payload: dict[str, object]) -> StrategyMappingArtifact:
    fields = {
        "artifact_version", "regime_model_artifact_hash", "regime_model_fingerprint_hash",
        "candidate_definition_hash", "candidate_universe_hash", "candidate_hashes",
        "data_provenance_hash", "common_initial_equity", "cluster_fingerprints", "entries",
        "candidate_assessments", "thresholds", "bootstrap", "profit_factor_zero_loss_policy",
    }
    _exact_fields(payload, fields, "mapping payload")
    thresholds_data = _dict(payload["thresholds"], "mapping thresholds")
    _exact_fields(
        thresholds_data,
        {"minimum_weekly_episodes", "minimum_distinct_months", "minimum_trade_count"},
        "mapping thresholds",
    )
    bootstrap_data = _dict(payload["bootstrap"], "bootstrap config")
    _exact_fields(
        bootstrap_data,
        {
            "block_length_weeks", "confidence", "resamples", "random_seed",
            "bootstrap_missingness_policy", "insufficient_evidence_lcb_policy",
        },
        "bootstrap config",
    )
    candidate_hashes = _dict(payload["candidate_hashes"], "candidate_hashes")
    entries_data = _dict(payload["entries"], "entries")
    assessments_data = _dict(payload["candidate_assessments"], "candidate_assessments")
    return StrategyMappingArtifact(
        artifact_version=_text(payload["artifact_version"], "artifact_version"),
        regime_model_artifact_hash=_text(payload["regime_model_artifact_hash"], "regime_model_artifact_hash"),
        regime_model_fingerprint_hash=_text(payload["regime_model_fingerprint_hash"], "regime_model_fingerprint_hash"),
        candidate_definition_hash=_text(payload["candidate_definition_hash"], "candidate_definition_hash"),
        candidate_universe_hash=_text(payload["candidate_universe_hash"], "candidate_universe_hash"),
        candidate_hashes={key: _text(value, "candidate_hash") for key, value in candidate_hashes.items()},
        data_provenance_hash=_text(payload["data_provenance_hash"], "data_provenance_hash"),
        common_initial_equity=_decimal(payload["common_initial_equity"], "common_initial_equity"),
        cluster_fingerprints=tuple(
            _text(item, "cluster_fingerprint")
            for item in _list(payload["cluster_fingerprints"], "cluster_fingerprints")
        ),
        entries={key: _decode_entry(value) for key, value in entries_data.items()},
        candidate_assessments={
            cluster: {
                key: _decode_assessment(value)
                for key, value in _dict(items, "cluster candidate assessments").items()
            }
            for cluster, items in assessments_data.items()
        },
        thresholds=MappingThresholds(
            minimum_weekly_episodes=_integer(thresholds_data["minimum_weekly_episodes"], "minimum_weekly_episodes"),
            minimum_distinct_months=_integer(thresholds_data["minimum_distinct_months"], "minimum_distinct_months"),
            minimum_trade_count=_integer(thresholds_data["minimum_trade_count"], "minimum_trade_count"),
        ),
        bootstrap=BootstrapConfig(
            block_length_weeks=_integer(bootstrap_data["block_length_weeks"], "block_length_weeks"),
            confidence=_decimal(bootstrap_data["confidence"], "confidence"),
            resamples=_integer(bootstrap_data["resamples"], "resamples"),
            random_seed=_integer(bootstrap_data["random_seed"], "random_seed"),
            bootstrap_missingness_policy=_text(bootstrap_data["bootstrap_missingness_policy"], "bootstrap_missingness_policy"),
            insufficient_evidence_lcb_policy=_text(bootstrap_data["insufficient_evidence_lcb_policy"], "insufficient_evidence_lcb_policy"),
        ),
        profit_factor_zero_loss_policy=_text(payload["profit_factor_zero_loss_policy"], "profit_factor_zero_loss_policy"),
    )


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory sync; opening directories is unavailable on Windows."""
    if os.name == "nt":
        return
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "JsonRegimeArtifactRepository",
    "canonical_artifact_hash",
    "model_artifact_hash",
    "model_fingerprint_hash",
]
