from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import re
from types import MappingProxyType
from typing import Literal, Mapping

from src.domain.regime.mapping import candidate_universe_hash
from src.domain.regime.temporal import UtcInterval
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)
from src.domain.regime.three_day_daily_profile import (
    PROFILE_ID,
    STRICT_RISK_POLICY,
    DailyRiskPolicy,
    ThreeDayDailyResearchProfile,
    ThreeDayDailyWalkForwardFold,
)


DAILY_STRATEGY_MAPPING_ARTIFACT_VERSION = "daily-strategy-mapping-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a nonempty canonical string")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA256 hash")
    return value


def _finite_decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field} must be a finite Decimal")
    return value


def _nonnegative_integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _midnight_utc(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is timezone.utc
        and value.time() == datetime.min.time()
    )


@dataclass(frozen=True)
class DailyStrategyEvidence:
    component_fingerprint: str
    candidate_id: str
    cluster_anchor_at: datetime
    feature_start_at: datetime
    feature_end_at: datetime
    outcome_start_at: datetime
    outcome_end_at: datetime
    initial_equity: Decimal
    final_equity: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    gross_return_ratio: Decimal
    net_return_ratio: Decimal
    fees: Decimal
    closed_trade_count: int
    exposure_ratio: Decimal
    turnover_ratio: Decimal
    maximum_drawdown_ratio: Decimal
    maximum_adverse_excursion_ratio: Decimal
    profit_factor: Decimal
    downside_deviation_ratio: Decimal
    expected_shortfall_10_ratio: Decimal
    median_daily_return_ratio: Decimal
    tenth_percentile_daily_return_ratio: Decimal
    worst_seven_day_return_ratio: Decimal
    return_without_best_episode_ratio: Decimal
    top_episode_profit_share: Decimal
    top_five_trade_profit_share: Decimal
    availability_status: Literal["available", "unavailable"]
    availability_reason: str | None
    candidate_hash: str
    model_artifact_hash: str
    data_hash: str
    cost_config_hash: str
    engine_config_hash: str
    trade_pnls: tuple[Decimal, ...] | None = None

    def __post_init__(self) -> None:
        _text(self.component_fingerprint, "component_fingerprint")
        _text(self.candidate_id, "candidate_id")
        timestamps = (
            self.cluster_anchor_at,
            self.feature_start_at,
            self.feature_end_at,
            self.outcome_start_at,
            self.outcome_end_at,
        )
        if any(not _midnight_utc(value) for value in timestamps):
            raise ValueError("daily evidence bounds must be canonical midnight UTC")
        if self.feature_end_at != self.cluster_anchor_at:
            raise ValueError("feature end must match the cluster anchor")
        if self.cluster_anchor_at != self.outcome_start_at:
            raise ValueError("cluster anchor must match the daily outcome start")
        if self.feature_start_at != self.feature_end_at - timedelta(days=3):
            raise ValueError("daily evidence feature interval must span exactly three days")
        if self.outcome_end_at != self.outcome_start_at + timedelta(days=1):
            raise ValueError("daily evidence outcome must span exactly one day")

        decimal_fields = (
            "initial_equity",
            "final_equity",
            "gross_pnl",
            "net_pnl",
            "gross_return_ratio",
            "net_return_ratio",
            "fees",
            "exposure_ratio",
            "turnover_ratio",
            "maximum_drawdown_ratio",
            "maximum_adverse_excursion_ratio",
            "profit_factor",
            "downside_deviation_ratio",
            "expected_shortfall_10_ratio",
            "median_daily_return_ratio",
            "tenth_percentile_daily_return_ratio",
            "worst_seven_day_return_ratio",
            "return_without_best_episode_ratio",
            "top_episode_profit_share",
            "top_five_trade_profit_share",
        )
        for field in decimal_fields:
            _finite_decimal(getattr(self, field), field)
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if self.final_equity != self.initial_equity + self.net_pnl:
            raise ValueError("final equity and net PnL are inconsistent")
        if self.gross_pnl - self.fees != self.net_pnl or self.fees < 0:
            raise ValueError("gross PnL, fees, and net PnL are inconsistent")
        if self.gross_return_ratio != self.gross_pnl / self.initial_equity:
            raise ValueError("gross return ratio is inconsistent")
        if self.net_return_ratio != self.net_pnl / self.initial_equity:
            raise ValueError("net return ratio is inconsistent")
        _nonnegative_integer(self.closed_trade_count, "closed_trade_count")
        if not Decimal(0) <= self.exposure_ratio <= Decimal(1):
            raise ValueError("exposure_ratio must be between zero and one")
        if self.turnover_ratio < 0 or self.profit_factor < 0 or self.downside_deviation_ratio < 0:
            raise ValueError("turnover, profit factor, and downside deviation must be nonnegative")
        for field in (
            "maximum_drawdown_ratio",
            "maximum_adverse_excursion_ratio",
            "top_episode_profit_share",
            "top_five_trade_profit_share",
        ):
            if not Decimal(0) <= getattr(self, field) <= Decimal(1):
                raise ValueError(f"{field} must be between zero and one")

        if self.availability_status == "available":
            if self.availability_reason is not None:
                raise ValueError("available evidence cannot contain an availability reason")
        elif self.availability_status == "unavailable":
            _text(self.availability_reason, "availability reason")
        else:
            raise ValueError("availability status must be available or unavailable")

        for field in (
            "candidate_hash",
            "model_artifact_hash",
            "data_hash",
            "cost_config_hash",
            "engine_config_hash",
        ):
            _hash(getattr(self, field), field)
        if self.trade_pnls is not None:
            trade_pnls = tuple(self.trade_pnls)
            for value in trade_pnls:
                _finite_decimal(value, "trade PnL")
            if len(trade_pnls) != self.closed_trade_count:
                raise ValueError("trade PnLs must match the closed trade count")
            if sum(trade_pnls, Decimal(0)) != self.net_pnl:
                raise ValueError("trade PnLs must reconcile to net PnL")
            object.__setattr__(self, "trade_pnls", trade_pnls)

    def canonical_payload(self) -> dict[str, object]:
        decimal_fields = (
            "initial_equity",
            "final_equity",
            "gross_pnl",
            "net_pnl",
            "gross_return_ratio",
            "net_return_ratio",
            "fees",
            "exposure_ratio",
            "turnover_ratio",
            "maximum_drawdown_ratio",
            "maximum_adverse_excursion_ratio",
            "profit_factor",
            "downside_deviation_ratio",
            "expected_shortfall_10_ratio",
            "median_daily_return_ratio",
            "tenth_percentile_daily_return_ratio",
            "worst_seven_day_return_ratio",
            "return_without_best_episode_ratio",
            "top_episode_profit_share",
            "top_five_trade_profit_share",
        )
        payload: dict[str, object] = {
            "component_fingerprint": self.component_fingerprint,
            "candidate_id": self.candidate_id,
            "cluster_anchor_at": _timestamp(self.cluster_anchor_at),
            "feature_interval": {
                "start_at": _timestamp(self.feature_start_at),
                "end_at": _timestamp(self.feature_end_at),
            },
            "outcome_interval": {
                "start_at": _timestamp(self.outcome_start_at),
                "end_at": _timestamp(self.outcome_end_at),
            },
            "closed_trade_count": self.closed_trade_count,
            "availability_status": self.availability_status,
            "availability_reason": self.availability_reason,
            "candidate_hash": self.candidate_hash,
            "model_artifact_hash": self.model_artifact_hash,
            "data_hash": self.data_hash,
            "cost_config_hash": self.cost_config_hash,
            "engine_config_hash": self.engine_config_hash,
            "trade_pnls": None
            if self.trade_pnls is None
            else [_decimal_text(value) for value in self.trade_pnls],
        }
        payload.update(
            {field: _decimal_text(getattr(self, field)) for field in decimal_fields}
        )
        return payload


