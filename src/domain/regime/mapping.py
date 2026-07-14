from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
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
    trades: tuple[WeeklyTradeEvidence, ...]
    candidate_hash: str
    market_context_hash: str
    data_hash: str
    feature_config_hash: str

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
        if start.weekday() != 0 or start.time() != datetime.min.time():
            raise ValueError("weekly evidence must start Monday 00:00 UTC")
        if end != start + timedelta(days=7):
            raise ValueError("weekly evidence must span exactly seven days")
        initial = _decimal(row["initial_equity"], "initial_equity")
        final = _decimal(row["final_equity"], "final_equity")
        net = _decimal(row["net_pnl"], "net_pnl")
        ratio = _decimal(row["return_ratio"], "return_ratio")
        if initial <= 0:
            raise ValueError("initial_equity must be positive")
        if final != initial + net or ratio != net / initial:
            raise ValueError("weekly evidence equity, net_pnl, and return_ratio are inconsistent")
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
        if trade_count != len(trades):
            raise ValueError("weekly evidence trade_count does not match trades")
        if abs(sum((item.net_pnl for item in trades), Decimal(0)) - net) > Decimal("1e-24"):
            raise ValueError("weekly evidence trade net_pnl does not reconcile")
        return cls(
            cluster_fingerprint=_text(row["cluster_fingerprint"], "cluster_fingerprint"),
            candidate_id=_text(row["candidate_id"], "candidate_id"),
            episode_start_at=start,
            episode_end_at=end,
            initial_equity=initial,
            final_equity=final,
            net_pnl=net,
            return_ratio=ratio,
            trades=tuple(trades),
            candidate_hash=_text(row["candidate_hash"], "candidate_hash"),
            market_context_hash=_text(row["market_context_hash"], "market_context_hash"),
            data_hash=_text(row["data_hash"], "data_hash"),
            feature_config_hash=_text(row["feature_config_hash"], "feature_config_hash"),
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

    def __post_init__(self) -> None:
        if self.block_length_weeks != 2:
            raise ValueError("bootstrap block length must be exactly two weeks")
        if not Decimal(0) < self.confidence < Decimal(1):
            raise ValueError("bootstrap confidence must be between zero and one")
        if not isinstance(self.resamples, int) or isinstance(self.resamples, bool) or self.resamples < 1:
            raise ValueError("bootstrap resamples must be positive")
        if not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool):
            raise ValueError("bootstrap random_seed must be an integer")


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
    weekly_episode_count: int
    distinct_month_count: int
    closed_trade_count: int
    observed_mean: Decimal
    corrected_lower_bound: Decimal
    eligible: bool
    metrics: Mapping[str, Decimal]
    rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.cluster_fingerprint, "cluster_fingerprint")
        _text(self.candidate_id, "candidate_id")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (self.weekly_episode_count, self.distinct_month_count, self.closed_trade_count)):
            raise ValueError("assessment counts must be nonnegative integers")
        if not self.observed_mean.is_finite() or not self.corrected_lower_bound.is_finite():
            raise ValueError("assessment returns must be finite")
        if self.eligible == bool(self.rejection_reasons):
            raise ValueError("assessment eligibility and rejection reasons are inconsistent")
        object.__setattr__(self, "metrics", _freeze_metrics(self.metrics))


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
    data_provenance_hash: str
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
        if not self.cluster_fingerprints or tuple(sorted(set(self.cluster_fingerprints))) != self.cluster_fingerprints:
            raise ValueError("cluster fingerprints must be unique, nonempty, and sorted")
        entries = dict(self.entries)
        assessments = {cluster: MappingProxyType(dict(items)) for cluster, items in self.candidate_assessments.items()}
        expected = set(self.cluster_fingerprints)
        if set(entries) != expected or set(assessments) != expected:
            raise ValueError("mapping artifact cluster coverage is inconsistent")
        for cluster in self.cluster_fingerprints:
            if entries[cluster].cluster_fingerprint != cluster or not assessments[cluster]:
                raise ValueError("mapping artifact cluster keys are inconsistent")
            if any(item.cluster_fingerprint != cluster or key != item.candidate_id for key, item in assessments[cluster].items()):
                raise ValueError("candidate assessment keys are inconsistent")
        object.__setattr__(self, "entries", MappingProxyType(entries))
        object.__setattr__(self, "candidate_assessments", MappingProxyType(assessments))
