from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, localcontext
import hashlib
import json
import math
import random
from typing import Mapping, Sequence

from src.domain.regime.mapping import (
    MAPPING_METRIC_NAMES,
    STRATEGY_MAPPING_ARTIFACT_VERSION,
    BootstrapConfig,
    CandidateMappingAssessment,
    MappingThresholds,
    StrategyMappingArtifact,
    StrategyMappingEntry,
    WeeklyStrategyEvidence,
)


REJECTION_ORDER = (
    "minimum_weekly_episodes",
    "minimum_distinct_months",
    "minimum_trade_count",
    "non_positive_corrected_lower_bound",
    "cash_dominance",
)


@dataclass(frozen=True)
class BuildStrategyMappingCommand:
    evidence_rows: tuple[Mapping[str, object] | WeeklyStrategyEvidence, ...]
    regime_model_artifact_hash: str
    regime_model_fingerprint_hash: str
    candidate_definition_hash: str | None = None
    candidate_universe_hash: str | None = None
    data_provenance_hash: str | None = None
    confidence: Decimal = Decimal("0.95")
    bootstrap_resamples: int = 2000
    random_seed: int = 20260714


@dataclass(frozen=True)
class BuildStrategyMappingResult:
    artifact: StrategyMappingArtifact


class BuildStrategyMappingUseCase:
    def execute(self, command: BuildStrategyMappingCommand) -> BuildStrategyMappingResult:
        evidence = tuple(
            row if isinstance(row, WeeklyStrategyEvidence) else WeeklyStrategyEvidence.from_row(row)
            for row in command.evidence_rows
        )
        if not evidence:
            raise ValueError("at least one weekly evidence row is required")
        grouped, candidate_hashes, episode_provenance, feature_hash = _validate_grid(evidence)
        candidate_ids = tuple(sorted(candidate_hashes))
        definition_hash = _hash({"candidate_hashes": candidate_hashes})
        universe_hash = _hash({"candidate_ids": candidate_ids})
        provenance_hash = _hash({"feature_config_hash": feature_hash, "episodes": episode_provenance})
        _match_optional(command.candidate_definition_hash, definition_hash, "candidate definition hash")
        _match_optional(command.candidate_universe_hash, universe_hash, "candidate universe hash")
        _match_optional(command.data_provenance_hash, provenance_hash, "data provenance hash")
        bootstrap = BootstrapConfig(confidence=command.confidence, resamples=command.bootstrap_resamples, random_seed=command.random_seed)
        thresholds = MappingThresholds()
        entries: dict[str, StrategyMappingEntry] = {}
        all_assessments: dict[str, dict[str, CandidateMappingAssessment]] = {}
        for cluster in sorted(grouped):
            by_candidate = grouped[cluster]
            returns = {candidate: tuple(row.return_ratio for row in rows) for candidate, rows in by_candidate.items()}
            lcbs = _family_corrected_lower_bounds(returns, confidence=bootstrap.confidence, random_seed=bootstrap.random_seed, resamples=bootstrap.resamples)
            assessments: dict[str, CandidateMappingAssessment] = {}
            for candidate in sorted(by_candidate):
                rows = by_candidate[candidate]
                metrics = _metrics(rows)
                episode_count = len(rows)
                months = len({(row.episode_start_at.year, row.episode_start_at.month) for row in rows})
                trades = sum(len(row.trades) for row in rows)
                reasons = tuple(reason for reason, applies in (
                    ("minimum_weekly_episodes", episode_count < thresholds.minimum_weekly_episodes),
                    ("minimum_distinct_months", months < thresholds.minimum_distinct_months),
                    ("minimum_trade_count", trades < thresholds.minimum_trade_count),
                    ("non_positive_corrected_lower_bound", lcbs[candidate] <= 0),
                    ("cash_dominance", metrics["mean_weekly_return"] <= 0),
                ) if applies)
                assessments[candidate] = CandidateMappingAssessment(
                    cluster_fingerprint=cluster, candidate_id=candidate,
                    weekly_episode_count=episode_count, distinct_month_count=months,
                    closed_trade_count=trades, observed_mean=metrics["mean_weekly_return"],
                    corrected_lower_bound=lcbs[candidate], eligible=not reasons,
                    metrics=metrics, rejection_reasons=reasons,
                )
            all_assessments[cluster] = assessments
            eligible = [item for item in assessments.values() if item.eligible]
            if eligible:
                winner = min(eligible, key=lambda item: (-item.corrected_lower_bound, -item.metrics["median_weekly_return"], -item.metrics["mean_weekly_return"], item.candidate_id))
                entries[cluster] = StrategyMappingEntry(
                    cluster_fingerprint=cluster, strategy_profile_id=winner.candidate_id,
                    decision="strategy", weekly_episode_count=winner.weekly_episode_count,
                    distinct_month_count=winner.distinct_month_count, closed_trade_count=winner.closed_trade_count,
                    corrected_lower_bound=winner.corrected_lower_bound, metrics=winner.metrics,
                )
            else:
                first = next(iter(assessments.values()))
                reasons = tuple(reason for reason in REJECTION_ORDER if any(reason in item.rejection_reasons for item in assessments.values()))
                entries[cluster] = StrategyMappingEntry(
                    cluster_fingerprint=cluster, strategy_profile_id=None, decision="cash",
                    weekly_episode_count=first.weekly_episode_count, distinct_month_count=first.distinct_month_count,
                    closed_trade_count=0, corrected_lower_bound=Decimal(0), metrics=_zero_metrics(),
                    rejection_reasons=reasons,
                )
        artifact = StrategyMappingArtifact(
            artifact_version=STRATEGY_MAPPING_ARTIFACT_VERSION,
            regime_model_artifact_hash=command.regime_model_artifact_hash,
            regime_model_fingerprint_hash=command.regime_model_fingerprint_hash,
            candidate_definition_hash=definition_hash, candidate_universe_hash=universe_hash,
            data_provenance_hash=provenance_hash, cluster_fingerprints=tuple(sorted(entries)),
            entries=entries, candidate_assessments=all_assessments,
            thresholds=thresholds, bootstrap=bootstrap,
        )
        return BuildStrategyMappingResult(artifact)


