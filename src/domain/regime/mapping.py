from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from types import MappingProxyType
from typing import Literal, Mapping


STRATEGY_MAPPING_ARTIFACT_VERSION = "strategy-mapping-v1"
MAPPING_METRIC_NAMES = (
    "mean_weekly_return",
    "median_weekly_return",
    "conservative_10th_percentile",
    "worst_14_day_block_return",
    "downside_deviation",
    "expected_shortfall",
    "profit_factor",
    "time_in_market",
    "exposure_adjusted_return",
    "top_5_trade_pnl_share",
    "top_1_episode_pnl_share",
    "return_without_best_episode",
)
MAPPING_REJECTION_ORDER = (
    "minimum_weekly_episodes",
    "minimum_distinct_months",
    "minimum_trade_count",
    "insufficient_consecutive_blocks",
    "non_positive_corrected_lower_bound",
    "cash_dominance",
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be a nonempty canonical string")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, str):
        try:
            result = Decimal(value)
        except InvalidOperation as error:
            raise ValueError(f"{field} must be a Decimal") from error
    else:
        raise ValueError(f"{field} must be a serialized Decimal")
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO UTC timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO UTC timestamp") from error
    if result.tzinfo is not timezone.utc:
        raise ValueError(f"{field} must use canonical UTC")
    return result


def _hash_text(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA256 hash")
    return value


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) or not key for key in value):
            raise ValueError("feature_provenance keys must be nonempty strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ValueError("feature_provenance must contain canonical JSON values")


@dataclass(frozen=True)
class WeeklyTradeEvidence:
    net_pnl: Decimal
    holding_bars: int

    def __post_init__(self) -> None:
        if not self.net_pnl.is_finite():
            raise ValueError("trade net_pnl must be finite")
        if not isinstance(self.holding_bars, int) or isinstance(self.holding_bars, bool) or self.holding_bars < 0:
            raise ValueError("trade holding_bars must be a nonnegative integer")


@dataclass(frozen=True)
class WeeklyStrategyEvidence:
    cluster_fingerprint: str
    candidate_id: str
    episode_start_at: datetime
    episode_end_at: datetime
    initial_equity: Decimal
    final_equity: Decimal
    net_pnl: Decimal
    return_ratio: Decimal
    trade_count: int
    trades: tuple[WeeklyTradeEvidence, ...]
    candidate_hash: str
    market_context_hash: str
    data_hash: str
    feature_cache_hash: str | None
    feature_provenance: Mapping[str, object]
    feature_config_hash: str | None

    def __post_init__(self) -> None:
        _text(self.cluster_fingerprint, "cluster_fingerprint")
        _text(self.candidate_id, "candidate_id")
        if self.episode_start_at.tzinfo is not timezone.utc or self.episode_start_at.weekday() != 0 or self.episode_start_at.time() != datetime.min.time():
            raise ValueError("episode_start_at must be canonical Monday 00:00 UTC")
        if self.episode_end_at.tzinfo is not timezone.utc or self.episode_end_at != self.episode_start_at + timedelta(days=7):
            raise ValueError("weekly evidence must span exactly seven days in canonical UTC")
        for field in ("initial_equity", "final_equity", "net_pnl", "return_ratio"):
            value = getattr(self, field)
            if not isinstance(value, Decimal) or not value.is_finite():
                raise ValueError(f"{field} must be a finite Decimal")
        if self.initial_equity <= 0 or self.final_equity != self.initial_equity + self.net_pnl or self.return_ratio != self.net_pnl / self.initial_equity:
            raise ValueError("weekly evidence equity, net_pnl, and return_ratio are inconsistent")
        trades = tuple(self.trades)
        if any(not isinstance(item, WeeklyTradeEvidence) for item in trades):
            raise ValueError("trades must contain WeeklyTradeEvidence")
        object.__setattr__(self, "trades", trades)
        if not isinstance(self.trade_count, int) or isinstance(self.trade_count, bool) or self.trade_count < 0 or self.trade_count != len(trades):
            raise ValueError("trade_count must be nonnegative and match trades")
        if abs(sum((item.net_pnl for item in trades), Decimal(0)) - self.net_pnl) > Decimal("1e-24"):
            raise ValueError("weekly evidence trade net_pnl does not reconcile")
        if sum(item.holding_bars for item in trades) > 10080:
            raise ValueError("weekly evidence holding bars exceed one-position episode capacity")
        for field in ("candidate_hash", "market_context_hash", "data_hash"):
            _hash_text(getattr(self, field), field)
        provenance = _freeze_json(dict(self.feature_provenance))
        object.__setattr__(self, "feature_provenance", provenance)
        null_identity = self.feature_cache_hash is None and self.feature_config_hash is None and not provenance
        present_identity = self.feature_cache_hash is not None and self.feature_config_hash is not None and bool(provenance)
        if not (null_identity or present_identity):
            raise ValueError("feature identity must be consistently all-null or all-present")
        if present_identity:
            _hash_text(self.feature_cache_hash, "feature_cache_hash")
            _hash_text(self.feature_config_hash, "feature_config_hash")

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "WeeklyStrategyEvidence":
        if not isinstance(row, Mapping):
            raise ValueError("weekly evidence row must be a mapping")
        required = {
            "cluster_fingerprint", "candidate_id", "episode_start_at", "episode_end_at",
            "initial_equity", "final_equity", "net_pnl", "return_ratio", "trade_count",
            "trades", "candidate_hash", "market_context_hash", "data_hash", "feature_config_hash",
        }
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"weekly evidence missing required fields: {', '.join(missing)}")
        start = _utc(row["episode_start_at"], "episode_start_at")
        end = _utc(row["episode_end_at"], "episode_end_at")
        initial = _decimal(row["initial_equity"], "initial_equity")
        final = _decimal(row["final_equity"], "final_equity")
        net = _decimal(row["net_pnl"], "net_pnl")
        ratio = _decimal(row["return_ratio"], "return_ratio")
        raw_trades = row["trades"]
        trade_count = row["trade_count"]
        if not isinstance(raw_trades, list) or not isinstance(trade_count, int) or isinstance(trade_count, bool):
            raise ValueError("weekly evidence trades and trade_count are invalid")
        trades: list[WeeklyTradeEvidence] = []
        for index, item in enumerate(raw_trades):
            if not isinstance(item, Mapping):
                raise ValueError(f"trade {index} must be a mapping")
            trades.append(WeeklyTradeEvidence(
                net_pnl=_decimal(item.get("net_pnl"), f"trade {index} net_pnl"),
                holding_bars=item.get("holding_bars"),
            ))
        return cls(
            cluster_fingerprint=_text(row["cluster_fingerprint"], "cluster_fingerprint"),
            candidate_id=_text(row["candidate_id"], "candidate_id"),
            episode_start_at=start,
            episode_end_at=end,
            initial_equity=initial,
            final_equity=final,
            net_pnl=net,
            return_ratio=ratio,
            trade_count=trade_count,
            trades=tuple(trades),
            candidate_hash=row["candidate_hash"],
            market_context_hash=row["market_context_hash"],
            data_hash=row["data_hash"],
            feature_cache_hash=row.get("feature_cache_hash"),
            feature_provenance=row.get("feature_provenance", {}),
            feature_config_hash=row["feature_config_hash"],
        )

    def validated_copy(self) -> "WeeklyStrategyEvidence":
        return type(self)(
            cluster_fingerprint=self.cluster_fingerprint, candidate_id=self.candidate_id,
            episode_start_at=self.episode_start_at, episode_end_at=self.episode_end_at,
            initial_equity=self.initial_equity, final_equity=self.final_equity,
            net_pnl=self.net_pnl, return_ratio=self.return_ratio, trade_count=self.trade_count,
            trades=tuple(self.trades), candidate_hash=self.candidate_hash,
            market_context_hash=self.market_context_hash, data_hash=self.data_hash,
            feature_cache_hash=self.feature_cache_hash,
            feature_provenance=dict(self.feature_provenance),
            feature_config_hash=self.feature_config_hash,
        )