@dataclass(frozen=True)
class DailyCandidateAssessment:
    component_fingerprint: str
    candidate_id: str
    candidate_hash: str
    assigned_day_count: int
    episode_count: int
    unavailable_day_count: int
    unavailable_reason_counts: tuple[tuple[str, int], ...]
    calendar_month_count: int
    closed_trade_count: int
    mean_daily_return_ratio: Decimal
    median_daily_return_ratio: Decimal
    corrected_lower_bound_ratio: Decimal
    worst_seven_day_return_ratio: Decimal
    expected_shortfall_10_ratio: Decimal
    maximum_drawdown_ratio: Decimal
    return_without_best_episode_ratio: Decimal
    top_episode_profit_share: Decimal
    top_five_trade_profit_share: Decimal
    eligible: bool
    rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.component_fingerprint, "component_fingerprint")
        _text(self.candidate_id, "candidate_id")
        _hash(self.candidate_hash, "candidate_hash")
        for field in (
            "assigned_day_count",
            "episode_count",
            "unavailable_day_count",
            "calendar_month_count",
            "closed_trade_count",
        ):
            _nonnegative_integer(getattr(self, field), field)
        if self.assigned_day_count != self.episode_count + self.unavailable_day_count:
            raise ValueError("assigned day count must equal available and unavailable days")
        unavailable_reason_counts = tuple(self.unavailable_reason_counts)
        if any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not item[0]
            or item[0] != item[0].strip()
            or not isinstance(item[1], int)
            or isinstance(item[1], bool)
            or item[1] <= 0
            for item in unavailable_reason_counts
        ):
            raise ValueError("unavailable reason counts must contain canonical reasons and positive counts")
        if unavailable_reason_counts != tuple(sorted(unavailable_reason_counts)) or len(
            {reason for reason, _ in unavailable_reason_counts}
        ) != len(unavailable_reason_counts):
            raise ValueError("unavailable reason counts must be unique and canonical sorted")
        if sum((count for _, count in unavailable_reason_counts), 0) != self.unavailable_day_count:
            raise ValueError("unavailable reason counts must sum to unavailable day count")
        object.__setattr__(self, "unavailable_reason_counts", unavailable_reason_counts)
        decimal_fields = (
            "mean_daily_return_ratio",
            "median_daily_return_ratio",
            "corrected_lower_bound_ratio",
            "worst_seven_day_return_ratio",
            "expected_shortfall_10_ratio",
            "maximum_drawdown_ratio",
            "return_without_best_episode_ratio",
            "top_episode_profit_share",
            "top_five_trade_profit_share",
        )
        for field in decimal_fields:
            _finite_decimal(getattr(self, field), field)
        for field in (
            "maximum_drawdown_ratio",
            "top_episode_profit_share",
            "top_five_trade_profit_share",
        ):
            if not Decimal(0) <= getattr(self, field) <= Decimal(1):
                raise ValueError(f"{field} must be between zero and one")
        if type(self.eligible) is not bool:
            raise ValueError("eligible must be a strict boolean")
        reasons = tuple(self.rejection_reasons)
        if any(not isinstance(reason, str) or not reason or reason != reason.strip() for reason in reasons):
            raise ValueError("rejection reasons must be canonical strings")
        if len(set(reasons)) != len(reasons):
            raise ValueError("rejection reasons must be unique")
        if self.eligible == bool(reasons):
            raise ValueError("assessment eligibility and rejection reasons are inconsistent")
        object.__setattr__(self, "rejection_reasons", reasons)


