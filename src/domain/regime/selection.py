from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Mapping

from src.domain.regime.temporal import is_regime_boundary


class SelectionEventType(Enum):
    CLASSIFICATION = "classification"
    ENTRY_SUSPENDED = "entry_suspended"
    CLUSTER_TRANSITION = "cluster_transition"
    STRATEGY_TRANSITION = "strategy_transition"
    CASH_TRANSITION = "cash_transition"
    ARTIFACT_REPLACED = "artifact_replaced"


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _canonical_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a nonempty canonical string")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _canonical_text(value, field)


def _nonnegative_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA256 hash")
    return value


def _probability(value: object, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"{field} must be finite and between zero and one")
    return float(value)


def _distance(value: object, field: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{field} must be finite and nonnegative")
    return float(value)


@dataclass(frozen=True)
class SelectionConfidenceThresholds:
    model_type: str
    gmm_probability_min: float | None = None
    gmm_margin_min: float | None = None
    kmeans_max_standardized_distances: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if self.model_type == "gmm":
            if self.gmm_probability_min is None or self.gmm_margin_min is None:
                raise ValueError("GMM confidence thresholds are required")
            _probability(self.gmm_probability_min, "gmm_probability_min")
            _probability(self.gmm_margin_min, "gmm_margin_min")
            if self.kmeans_max_standardized_distances:
                raise ValueError("GMM thresholds cannot contain KMeans distances")
            object.__setattr__(
                self,
                "gmm_probability_min",
                _probability(self.gmm_probability_min, "gmm_probability_min"),
            )
            object.__setattr__(
                self,
                "gmm_margin_min",
                _probability(self.gmm_margin_min, "gmm_margin_min"),
            )
            object.__setattr__(
                self, "kmeans_max_standardized_distances", MappingProxyType({})
            )
        elif self.model_type == "kmeans":
            distances = dict(self.kmeans_max_standardized_distances)
            if not distances:
                raise ValueError("KMeans maximum distances are required")
            for fingerprint, distance in distances.items():
                _canonical_text(fingerprint, "KMeans threshold fingerprint")
                _distance(distance, "KMeans maximum distance")
                if distance <= 0:
                    raise ValueError("KMeans maximum distance must be positive")
            if self.gmm_probability_min is not None or self.gmm_margin_min is not None:
                raise ValueError("KMeans thresholds cannot contain GMM probabilities")
            object.__setattr__(
                self,
                "kmeans_max_standardized_distances",
                MappingProxyType(dict(sorted(distances.items()))),
            )
        else:
            raise ValueError("confidence threshold model type must be gmm or kmeans")


def _canonical_float(value: float | None) -> str | None:
    if value is None:
        return None
    normalized = Decimal(str(value)).normalize()
    return "0" if normalized.is_zero() else format(normalized, "f")


@dataclass(frozen=True)
class SelectionArtifactSnapshot:
    """Content-bound model/mapping bundle used for one selection decision."""

    model_artifact_hash: str
    mapping_artifact_hash: str
    cluster_strategy_mapping: Mapping[str, str | None]
    model_type: str
    confidence_thresholds: SelectionConfidenceThresholds
    artifact_identity: str | None = None

    def __post_init__(self) -> None:
        _sha256(self.model_artifact_hash, "model_artifact_hash")
        _sha256(self.mapping_artifact_hash, "mapping_artifact_hash")
        if self.model_type not in {"gmm", "kmeans"}:
            raise ValueError("model type must be gmm or kmeans")
        if not isinstance(self.confidence_thresholds, SelectionConfidenceThresholds):
            raise ValueError("confidence thresholds are required")
        if self.confidence_thresholds.model_type != self.model_type:
            raise ValueError("confidence threshold model type must match snapshot model type")
        mapping = dict(self.cluster_strategy_mapping)
        if not mapping:
            raise ValueError("cluster strategy mapping cannot be empty")
        for fingerprint, strategy in mapping.items():
            _canonical_text(fingerprint, "mapping fingerprint")
            if strategy is not None:
                _canonical_text(strategy, "strategy profile id")
        canonical_mapping = dict(sorted(mapping.items()))
        if (
            self.model_type == "kmeans"
            and set(self.confidence_thresholds.kmeans_max_standardized_distances)
            != set(canonical_mapping)
        ):
            raise ValueError("KMeans threshold keys must match cluster mapping keys")
        payload = {
            "model_artifact_hash": self.model_artifact_hash,
            "mapping_artifact_hash": self.mapping_artifact_hash,
            "cluster_strategy_mapping": canonical_mapping,
            "model_type": self.model_type,
            "confidence_thresholds": {
                "gmm_probability_min": _canonical_float(
                    self.confidence_thresholds.gmm_probability_min
                ),
                "gmm_margin_min": _canonical_float(
                    self.confidence_thresholds.gmm_margin_min
                ),
                "kmeans_max_standardized_distances": {
                    key: _canonical_float(value)
                    for key, value in self.confidence_thresholds.kmeans_max_standardized_distances.items()
                },
            },
        }
        computed = hashlib.sha256(
            json.dumps(
                payload,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if self.artifact_identity is not None:
            _sha256(self.artifact_identity, "artifact_identity")
            if self.artifact_identity != computed:
                raise ValueError("artifact identity does not match snapshot content")
        object.__setattr__(
            self, "cluster_strategy_mapping", MappingProxyType(canonical_mapping)
        )
        object.__setattr__(self, "artifact_identity", computed)

    @classmethod
    def from_mapping_artifact(
        cls,
        artifact: object,
        *,
        mapping_artifact_hash: str,
        model_type: str,
        confidence_thresholds: SelectionConfidenceThresholds,
        artifact_identity: str | None = None,
    ) -> "SelectionArtifactSnapshot":
        """Build a snapshot from a mapping artifact without infrastructure coupling."""
        try:
            model_hash = artifact.regime_model_artifact_hash
            entries = artifact.entries
            mapping = {
                fingerprint: entry.strategy_profile_id
                for fingerprint, entry in entries.items()
            }
        except (AttributeError, TypeError) as error:
            raise ValueError("mapping artifact is incompatible with selection") from error
        return cls(
            model_artifact_hash=model_hash,
            mapping_artifact_hash=mapping_artifact_hash,
            cluster_strategy_mapping=mapping,
            model_type=model_type,
            confidence_thresholds=confidence_thresholds,
            artifact_identity=artifact_identity,
        )


@dataclass(frozen=True)
class RegimeSelectionState:
    """Persisted selector state; artifact_version is a bundle content identity."""

    symbol: str
    artifact_version: str
    current_cluster_fingerprint: str | None
    active_strategy_profile_id: str | None
    pending_cluster_fingerprint: str | None
    pending_confirmation_count: int
    consecutive_low_confidence_count: int
    new_entries_enabled: bool
    last_boundary_at: datetime
    state_version: int
    pending_artifact_version: str | None = None

    def __post_init__(self) -> None:
        symbol = _canonical_text(self.symbol, "symbol")
        if symbol != symbol.upper():
            raise ValueError("symbol must be canonical uppercase")
        _sha256(self.artifact_version, "artifact_version")
        _optional_text(self.current_cluster_fingerprint, "current_cluster_fingerprint")
        _optional_text(self.active_strategy_profile_id, "active_strategy_profile_id")
        _optional_text(self.pending_cluster_fingerprint, "pending_cluster_fingerprint")
        if self.pending_artifact_version is not None:
            _sha256(self.pending_artifact_version, "pending_artifact_version")
        _nonnegative_integer(self.pending_confirmation_count, "pending_confirmation_count")
        _nonnegative_integer(
            self.consecutive_low_confidence_count,
            "consecutive_low_confidence_count",
        )
        _nonnegative_integer(self.state_version, "state_version")
        if type(self.new_entries_enabled) is not bool:
            raise ValueError("new_entries_enabled must be a strict boolean")
        if not isinstance(self.last_boundary_at, datetime) or not is_regime_boundary(
            self.last_boundary_at
        ):
            raise ValueError("last_boundary_at must be a four-hour UTC boundary")

        has_pending = self.pending_confirmation_count > 0
        if has_pending != (self.pending_cluster_fingerprint is not None):
            raise ValueError("pending count and cluster fingerprint must be consistent")
        if self.pending_confirmation_count > 1:
            raise ValueError("only one uncommitted confirmation may be persisted")
        if (
            self.pending_artifact_version is not None
            and self.pending_artifact_version == self.artifact_version
        ):
            raise ValueError("pending artifact must differ from the committed artifact")
        if self.pending_artifact_version is not None and not has_pending:
            raise ValueError("pending artifact requires a pending confirmation")
        if self.pending_artifact_version is not None and self.new_entries_enabled:
            raise ValueError("pending artifact replacement must suspend new entries")
        if self.consecutive_low_confidence_count and has_pending:
            raise ValueError("low confidence and pending confirmation cannot coexist")
        if self.consecutive_low_confidence_count > 2:
            raise ValueError("low confidence count cannot exceed two")
        if self.consecutive_low_confidence_count and self.new_entries_enabled:
            raise ValueError("low confidence must suspend new entries")
        if (
            self.consecutive_low_confidence_count == 2
            and self.active_strategy_profile_id is not None
        ):
            raise ValueError("two low-confidence observations must commit cash")
        if self.current_cluster_fingerprint is None and (
            self.active_strategy_profile_id is not None or self.new_entries_enabled
        ):
            raise ValueError("an active selection requires a current cluster")
        if self.active_strategy_profile_id is None and self.new_entries_enabled:
            raise ValueError("cash cannot enable new entries")


@dataclass(frozen=True)
class SelectStrategyResult:
    expected_state_version: int
    state: RegimeSelectionState
    events: tuple[SelectionEventType, ...]
    evaluated_artifact_identity: str
    selection_input_hash: str

    def __post_init__(self) -> None:
        expected = _nonnegative_integer(
            self.expected_state_version, "expected_state_version"
        )
        _sha256(self.evaluated_artifact_identity, "evaluated_artifact_identity")
        _sha256(self.selection_input_hash, "selection_input_hash")
        if self.state.state_version != expected + 1:
            raise ValueError("proposed state version must increment expected state version")
        events = tuple(self.events)
        if not events or any(not isinstance(event, SelectionEventType) for event in events):
            raise ValueError("selection events must be nonempty and known")
        if len(set(events)) != len(events):
            raise ValueError("selection events must be unique")
        if SelectionEventType.CLASSIFICATION in events and len(events) != 1:
            raise ValueError("classification cannot accompany a material event")
        if SelectionEventType.ENTRY_SUSPENDED in events and len(events) != 1:
            raise ValueError("entry suspension must be a standalone event")
        material_order = (
            SelectionEventType.ARTIFACT_REPLACED,
            SelectionEventType.CLUSTER_TRANSITION,
            SelectionEventType.STRATEGY_TRANSITION,
            SelectionEventType.CASH_TRANSITION,
        )
        if all(event in material_order for event in events):
            positions = tuple(material_order.index(event) for event in events)
            if positions != tuple(sorted(positions)):
                raise ValueError("selection events must use deterministic order")
            if (
                SelectionEventType.STRATEGY_TRANSITION in events
                and SelectionEventType.CASH_TRANSITION in events
            ):
                raise ValueError("strategy and cash transitions are mutually exclusive")
        object.__setattr__(self, "events", events)


__all__ = [
    "RegimeSelectionState",
    "SelectionArtifactSnapshot",
    "SelectionConfidenceThresholds",
    "SelectStrategyResult",
    "SelectionEventType",
]