@dataclass(frozen=True)
class MappingThresholds:
    minimum_weekly_episodes: int = 8
    minimum_distinct_months: int = 3
    minimum_trade_count: int = 30

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in (
                self.minimum_weekly_episodes,
                self.minimum_distinct_months,
                self.minimum_trade_count,
            )
        ):
            raise ValueError("mapping thresholds must be positive integers")


@dataclass(frozen=True)
class BootstrapConfig:
    block_length_weeks: int = 2
    confidence: Decimal = Decimal("0.95")
    resamples: int = 2000
    random_seed: int = 20260714
    bootstrap_missingness_policy: str = "common_uniform_rank_coupled_calendar_blocks_v1"
    insufficient_evidence_lcb_policy: str = "zero_nonselectable_v1"

    def __post_init__(self) -> None:
        if self.block_length_weeks != 2:
            raise ValueError("bootstrap block length must be exactly two weeks")
        if not Decimal(0) < self.confidence < Decimal(1):
            raise ValueError("bootstrap confidence must be between zero and one")
        if not isinstance(self.resamples, int) or isinstance(self.resamples, bool) or self.resamples < 1:
            raise ValueError("bootstrap resamples must be positive")
        if not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool):
            raise ValueError("bootstrap random_seed must be an integer")
        if self.bootstrap_missingness_policy != "common_uniform_rank_coupled_calendar_blocks_v1":
            raise ValueError("unsupported bootstrap missingness policy")
        if self.insufficient_evidence_lcb_policy != "zero_nonselectable_v1":
            raise ValueError("unsupported insufficient-evidence LCB policy")