@dataclass(frozen=True)
class DailyStrategyMappingEntry:
    component_fingerprint: str
    decision: Literal["strategy", "cash"]
    strategy_candidate_id: str | None
    rejection_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.component_fingerprint, "component_fingerprint")
        reasons = tuple(self.rejection_reasons)
        if any(not isinstance(reason, str) or not reason or reason != reason.strip() for reason in reasons):
            raise ValueError("rejection reasons must be canonical strings")
        if len(set(reasons)) != len(reasons):
            raise ValueError("rejection reasons must be unique")
        if self.decision == "strategy":
            _text(self.strategy_candidate_id, "strategy_candidate_id")
            if reasons:
                raise ValueError("strategy entry cannot contain rejection reasons")
        elif self.decision == "cash":
            if self.strategy_candidate_id is not None:
                raise ValueError("cash entry cannot contain a strategy candidate")
            if not reasons:
                raise ValueError("cash entry requires at least one rejection reason")
        else:
            raise ValueError("daily mapping decision must be strategy or cash")
        object.__setattr__(self, "rejection_reasons", reasons)


@dataclass(frozen=True)
class DailyStrategyMappingArtifact:
    artifact_version: str
    profile_id: str
    feature_schema_version: str
    model_artifact_hash: str
    candidate_universe_hash: str
    candidate_ids: tuple[str, ...]
    candidate_hashes: Mapping[str, str]
    component_fingerprints: tuple[str, ...]
    entries: tuple[DailyStrategyMappingEntry, ...]
    candidate_assessments: tuple[DailyCandidateAssessment, ...]
    risk_policy: DailyRiskPolicy
    cluster_fit: UtcInterval
    mapping_fit: UtcInterval

    def __post_init__(self) -> None:
        if self.artifact_version != DAILY_STRATEGY_MAPPING_ARTIFACT_VERSION:
            raise ValueError("unsupported daily strategy mapping artifact version")
        if self.profile_id != PROFILE_ID:
            raise ValueError("daily mapping artifact profile is incompatible")
        if self.feature_schema_version != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION:
            raise ValueError("daily mapping feature schema is incompatible")
        _hash(self.model_artifact_hash, "model artifact hash")
        _hash(self.candidate_universe_hash, "candidate universe hash")

        candidate_ids = tuple(self.candidate_ids)
        if (
            not candidate_ids
            or candidate_ids != tuple(sorted(set(candidate_ids)))
            or any(_text(candidate, "candidate id") != candidate for candidate in candidate_ids)
        ):
            raise ValueError("candidate universe must be nonempty, unique, and sorted")
        if self.candidate_universe_hash != candidate_universe_hash(candidate_ids):
            raise ValueError("candidate universe hash is inconsistent")
        candidate_hashes = dict(self.candidate_hashes)
        if set(candidate_hashes) != set(candidate_ids):
            raise ValueError("candidate hashes must cover the candidate universe")
        for candidate, value in candidate_hashes.items():
            _text(candidate, "candidate id")
            _hash(value, "candidate hash")

        supplied_components = tuple(self.component_fingerprints)
        if len(supplied_components) != 4 or len(set(supplied_components)) != 4:
            raise ValueError("artifact requires exactly four unique component fingerprints")
        for component in supplied_components:
            _text(component, "component fingerprint")
        components = tuple(sorted(supplied_components))

        supplied_entries = tuple(self.entries)
        if any(not isinstance(entry, DailyStrategyMappingEntry) for entry in supplied_entries):
            raise ValueError("entries must contain daily strategy mapping entries")
        entries_by_component = {
            entry.component_fingerprint: entry for entry in supplied_entries
        }
        if (
            len(supplied_entries) != len(components)
            or len(entries_by_component) != len(supplied_entries)
            or set(entries_by_component) != set(components)
        ):
            raise ValueError("mapping entry component coverage is inconsistent")
        entries = tuple(entries_by_component[component] for component in components)
        if any(
            entry.strategy_candidate_id not in candidate_ids
            for entry in entries
            if entry.decision == "strategy"
        ):
            raise ValueError("mapping entry strategy is outside the candidate universe")

        component_order = {component: index for index, component in enumerate(components)}
        assessments = tuple(
            sorted(
                self.candidate_assessments,
                key=lambda item: (
                    component_order.get(item.component_fingerprint, len(components))
                    if isinstance(item, DailyCandidateAssessment)
                    else len(components),
                    item.candidate_id if isinstance(item, DailyCandidateAssessment) else "",
                ),
            )
        )
        if any(not isinstance(item, DailyCandidateAssessment) for item in assessments):
            raise ValueError("candidate assessments contain an invalid value")
        assessment_keys = tuple(
            (item.component_fingerprint, item.candidate_id) for item in assessments
        )
        if len(set(assessment_keys)) != len(assessment_keys):
            raise ValueError("candidate assessments must be unique per component and candidate")
        if any(
            item.component_fingerprint not in components or item.candidate_id not in candidate_ids
            for item in assessments
        ):
            raise ValueError("candidate assessment is outside the artifact universe")
        expected_assessment_keys = {
            (component, candidate)
            for component in components
            for candidate in candidate_ids
        }
        if set(assessment_keys) != expected_assessment_keys:
            raise ValueError("candidate assessment coverage is incomplete")
        if any(
            item.candidate_hash != candidate_hashes[item.candidate_id]
            for item in assessments
        ):
            raise ValueError("candidate assessment hash is inconsistent")
        assessments_by_component = {
            component: tuple(
                item for item in assessments if item.component_fingerprint == component
            )
            for component in components
        }
        for entry in entries:
            eligible_ids = {
                item.candidate_id
                for item in assessments_by_component[entry.component_fingerprint]
                if item.eligible
            }
            if entry.decision == "strategy" and entry.strategy_candidate_id not in eligible_ids:
                raise ValueError("strategy entry must reference an eligible candidate assessment")
            if entry.decision == "cash" and eligible_ids:
                raise ValueError("cash entry cannot discard an eligible candidate assessment")

        if self.risk_policy != STRICT_RISK_POLICY:
            raise ValueError("daily mapping artifact must use the frozen strict risk policy")
        default_fold = ThreeDayDailyWalkForwardFold.default()
        if self.cluster_fit != default_fold.cluster_fit:
            raise ValueError("artifact Cluster Fit interval is incompatible")
        if self.mapping_fit != default_fold.mapping_fit:
            raise ValueError("artifact Mapping Fit interval is incompatible")

        object.__setattr__(self, "candidate_ids", candidate_ids)
        object.__setattr__(self, "candidate_hashes", MappingProxyType(candidate_hashes))
        object.__setattr__(self, "component_fingerprints", components)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "candidate_assessments", assessments)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "artifact_version": self.artifact_version,
            "profile_id": self.profile_id,
            "feature_schema_version": self.feature_schema_version,
            "model_artifact_hash": self.model_artifact_hash,
            "candidate_universe_hash": self.candidate_universe_hash,
            "candidate_ids": list(self.candidate_ids),
            "candidate_hashes": dict(sorted(self.candidate_hashes.items())),
            "component_fingerprints": list(self.component_fingerprints),
            "entries": [
                {
                    "component_fingerprint": entry.component_fingerprint,
                    "decision": entry.decision,
                    "strategy_candidate_id": entry.strategy_candidate_id,
                    "rejection_reasons": list(entry.rejection_reasons),
                }
                for entry in self.entries
            ],
            "candidate_assessments": [
                {
                    "component_fingerprint": item.component_fingerprint,
                    "candidate_id": item.candidate_id,
                    "candidate_hash": item.candidate_hash,
                    "assigned_day_count": item.assigned_day_count,
                    "episode_count": item.episode_count,
                    "unavailable_day_count": item.unavailable_day_count,
                    "unavailable_reason_counts": [
                        [reason, count]
                        for reason, count in item.unavailable_reason_counts
                    ],
                    "calendar_month_count": item.calendar_month_count,
                    "closed_trade_count": item.closed_trade_count,
                    "mean_daily_return_ratio": _decimal_text(item.mean_daily_return_ratio),
                    "median_daily_return_ratio": _decimal_text(item.median_daily_return_ratio),
                    "corrected_lower_bound_ratio": _decimal_text(item.corrected_lower_bound_ratio),
                    "worst_seven_day_return_ratio": _decimal_text(item.worst_seven_day_return_ratio),
                    "expected_shortfall_10_ratio": _decimal_text(item.expected_shortfall_10_ratio),
                    "maximum_drawdown_ratio": _decimal_text(item.maximum_drawdown_ratio),
                    "return_without_best_episode_ratio": _decimal_text(item.return_without_best_episode_ratio),
                    "top_episode_profit_share": _decimal_text(item.top_episode_profit_share),
                    "top_five_trade_profit_share": _decimal_text(item.top_five_trade_profit_share),
                    "eligible": item.eligible,
                    "rejection_reasons": list(item.rejection_reasons),
                }
                for item in self.candidate_assessments
            ],
            "risk_policy": {
                key: _decimal_text(Decimal(value))
                for key, value in self.risk_policy.canonical_payload().items()
            },
            "research_profile": ThreeDayDailyResearchProfile().canonical_payload(),
            "cluster_fit": _interval_payload(self.cluster_fit),
            "mapping_fit": _interval_payload(self.mapping_fit),
        }