def corrected_lower_bound(
    weekly_returns: Sequence[Decimal], *, random_seed: int = 20260714,
    resamples: int = 2000, confidence: Decimal = Decimal("0.95"),
) -> Decimal:
    return _family_corrected_lower_bounds(
        {"candidate": tuple(weekly_returns)}, random_seed=random_seed,
        resamples=resamples, confidence=confidence,
    )["candidate"]


def _family_corrected_lower_bounds(
    returns_by_candidate: Mapping[str, Sequence[Decimal]], *,
    random_seed: int, resamples: int, confidence: Decimal = Decimal("0.95"),
) -> dict[str, Decimal]:
    candidates = tuple(sorted(returns_by_candidate))
    if not candidates:
        raise ValueError("bootstrap requires candidates")
    values = {candidate: tuple(returns_by_candidate[candidate]) for candidate in candidates}
    n = len(values[candidates[0]])
    if n < 2 or any(len(items) != n for items in values.values()):
        raise ValueError("moving-block bootstrap requires aligned candidates and at least two weeks")
    if any(not isinstance(value, Decimal) or not value.is_finite() for items in values.values() for value in items):
        raise ValueError("bootstrap returns must be finite Decimals")
    if resamples < 1 or not Decimal(0) < confidence < Decimal(1):
        raise ValueError("invalid bootstrap configuration")
    means = {candidate: sum(values[candidate], Decimal(0)) / Decimal(n) for candidate in candidates}
    rng = random.Random(random_seed)
    family_statistics: list[Decimal] = []
    blocks_needed = math.ceil(n / 2)
    for _ in range(resamples):
        starts = tuple(rng.randrange(n - 1) for _ in range(blocks_needed))
        maximum: Decimal | None = None
        for candidate in candidates:
            sample = tuple(value for start in starts for value in values[candidate][start:start + 2])[:n]
            centered = sum(sample, Decimal(0)) / Decimal(n) - means[candidate]
            maximum = centered if maximum is None or centered > maximum else maximum
        family_statistics.append(maximum if maximum is not None else Decimal(0))
    ordered = sorted(family_statistics)
    rank = max(1, int((confidence * Decimal(resamples)).to_integral_value(rounding=ROUND_CEILING)))
    critical = ordered[rank - 1]
    return {candidate: means[candidate] - critical for candidate in candidates}