def episode_months_touched(starts: tuple[datetime, ...]) -> frozenset[tuple[int, int]]:
    """Return calendar months intersecting exact half-open seven-day episodes."""
    months: set[tuple[int, int]] = set()
    for start in starts:
        if start.tzinfo is not timezone.utc:
            raise ValueError("effective episode starts must use canonical UTC")
        end = start + timedelta(days=7)
        cursor = datetime(start.year, start.month, 1, tzinfo=timezone.utc)
        while cursor < end:
            months.add((cursor.year, cursor.month))
            cursor = (
                datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
                if cursor.month == 12
                else datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)
            )
    return frozenset(months)


def derive_mapping_rejection_reasons(
    *,
    thresholds: MappingThresholds,
    weekly_episode_count: int,
    distinct_month_count: int,
    closed_trade_count: int,
    has_sufficient_consecutive_blocks: bool,
    corrected_lower_bound: Decimal,
    observed_mean: Decimal,
) -> tuple[str, ...]:
    """Derive the canonical eligibility audit tuple from persisted evidence."""
    if type(has_sufficient_consecutive_blocks) is not bool:
        raise ValueError("has_sufficient_consecutive_blocks must be a strict boolean")
    return tuple(
        reason
        for reason, applies in (
            ("minimum_weekly_episodes", weekly_episode_count < thresholds.minimum_weekly_episodes),
            ("minimum_distinct_months", distinct_month_count < thresholds.minimum_distinct_months),
            ("minimum_trade_count", closed_trade_count < thresholds.minimum_trade_count),
            ("insufficient_consecutive_blocks", not has_sufficient_consecutive_blocks),
            ("non_positive_corrected_lower_bound", corrected_lower_bound <= 0),
            ("cash_dominance", observed_mean <= 0),
        )
        if applies
    )


def _freeze_metrics(metrics: Mapping[str, Decimal]) -> Mapping[str, Decimal]:
    if tuple(metrics) != MAPPING_METRIC_NAMES:
        raise ValueError("mapping metrics must use the complete canonical order")
    result = dict(metrics)
    for name, value in result.items():
        if not isinstance(value, Decimal) or value.is_nan():
            raise ValueError(f"mapping metric {name} must be a non-NaN Decimal")
        if not value.is_finite() and not (name == "profit_factor" and value == Decimal("Infinity")):
            raise ValueError(f"mapping metric {name} must be finite")
    for name in ("time_in_market", "top_5_trade_pnl_share", "top_1_episode_pnl_share"):
        if not Decimal(0) <= result[name] <= Decimal(1):
            raise ValueError(f"mapping metric {name} must be between zero and one")
    return MappingProxyType(result)