def daily_mapping_artifact_hash(artifact: DailyStrategyMappingArtifact) -> str:
    if not isinstance(artifact, DailyStrategyMappingArtifact):
        raise ValueError("daily mapping artifact is required")
    encoded = json.dumps(
        artifact.canonical_payload(),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def daily_strategy_evidence_hash(evidence: DailyStrategyEvidence) -> str:
    if not isinstance(evidence, DailyStrategyEvidence):
        raise ValueError("daily strategy evidence is required")
    encoded = json.dumps(
        evidence.canonical_payload(),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _decimal_text(value: Decimal) -> str:
    sign, raw_digits, exponent = value.as_tuple()
    if not any(raw_digits):
        return "0"
    digits = list(raw_digits)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        rendered = coefficient + "0" * exponent
    else:
        decimal_position = len(coefficient) + exponent
        if decimal_position > 0:
            rendered = (
                coefficient[:decimal_position]
                + "."
                + coefficient[decimal_position:]
            )
        else:
            rendered = "0." + "0" * (-decimal_position) + coefficient
    return "-" + rendered if sign else rendered


def _interval_payload(interval: UtcInterval) -> dict[str, str]:
    return {
        "start_at": _timestamp(interval.start_at),
        "end_at": _timestamp(interval.end_at),
    }


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


__all__ = [
    "DAILY_STRATEGY_MAPPING_ARTIFACT_VERSION",
    "DailyCandidateAssessment",
    "DailyStrategyEvidence",
    "DailyStrategyMappingArtifact",
    "DailyStrategyMappingEntry",
    "daily_mapping_artifact_hash",
    "daily_strategy_evidence_hash",
]