def _validate_grid(evidence: tuple[WeeklyStrategyEvidence, ...]):
    seen: set[tuple[str, str, object]] = set()
    grouped: dict[str, dict[str, list[WeeklyStrategyEvidence]]] = {}
    candidate_hashes: dict[str, str] = {}
    provenance: dict[str, tuple[str, str]] = {}
    feature_hashes = {row.feature_config_hash for row in evidence}
    if len(feature_hashes) != 1:
        raise ValueError("feature config hash mismatch")
    for row in evidence:
        key = (row.cluster_fingerprint, row.candidate_id, row.episode_start_at)
        if key in seen:
            raise ValueError("duplicate candidate/episode evidence")
        seen.add(key)
        previous_hash = candidate_hashes.setdefault(row.candidate_id, row.candidate_hash)
        if previous_hash != row.candidate_hash:
            raise ValueError("candidate definition hash mismatch")
        episode_key = row.episode_start_at.isoformat()
        pair = (row.market_context_hash, row.data_hash)
        previous_pair = provenance.setdefault(episode_key, pair)
        if previous_pair != pair:
            raise ValueError("data hash mismatch across candidates")
        grouped.setdefault(row.cluster_fingerprint, {}).setdefault(row.candidate_id, []).append(row)
    global_episodes = sorted({row.episode_start_at: row.episode_end_at for row in evidence}.items())
    if any(left_end != right_start for (_, left_end), (right_start, _) in zip(global_episodes, global_episodes[1:])):
        raise ValueError("weekly evidence timeline must be consecutive and non-overlapping")
    expected_candidates = set(candidate_hashes)
    for cluster, by_candidate in grouped.items():
        if set(by_candidate) != expected_candidates:
            raise ValueError("evidence grid is not rectangular across clusters")
        expected_episodes = None
        for candidate, rows in by_candidate.items():
            rows.sort(key=lambda item: item.episode_start_at)
            episodes = tuple(row.episode_start_at for row in rows)
            if expected_episodes is None:
                expected_episodes = episodes
            elif episodes != expected_episodes:
                raise ValueError("evidence grid is not rectangular")
            if any(left.episode_end_at > right.episode_start_at for left, right in zip(rows, rows[1:])):
                raise ValueError("weekly episodes must be non-overlapping")
    ordered = {cluster: {candidate: tuple(rows) for candidate, rows in sorted(items.items())} for cluster, items in sorted(grouped.items())}
    return ordered, dict(sorted(candidate_hashes.items())), dict(sorted(provenance.items())), next(iter(feature_hashes))


def _metrics(rows: Sequence[WeeklyStrategyEvidence]) -> Mapping[str, Decimal]:
    n = len(rows)
    if n < 2:
        raise ValueError("mapping metrics require at least two weekly episodes")
    returns = tuple(row.return_ratio for row in rows)
    ordered = sorted(returns)
    mean = sum(returns, Decimal(0)) / Decimal(n)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / Decimal(2)
    # Conservative nearest-rank lower quantile: ceil(p*n), one-based.
    q10 = ordered[max(0, math.ceil(0.1 * n) - 1)]
    blocks = tuple((Decimal(1) + left) * (Decimal(1) + right) - Decimal(1) for left, right in zip(returns, returns[1:]))
    with localcontext() as context:
        context.prec = 28
        downside = (sum((min(value, Decimal(0)) ** 2 for value in returns), Decimal(0)) / Decimal(n)).sqrt()
    tail = tuple(value for value in returns if value <= q10)
    trades = tuple(trade for row in rows for trade in row.trades)
    positive = tuple(trade.net_pnl for trade in trades if trade.net_pnl > 0)
    losses = tuple(trade.net_pnl for trade in trades if trade.net_pnl < 0)
    profit_factor = (sum(positive, Decimal(0)) / abs(sum(losses, Decimal(0))) if losses else (Decimal("Infinity") if positive else Decimal(0)))
    time_in_market = Decimal(sum(trade.holding_bars for trade in trades)) / Decimal(10080 * n)
    if time_in_market > 1:
        raise ValueError("time in market exceeds single-position capacity")
    if time_in_market == 0 and mean != 0:
        raise ValueError("nonzero return with zero exposure is inconsistent")
    positive_episode_pnl = tuple(row.net_pnl for row in rows if row.net_pnl > 0)
    best_index = max(range(n), key=lambda index: (returns[index], -index))
    metrics = {
        "mean_weekly_return": mean,
        "median_weekly_return": median,
        "conservative_10th_percentile": q10,
        "worst_14_day_block_return": min(blocks),
        "downside_deviation": downside,
        "expected_shortfall": sum(tail, Decimal(0)) / Decimal(len(tail)),
        "profit_factor": profit_factor,
        "time_in_market": time_in_market,
        "exposure_adjusted_return": mean / time_in_market if time_in_market else Decimal(0),
        "top_5_trade_pnl_share": sum(sorted(positive, reverse=True)[:5], Decimal(0)) / sum(positive, Decimal(0)) if positive else Decimal(0),
        "top_1_episode_pnl_share": max(positive_episode_pnl) / sum(positive_episode_pnl, Decimal(0)) if positive_episode_pnl else Decimal(0),
        "return_without_best_episode": sum((value for index, value in enumerate(returns) if index != best_index), Decimal(0)) / Decimal(n - 1),
    }
    return metrics


def _zero_metrics() -> Mapping[str, Decimal]:
    return {name: Decimal(0) for name in MAPPING_METRIC_NAMES}


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _match_optional(expected: str | None, actual: str, field: str) -> None:
    if expected is not None and expected != actual:
        raise ValueError(f"{field} mismatch")