@dataclass(frozen=True)
class CandidateMappingAssessment:
    cluster_fingerprint: str
    candidate_id: str
    candidate_hash: str
    weekly_episode_count: int
    distinct_month_count: int
    closed_trade_count: int
    effective_episode_starts: tuple[datetime, ...]
    observed_mean: Decimal
    corrected_lower_bound: Decimal
    has_sufficient_consecutive_blocks: bool
    eligible: bool
    metrics: Mapping[str, Decimal]
    rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.cluster_fingerprint, "cluster_fingerprint")
        _text(self.candidate_id, "candidate_id")
        _hash_text(self.candidate_hash, "candidate_hash")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (self.weekly_episode_count, self.distinct_month_count, self.closed_trade_count)):
            raise ValueError("assessment counts must be nonnegative integers")
        starts = tuple(self.effective_episode_starts)
        if starts != tuple(sorted(set(starts))) or any(
            start.tzinfo is not timezone.utc or start.weekday() != 0 or start.time() != datetime.min.time()
            for start in starts
        ):
            raise ValueError("effective episode starts must be unique sorted canonical Mondays")
        if self.weekly_episode_count != len(starts):
            raise ValueError("weekly episode count must match effective episode starts")
        if self.distinct_month_count != len(episode_months_touched(starts)):
            raise ValueError("distinct month count must match touched episode months")
        object.__setattr__(self, "effective_episode_starts", starts)
        if (
            not isinstance(self.observed_mean, Decimal)
            or not isinstance(self.corrected_lower_bound, Decimal)
            or not self.observed_mean.is_finite()
            or not self.corrected_lower_bound.is_finite()
        ):
            raise ValueError("assessment returns must be finite")
        if type(self.has_sufficient_consecutive_blocks) is not bool:
            raise ValueError("has_sufficient_consecutive_blocks must be a strict boolean")
        frozen_metrics = _freeze_metrics(self.metrics)
        if self.observed_mean != frozen_metrics["mean_weekly_return"]:
            raise ValueError("assessment observed mean must equal its mean weekly return metric")
        if self.eligible == bool(self.rejection_reasons):
            raise ValueError("assessment eligibility and rejection reasons are inconsistent")
        expected_order = tuple(reason for reason in MAPPING_REJECTION_ORDER if reason in self.rejection_reasons)
        if self.rejection_reasons != expected_order:
            raise ValueError("assessment rejection reasons must be unique, known, and ordered")
        object.__setattr__(self, "metrics", frozen_metrics)


@dataclass(frozen=True)
class StrategyMappingEntry:
    cluster_fingerprint: str
    strategy_profile_id: str | None
    decision: Literal["strategy", "cash"]
    weekly_episode_count: int
    distinct_month_count: int
    closed_trade_count: int
    corrected_lower_bound: Decimal
    metrics: Mapping[str, Decimal]
    rejection_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.cluster_fingerprint, "cluster_fingerprint")
        if self.decision == "strategy":
            _text(self.strategy_profile_id, "strategy_profile_id")
            if self.rejection_reasons:
                raise ValueError("strategy mapping cannot have rejection reasons")
        elif self.decision == "cash":
            if self.strategy_profile_id is not None:
                raise ValueError("cash mapping cannot have a strategy profile")
        else:
            raise ValueError("mapping decision must be strategy or cash")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (self.weekly_episode_count, self.distinct_month_count, self.closed_trade_count)):
            raise ValueError("mapping counts must be nonnegative integers")
        if not self.corrected_lower_bound.is_finite():
            raise ValueError("corrected lower bound must be finite")
        object.__setattr__(self, "metrics", _freeze_metrics(self.metrics))


