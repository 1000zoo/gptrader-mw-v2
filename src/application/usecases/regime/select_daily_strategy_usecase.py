"""Research-only daily selector with immediate, fail-closed transitions."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from types import MappingProxyType
from typing import Mapping, Protocol

from scipy.stats import chi2

from src.application.services.three_day_chart_feature_extractor import (
    extract_three_day_chart_feature_vector,
)
from src.domain.market.candle import Candle
from src.domain.regime.daily_mapping import (
    DailyStrategyMappingArtifact,
    DailyStrategyMappingEntry,
    daily_mapping_artifact_hash,
)
from src.domain.regime.model import ClusterAssignment
from src.domain.regime.selection import (
    RegimeSelectionState,
    SelectionArtifactSnapshot,
    SelectionConfidenceThresholds,
    SelectionEventType,
    SelectStrategyResult,
)
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)
from src.domain.regime.three_day_daily_profile import (
    PROFILE_ID,
    ThreeDayDailyResearchProfile,
)


class ThreeDayAssignmentArtifactPort(Protocol):
    artifact_hash: str
    symbol: str
    profile_id: str
    feature_schema_version: str
    component_fingerprints: tuple[str, ...]
    feature_names: tuple[str, ...]
    assignment_confidence_policy: str
    model_gates: Mapping[str, object]

    def assign(self, vector: object) -> ClusterAssignment: ...


def _canonical_midnight(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is timezone.utc
        and value.hour == value.minute == value.second == value.microsecond == 0
    )


def _sha256(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase SHA256 hash")
    return value


@dataclass(frozen=True)
class DailySelectStrategyCommand:
    previous_state: RegimeSelectionState | None
    symbol: str
    boundary_at: datetime
    model_artifact: ThreeDayAssignmentArtifactPort
    mapping_artifact: DailyStrategyMappingArtifact
    candles: tuple[Candle, ...]
    _input_hash: str = field(init=False, repr=False)
    _model_artifact_hash: str = field(init=False, repr=False)
    _model_symbol: object = field(init=False, repr=False)
    _model_profile_id: object = field(init=False, repr=False)
    _model_feature_schema_version: object = field(init=False, repr=False)
    _model_component_fingerprints: tuple[object, ...] = field(init=False, repr=False)
    _model_feature_names: tuple[object, ...] = field(init=False, repr=False)
    _model_assignment_confidence_policy: object = field(init=False, repr=False)
    _model_gates: Mapping[str, object] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.symbol, str)
            or not self.symbol
            or self.symbol != self.symbol.strip().upper()
        ):
            raise ValueError("symbol must be canonical uppercase")
        if not _canonical_midnight(self.boundary_at):
            raise ValueError("boundary_at must be canonical midnight UTC")
        if not isinstance(self.mapping_artifact, DailyStrategyMappingArtifact):
            raise ValueError("mapping_artifact must be a DailyStrategyMappingArtifact")
        if not isinstance(self.candles, tuple) or any(
            not isinstance(candle, Candle) for candle in self.candles
        ):
            raise ValueError("candles must be an immutable tuple of Candle values")
        try:
            model_hash = _sha256(self.model_artifact.artifact_hash, "model artifact hash")
        except AttributeError as error:
            raise ValueError("model artifact must expose an immutable assignment snapshot") from error
        try:
            component_fingerprints = tuple(self.model_artifact.component_fingerprints)
        except (AttributeError, TypeError):
            component_fingerprints = ()
        try:
            feature_names = tuple(self.model_artifact.feature_names)
        except (AttributeError, TypeError):
            feature_names = ()
        try:
            model_gates = MappingProxyType(dict(self.model_artifact.model_gates))
        except (AttributeError, TypeError, ValueError):
            model_gates = MappingProxyType({})
        object.__setattr__(self, "_model_artifact_hash", model_hash)
        object.__setattr__(
            self, "_model_symbol", getattr(self.model_artifact, "symbol", None)
        )
        object.__setattr__(
            self, "_model_profile_id", getattr(self.model_artifact, "profile_id", None)
        )
        object.__setattr__(
            self,
            "_model_feature_schema_version",
            getattr(self.model_artifact, "feature_schema_version", None),
        )
        object.__setattr__(self, "_model_component_fingerprints", component_fingerprints)
        object.__setattr__(self, "_model_feature_names", feature_names)
        object.__setattr__(
            self,
            "_model_assignment_confidence_policy",
            getattr(self.model_artifact, "assignment_confidence_policy", None),
        )
        object.__setattr__(self, "_model_gates", model_gates)
        previous = self.previous_state
        if previous is not None:
            if not isinstance(previous, RegimeSelectionState):
                raise ValueError("previous_state must be a RegimeSelectionState")
            if previous.symbol != self.symbol:
                raise ValueError("previous state symbol must match command symbol")
            if self.boundary_at < previous.last_boundary_at:
                raise ValueError("boundary_at cannot precede the previous boundary")
        payload = {
            "contract": "daily-immediate-selection-v1",
            "symbol": self.symbol,
            "boundary_at": self.boundary_at.isoformat(),
            "model_artifact_hash": model_hash,
            "mapping_artifact_hash": daily_mapping_artifact_hash(self.mapping_artifact),
            "candles": [
                {
                    "symbol": candle.symbol.pair,
                    "timeframe": candle.timeframe.label,
                    "opened_at": candle.opened_at.isoformat(),
                    "closed_at": candle.closed_at.isoformat(),
                    "open": str(candle.open_price),
                    "high": str(candle.high_price),
                    "low": str(candle.low_price),
                    "close": str(candle.close_price),
                    "volume": str(candle.volume),
                }
                for candle in self.candles
            ],
        }
        encoded = json.dumps(
            payload, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        object.__setattr__(self, "_input_hash", hashlib.sha256(encoded).hexdigest())

    @property
    def artifact_snapshot(self) -> SelectionArtifactSnapshot:
        """Stable scheduler coordinate; compatibility is evaluated fail-closed."""
        return _selection_snapshot(self)

    @property
    def selection_input_hash(self) -> str:
        return self._input_hash


@dataclass(frozen=True)
class DailySelectionAudit:
    status: str
    reason: str
    boundary_at: datetime
    model_artifact_hash: str
    mapping_artifact_hash: str
    profile_id: str
    profile_hash: str
    component_fingerprint: str | None
    dominant_probability: float | None
    probability_margin: float | None
    distance: float | None
    candidate_id: str | None
    candidate_definition_hash: str | None
    previous_component_fingerprint: str | None
    previous_candidate_id: str | None
    selection_input_hash: str

    def __post_init__(self) -> None:
        if self.status not in {"selected", "cash", "fail_closed"}:
            raise ValueError("daily selection audit status is invalid")
        if not self.reason or self.reason != self.reason.strip():
            raise ValueError("daily selection audit reason is required")
        if not _canonical_midnight(self.boundary_at):
            raise ValueError("daily selection audit boundary must be canonical midnight UTC")
        for value, name in (
            (self.model_artifact_hash, "model artifact hash"),
            (self.mapping_artifact_hash, "mapping artifact hash"),
            (self.profile_hash, "profile hash"),
            (self.selection_input_hash, "selection input hash"),
        ):
            _sha256(value, name)


@dataclass(frozen=True)
class DailySelectStrategyResult:
    base_result: SelectStrategyResult
    audit: DailySelectionAudit

    def __post_init__(self) -> None:
        if not isinstance(self.base_result, SelectStrategyResult):
            raise ValueError("base_result must be a SelectStrategyResult")
        if not isinstance(self.audit, DailySelectionAudit):
            raise ValueError("audit must be a DailySelectionAudit")
        if self.audit.selection_input_hash != self.base_result.selection_input_hash:
            raise ValueError("audit must bind the persisted selection input hash")

    @property
    def expected_state_version(self) -> int:
        return self.base_result.expected_state_version

    @property
    def state(self) -> RegimeSelectionState:
        return self.base_result.state

    @property
    def events(self) -> tuple[SelectionEventType, ...]:
        return self.base_result.events

    @property
    def evaluated_artifact_identity(self) -> str:
        return self.base_result.evaluated_artifact_identity

    @property
    def selection_input_hash(self) -> str:
        return self.base_result.selection_input_hash


class SelectDailyStrategyUseCase:
    def execute(self, command: DailySelectStrategyCommand) -> DailySelectStrategyResult:
        if not isinstance(command, DailySelectStrategyCommand):
            raise ValueError("command must be a DailySelectStrategyCommand")
        if (
            command.previous_state is not None
            and command.boundary_at == command.previous_state.last_boundary_at
        ):
            raise ValueError("equal boundary requires scheduler retry preflight")

        model = command.model_artifact
        mapping = command.mapping_artifact
        snapshot = _selection_snapshot(command)
        mapping_hash = daily_mapping_artifact_hash(mapping)
        assignment = None
        status = "fail_closed"
        reason = "selection evaluation failed"
        candidate_id = None
        candidate_hash = None

        compatibility_reason = _compatibility_reason(command)
        if compatibility_reason is not None:
            reason = compatibility_reason
        else:
            try:
                _validate_raw_history(command)
                vector = extract_three_day_chart_feature_vector(
                    command.candles, command.boundary_at
                )
            except (TypeError, ValueError, ArithmeticError) as error:
                reason = f"three-day history invalid: {error}"
            else:
                try:
                    assigned = model.assign(vector)
                    distance = getattr(assigned, "distance", None)
                    if distance is None:
                        raise ValueError("assignment distance is missing")
                    if (
                        not isinstance(distance, (int, float))
                        or isinstance(distance, bool)
                        or not math.isfinite(distance)
                    ):
                        raise ValueError("assignment distance must be finite")
                    if distance < 0:
                        raise ValueError("assignment distance must be nonnegative")
                    if not isinstance(assigned, ClusterAssignment):
                        raise ValueError("assignment artifact returned an invalid assignment")
                    assignment = assigned
                except (TypeError, ValueError, ArithmeticError) as error:
                    reason = f"model assignment failed: {error}"
                else:
                    probability_threshold = float(
                        command._model_gates["gmm_probability_threshold"]
                    )
                    margin_threshold = float(
                        command._model_gates["gmm_margin_threshold"]
                    )
                    margin = assignment.dominant_probability - assignment.second_probability
                    if (
                        assignment.dominant_probability < probability_threshold
                        or margin < margin_threshold
                    ):
                        reason = (
                            "low confidence assignment: probability or margin is below "
                            "the frozen model policy"
                        )
                    elif assignment.distance > command._model_gates["distance_threshold"]:
                        reason = "assignment distance exceeds the frozen maximum threshold"
                    elif assignment.fingerprint not in mapping.component_fingerprints:
                        reason = "unknown component fingerprint"
                    else:
                        entry = _entry_for(mapping, assignment.fingerprint)
                        if entry.decision == "cash":
                            status = "cash"
                            reason = "explicit cash mapping: " + ", ".join(entry.rejection_reasons)
                        else:
                            status = "selected"
                            candidate_id = entry.strategy_candidate_id
                            candidate_hash = mapping.candidate_hashes[candidate_id]
                            reason = "high-confidence component mapped to strategy candidate"

        current_component = (
            assignment.fingerprint
            if assignment is not None
            and assignment.fingerprint in mapping.component_fingerprints
            else None
        )
        previous = command.previous_state
        expected_version = 0 if previous is None else previous.state_version
        state = RegimeSelectionState(
            symbol=command.symbol,
            artifact_version=snapshot.artifact_identity,
            current_cluster_fingerprint=current_component,
            active_strategy_profile_id=candidate_id,
            pending_cluster_fingerprint=None,
            pending_confirmation_count=0,
            consecutive_low_confidence_count=1 if status == "fail_closed" else 0,
            new_entries_enabled=status == "selected",
            last_boundary_at=command.boundary_at,
            state_version=expected_version + 1,
            pending_artifact_version=None,
        )
        events = _events(previous, state, snapshot.artifact_identity)
        base_result = SelectStrategyResult(
            expected_state_version=expected_version,
            state=state,
            events=events,
            evaluated_artifact_identity=snapshot.artifact_identity,
            selection_input_hash=command.selection_input_hash,
        )
        audit = DailySelectionAudit(
            status=status,
            reason=reason,
            boundary_at=command.boundary_at,
            model_artifact_hash=command._model_artifact_hash,
            mapping_artifact_hash=mapping_hash,
            profile_id=str(command._model_profile_id),
            profile_hash=_profile_hash(),
            component_fingerprint=None if assignment is None else assignment.fingerprint,
            dominant_probability=(
                None if assignment is None else assignment.dominant_probability
            ),
            probability_margin=(
                None
                if assignment is None
                else assignment.dominant_probability - assignment.second_probability
            ),
            distance=None if assignment is None else assignment.distance,
            candidate_id=candidate_id,
            candidate_definition_hash=candidate_hash,
            previous_component_fingerprint=(
                None if previous is None else previous.current_cluster_fingerprint
            ),
            previous_candidate_id=(
                None if previous is None else previous.active_strategy_profile_id
            ),
            selection_input_hash=command.selection_input_hash,
        )
        return DailySelectStrategyResult(base_result, audit)


def daily_selection_command_input_hash(command: DailySelectStrategyCommand) -> str:
    if not isinstance(command, DailySelectStrategyCommand):
        raise ValueError("command must be a DailySelectStrategyCommand")
    return command.selection_input_hash


def _profile_hash() -> str:
    encoded = json.dumps(
        ThreeDayDailyResearchProfile().canonical_payload(),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _selection_snapshot(command: DailySelectStrategyCommand) -> SelectionArtifactSnapshot:
    mapping = command.mapping_artifact
    entries = {
        entry.component_fingerprint: entry.strategy_candidate_id
        for entry in mapping.entries
    }
    gates = dict(command._model_gates)
    probability = gates.get("gmm_probability_threshold", 0.65)
    margin = gates.get("gmm_margin_threshold", 0.10)
    try:
        thresholds = SelectionConfidenceThresholds(
            model_type="gmm",
            gmm_probability_min=probability,
            gmm_margin_min=margin,
        )
    except ValueError:
        thresholds = SelectionConfidenceThresholds(
            model_type="gmm", gmm_probability_min=0.65, gmm_margin_min=0.10
        )
    return SelectionArtifactSnapshot(
        model_artifact_hash=command._model_artifact_hash,
        mapping_artifact_hash=daily_mapping_artifact_hash(mapping),
        cluster_strategy_mapping=entries,
        model_type="gmm",
        confidence_thresholds=thresholds,
    )


def _compatibility_reason(command: DailySelectStrategyCommand) -> str | None:
    mapping = command.mapping_artifact
    try:
        gates = command._model_gates
        compatible = (
            command._model_symbol == command.symbol
            and command._model_profile_id == PROFILE_ID == mapping.profile_id
            and command._model_feature_schema_version
            == THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
            == mapping.feature_schema_version
            and command._model_artifact_hash == mapping.model_artifact_hash
            and tuple(sorted(command._model_component_fingerprints))
            == mapping.component_fingerprints
            and gates.get("passed") is True
            and gates.get("gmm_probability_threshold") == 0.65
            and gates.get("gmm_margin_threshold") == 0.10
            and command._model_assignment_confidence_policy
            == "gmm_top_two_posterior_and_chi_square_distance_v2"
            and gates.get("distance_threshold_policy")
            == "maximum_chi_square_995_squared_mahalanobis"
            and isinstance(gates.get("distance_threshold"), (int, float))
            and not isinstance(gates.get("distance_threshold"), bool)
            and math.isfinite(gates["distance_threshold"])
            and gates["distance_threshold"] > 0
            and math.isclose(
                gates["distance_threshold"],
                float(chi2.ppf(0.995, df=len(command._model_feature_names))),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            and gates.get("distance_result") is True
            and gates.get("maximum_distance_exceedance_rate_threshold") == 0.02
            and isinstance(gates.get("distance_exceedance_rate"), (int, float))
            and not isinstance(gates.get("distance_exceedance_rate"), bool)
            and math.isfinite(gates["distance_exceedance_rate"])
            and 0 <= gates["distance_exceedance_rate"] <= 0.02
        )
    except (AttributeError, TypeError, ValueError):
        compatible = False
    return (
        None
        if compatible
        else "model, mapping, profile, schema, or confidence policy is incompatible"
    )


def _validate_raw_history(command: DailySelectStrategyCommand) -> None:
    if len(command.candles) != 4320:
        raise ValueError("complete three-day one-minute history is required")
    if any(candle.symbol.pair != command.symbol for candle in command.candles):
        raise ValueError("history symbol does not match selection symbol")
    if any(candle.closed_at > command.boundary_at for candle in command.candles):
        raise ValueError("history contains a candle at or after the selection boundary")
    if command.candles[-1].closed_at != command.boundary_at:
        raise ValueError("last candle must close exactly at the selection boundary")


def _entry_for(
    mapping: DailyStrategyMappingArtifact, fingerprint: str
) -> DailyStrategyMappingEntry:
    return next(
        entry
        for entry in mapping.entries
        if entry.component_fingerprint == fingerprint
    )


def _events(
    previous: RegimeSelectionState | None,
    state: RegimeSelectionState,
    artifact_identity: str,
) -> tuple[SelectionEventType, ...]:
    if previous is None:
        return (SelectionEventType.CLASSIFICATION,)
    events = []
    if previous.artifact_version != artifact_identity:
        events.append(SelectionEventType.ARTIFACT_REPLACED)
    if previous.current_cluster_fingerprint != state.current_cluster_fingerprint:
        events.append(SelectionEventType.CLUSTER_TRANSITION)
    if previous.active_strategy_profile_id != state.active_strategy_profile_id:
        events.append(
            SelectionEventType.CASH_TRANSITION
            if state.active_strategy_profile_id is None
            else SelectionEventType.STRATEGY_TRANSITION
        )
    return tuple(events) or (SelectionEventType.CLASSIFICATION,)


__all__ = [
    "DailySelectStrategyCommand",
    "DailySelectStrategyResult",
    "DailySelectionAudit",
    "SelectDailyStrategyUseCase",
    "ThreeDayAssignmentArtifactPort",
    "daily_selection_command_input_hash",
]