@dataclass(frozen=True)
class StrategyMappingArtifact:
    artifact_version: str
    regime_model_artifact_hash: str
    regime_model_fingerprint_hash: str
    candidate_definition_hash: str
    candidate_universe_hash: str
    candidate_hashes: Mapping[str, str]
    data_provenance_hash: str
    common_initial_equity: Decimal
    cluster_fingerprints: tuple[str, ...]
    entries: Mapping[str, StrategyMappingEntry]
    candidate_assessments: Mapping[str, Mapping[str, CandidateMappingAssessment]]
    thresholds: MappingThresholds
    bootstrap: BootstrapConfig
    profit_factor_zero_loss_policy: str = "positive_infinity_when_profit_positive_else_zero"

    def __post_init__(self) -> None:
        if self.artifact_version != STRATEGY_MAPPING_ARTIFACT_VERSION:
            raise ValueError("unsupported strategy mapping artifact version")
        for field in ("regime_model_artifact_hash", "regime_model_fingerprint_hash", "candidate_definition_hash", "candidate_universe_hash", "data_provenance_hash"):
            _text(getattr(self, field), field)
        if self.profit_factor_zero_loss_policy != "positive_infinity_when_profit_positive_else_zero":
            raise ValueError("unsupported profit factor zero-loss policy")
        if not isinstance(self.common_initial_equity, Decimal) or not self.common_initial_equity.is_finite() or self.common_initial_equity <= 0:
            raise ValueError("common initial equity must be a finite positive Decimal")
        if not self.cluster_fingerprints or tuple(sorted(set(self.cluster_fingerprints))) != self.cluster_fingerprints:
            raise ValueError("cluster fingerprints must be unique, nonempty, and sorted")
        entries = dict(self.entries)
        assessments = {cluster: MappingProxyType(dict(items)) for cluster, items in self.candidate_assessments.items()}
        expected = set(self.cluster_fingerprints)
        if set(entries) != expected or set(assessments) != expected:
            raise ValueError("mapping artifact cluster coverage is inconsistent")
        if any(not isinstance(item, StrategyMappingEntry) for item in entries.values()):
            raise ValueError("mapping entries must contain StrategyMappingEntry values")
        candidate_hashes = dict(self.candidate_hashes)
        if not candidate_hashes or any(not isinstance(key, str) or not key for key in candidate_hashes):
            raise ValueError("candidate hashes must cover a nonempty candidate universe")
        for value in candidate_hashes.values():
            _hash_text(value, "candidate_hash")
        if self.candidate_universe_hash != _canonical_hash({"candidate_ids": tuple(sorted(candidate_hashes))}):
            raise ValueError("candidate universe hash is inconsistent")
        if self.candidate_definition_hash != _canonical_hash({"candidate_hashes": dict(sorted(candidate_hashes.items()))}):
            raise ValueError("candidate definition hash is inconsistent")
        for cluster in self.cluster_fingerprints:
            if entries[cluster].cluster_fingerprint != cluster or not assessments[cluster]:
                raise ValueError("mapping artifact cluster keys are inconsistent")
            if any(not isinstance(item, CandidateMappingAssessment) for item in assessments[cluster].values()):
                raise ValueError("candidate assessments contain an invalid value")
            if any(item.cluster_fingerprint != cluster or key != item.candidate_id for key, item in assessments[cluster].items()):
                raise ValueError("candidate assessment keys are inconsistent")
            if set(assessments[cluster]) != set(candidate_hashes):
                raise ValueError("candidate universe must be identical across clusters")
            if any(item.candidate_hash != candidate_hashes[key] for key, item in assessments[cluster].items()):
                raise ValueError("candidate assessment hash is inconsistent")
            for item in assessments[cluster].values():
                derived_reasons = derive_mapping_rejection_reasons(
                    thresholds=self.thresholds,
                    weekly_episode_count=item.weekly_episode_count,
                    distinct_month_count=item.distinct_month_count,
                    closed_trade_count=item.closed_trade_count,
                    has_sufficient_consecutive_blocks=item.has_sufficient_consecutive_blocks,
                    corrected_lower_bound=item.corrected_lower_bound,
                    observed_mean=item.observed_mean,
                )
                if item.rejection_reasons != derived_reasons or item.eligible != (not derived_reasons):
                    raise ValueError("candidate assessment does not match derived eligibility")
            eligible = [item for item in assessments[cluster].values() if item.eligible]
            entry = entries[cluster]
            if eligible:
                winner = min(eligible, key=lambda item: (-item.corrected_lower_bound, -item.metrics["median_weekly_return"], -item.metrics["mean_weekly_return"], item.candidate_id))
                if not (
                    entry.decision == "strategy" and entry.strategy_profile_id == winner.candidate_id
                    and entry.weekly_episode_count == winner.weekly_episode_count
                    and entry.distinct_month_count == winner.distinct_month_count
                    and entry.closed_trade_count == winner.closed_trade_count
                    and entry.corrected_lower_bound == winner.corrected_lower_bound
                    and entry.metrics == winner.metrics and not entry.rejection_reasons
                ):
                    raise ValueError("strategy entry does not match the deterministic eligible winner")
            else:
                reasons = tuple(reason for reason in MAPPING_REJECTION_ORDER if any(reason in item.rejection_reasons for item in assessments[cluster].values()))
                cluster_starts = tuple(sorted({start for item in assessments[cluster].values() for start in item.effective_episode_starts}))
                if not (
                    entry.decision == "cash" and entry.strategy_profile_id is None
                    and entry.weekly_episode_count == len(cluster_starts)
                    and entry.distinct_month_count == len(episode_months_touched(cluster_starts))
                    and entry.closed_trade_count == 0 and entry.corrected_lower_bound == 0
                    and entry.metrics == {name: Decimal(0) for name in MAPPING_METRIC_NAMES}
                    and entry.rejection_reasons == reasons
                ):
                    raise ValueError("cash entry does not match audited candidate rejections")
        object.__setattr__(self, "entries", MappingProxyType(entries))
        object.__setattr__(self, "candidate_assessments", MappingProxyType(assessments))
        object.__setattr__(self, "candidate_hashes", MappingProxyType(candidate_hashes))


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()
