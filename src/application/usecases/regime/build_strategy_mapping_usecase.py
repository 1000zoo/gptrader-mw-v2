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
    MAPPING_REJECTION_ORDER,
    STRATEGY_MAPPING_ARTIFACT_VERSION,
    BootstrapConfig,
    CandidateMappingAssessment,
    MappingThresholds,
    StrategyMappingArtifact,
    StrategyMappingEntry,
    WeeklyStrategyEvidence,
    derive_mapping_rejection_reasons,
    episode_months_touched,
    has_sufficient_calendar_block_coverage,
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
            row.validated_copy() if isinstance(row, WeeklyStrategyEvidence) else WeeklyStrategyEvidence.from_row(row)
            for row in command.evidence_rows
        )
        if not evidence:
            raise ValueError("at least one weekly evidence row is required")
        grouped, candidate_hashes, episode_provenance, feature_identity, common_initial_equity = _validate_grid(evidence)
        candidate_ids = tuple(sorted(candidate_hashes))
        definition_hash = _hash({"candidate_hashes": candidate_hashes})
        universe_hash = _hash({"candidate_ids": candidate_ids})
        provenance_hash = _hash({"feature_identity": feature_identity, "episodes": episode_provenance})
        _match_optional(command.candidate_definition_hash, definition_hash, "candidate definition hash")
        _match_optional(command.candidate_universe_hash, universe_hash, "candidate universe hash")
        _match_optional(command.data_provenance_hash, provenance_hash, "data provenance hash")
        bootstrap = BootstrapConfig(confidence=command.confidence, resamples=command.bootstrap_resamples, random_seed=command.random_seed)
        thresholds = MappingThresholds()
        entries: dict[str, StrategyMappingEntry] = {}
        all_assessments: dict[str, dict[str, CandidateMappingAssessment]] = {}
        for cluster in sorted(grouped):
            by_candidate = {
                candidate: tuple(grouped[cluster].get(candidate, ()))
                for candidate in candidate_ids
            }
            valid_starts_by_candidate = {
                candidate: _calendar_block_starts(rows)
                for candidate, rows in by_candidate.items()
            }
            sufficient_by_candidate = {
                candidate: has_sufficient_calendar_block_coverage(
                    tuple(row.episode_start_at for row in rows)
                )
                for candidate, rows in by_candidate.items()
            }
            pre_statistical = {
                candidate: rows
                for candidate, rows in by_candidate.items()
                if len(rows) >= thresholds.minimum_weekly_episodes
                and len(episode_months_touched(tuple(row.episode_start_at for row in rows))) >= thresholds.minimum_distinct_months
                and sum(len(row.trades) for row in rows) >= thresholds.minimum_trade_count
                and sufficient_by_candidate[candidate]
            }
            lcbs = {candidate: Decimal(0) for candidate in candidate_ids}
            if pre_statistical:
                lcbs.update(_rank_coupled_calendar_family_corrected_lower_bounds(
                    pre_statistical,
                    valid_starts_by_candidate={candidate: valid_starts_by_candidate[candidate] for candidate in pre_statistical},
                    confidence=bootstrap.confidence, random_seed=bootstrap.random_seed,
                    resamples=bootstrap.resamples,
                ))
            assessments: dict[str, CandidateMappingAssessment] = {}
            for candidate in sorted(by_candidate):
                rows = by_candidate[candidate]
                valid_starts = valid_starts_by_candidate[candidate]
                sufficient_blocks = sufficient_by_candidate[candidate]
                metrics = _metrics(rows, valid_block_starts=valid_starts) if rows else _zero_metrics()
                episode_count = len(rows)
                effective_starts = tuple(row.episode_start_at for row in rows)
                months = len(episode_months_touched(effective_starts))
                trades = sum(len(row.trades) for row in rows)
                reasons = derive_mapping_rejection_reasons(
                    thresholds=thresholds,
                    weekly_episode_count=episode_count,
                    distinct_month_count=months,
                    closed_trade_count=trades,
                    has_sufficient_consecutive_blocks=sufficient_blocks,
                    corrected_lower_bound=lcbs[candidate],
                    observed_mean=metrics["mean_weekly_return"],
                )
                assessments[candidate] = CandidateMappingAssessment(
                    cluster_fingerprint=cluster, candidate_id=candidate,
                    candidate_hash=candidate_hashes[candidate],
                    weekly_episode_count=episode_count, distinct_month_count=months,
                    closed_trade_count=trades, effective_episode_starts=effective_starts,
                    observed_mean=metrics["mean_weekly_return"],
                    corrected_lower_bound=lcbs[candidate],
                    has_sufficient_consecutive_blocks=sufficient_blocks,
                    eligible=not reasons,
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
                reasons = tuple(reason for reason in MAPPING_REJECTION_ORDER if any(reason in item.rejection_reasons for item in assessments.values()))
                cluster_starts = tuple(sorted({start for item in assessments.values() for start in item.effective_episode_starts}))
                entries[cluster] = StrategyMappingEntry(
                    cluster_fingerprint=cluster, strategy_profile_id=None, decision="cash",
                    weekly_episode_count=len(cluster_starts), distinct_month_count=len(episode_months_touched(cluster_starts)),
                    closed_trade_count=0, corrected_lower_bound=Decimal(0), metrics=_zero_metrics(),
                    rejection_reasons=reasons,
                )
        artifact = StrategyMappingArtifact(
            artifact_version=STRATEGY_MAPPING_ARTIFACT_VERSION,
            regime_model_artifact_hash=command.regime_model_artifact_hash,
            regime_model_fingerprint_hash=command.regime_model_fingerprint_hash,
            candidate_definition_hash=definition_hash, candidate_universe_hash=universe_hash,
            candidate_hashes=candidate_hashes,
            data_provenance_hash=provenance_hash, cluster_fingerprints=tuple(sorted(entries)),
            common_initial_equity=common_initial_equity,
            entries=entries, candidate_assessments=all_assessments,
            thresholds=thresholds, bootstrap=bootstrap,
        )
        return BuildStrategyMappingResult(artifact)


def corrected_lower_bound(
    weekly_returns: Sequence[Decimal], *, random_seed: int = 20260714,
    resamples: int = 2000, confidence: Decimal = Decimal("0.95"),
) -> Decimal:
    """Low-level helper for an already contiguous weekly series.

    Production mapping uses timestamp-aware rank-coupled calendar blocks.
    """
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


def _rank_coupled_calendar_family_corrected_lower_bounds(
    rows_by_candidate: Mapping[str, Sequence[WeeklyStrategyEvidence]], *,
    valid_starts_by_candidate: Mapping[str, tuple[int, ...]], random_seed: int, resamples: int,
    confidence: Decimal,
) -> dict[str, Decimal]:
    candidates = tuple(sorted(rows_by_candidate))
    if any(not valid_starts_by_candidate[candidate] for candidate in candidates):
        raise ValueError("calendar bootstrap requires true consecutive blocks")
    means = {
        candidate: sum((row.return_ratio for row in rows_by_candidate[candidate]), Decimal(0)) / Decimal(len(rows_by_candidate[candidate]))
        for candidate in candidates
    }
    rng = random.Random(random_seed)
    statistics: list[Decimal] = []
    max_blocks_needed = max(math.ceil(len(rows_by_candidate[candidate]) / 2) for candidate in candidates)
    for _ in range(resamples):
        uniforms = tuple(rng.random() for _ in range(max_blocks_needed))
        maximum: Decimal | None = None
        for candidate in candidates:
            rows = rows_by_candidate[candidate]
            n = len(rows)
            valid_starts = valid_starts_by_candidate[candidate]
            selected = _rank_coupled_selected_starts(valid_starts, uniforms, math.ceil(n / 2))
            sample = tuple(rows[index].return_ratio for start in selected for index in (start, start + 1))[:n]
            centered = sum(sample, Decimal(0)) / Decimal(n) - means[candidate]
            maximum = centered if maximum is None or centered > maximum else maximum
        statistics.append(maximum if maximum is not None else Decimal(0))
    rank = max(1, int((confidence * Decimal(resamples)).to_integral_value(rounding=ROUND_CEILING)))
    critical = sorted(statistics)[rank - 1]
    return {candidate: means[candidate] - critical for candidate in candidates}


def _rank_coupled_selected_starts(
    valid_starts: tuple[int, ...], uniforms: tuple[float, ...], blocks_needed: int
) -> tuple[int, ...]:
    return tuple(
        valid_starts[min(int(value * len(valid_starts)), len(valid_starts) - 1)]
        for value in uniforms[:blocks_needed]
    )


def _validate_grid(evidence: tuple[WeeklyStrategyEvidence, ...]):
    seen: set[tuple[str, object]] = set()
    grouped: dict[str, dict[str, list[WeeklyStrategyEvidence]]] = {}
    candidate_hashes: dict[str, str] = {}
    provenance: dict[str, tuple[str, str]] = {}
    feature_identities = {
        (row.feature_cache_hash, row.feature_config_hash, _canonical_json(row.feature_provenance))
        for row in evidence
    }
    # Cache hashes may vary by episode. Configuration/provenance identity must not.
    feature_configs = {(row.feature_config_hash, _canonical_json(row.feature_provenance)) for row in evidence}
    if len(feature_configs) != 1:
        raise ValueError("feature identity mismatch")
    initial_equities = {row.initial_equity for row in evidence}
    if len(initial_equities) != 1:
        raise ValueError("all mapping evidence must use one exact common initial equity")
    episode_clusters: dict[object, str] = {}
    for row in evidence:
        key = (row.candidate_id, row.episode_start_at)
        if key in seen:
            raise ValueError("duplicate candidate/episode evidence, including conflicting clusters")
        seen.add(key)
        previous_hash = candidate_hashes.setdefault(row.candidate_id, row.candidate_hash)
        if previous_hash != row.candidate_hash:
            raise ValueError("candidate definition hash mismatch")
        episode_key = row.episode_start_at.isoformat()
        pair = (row.market_context_hash, row.data_hash)
        previous_pair = provenance.setdefault(episode_key, pair)
        if previous_pair != pair:
            raise ValueError("data hash mismatch across candidates")
        previous_cluster = episode_clusters.setdefault(row.episode_start_at, row.cluster_fingerprint)
        if previous_cluster != row.cluster_fingerprint:
            raise ValueError("one weekly episode cannot have conflicting clusters")
        grouped.setdefault(row.cluster_fingerprint, {}).setdefault(row.candidate_id, []).append(row)
    for cluster, by_candidate in grouped.items():
        for candidate, rows in by_candidate.items():
            rows.sort(key=lambda item: item.episode_start_at)
            if any(left.episode_end_at > right.episode_start_at for left, right in zip(rows, rows[1:])):
                raise ValueError("weekly episodes must be non-overlapping")
    ordered = {cluster: {candidate: tuple(rows) for candidate, rows in sorted(items.items())} for cluster, items in sorted(grouped.items())}
    feature_identity = tuple(sorted((cache or "", config or "", payload) for cache, config, payload in feature_identities))
    return ordered, dict(sorted(candidate_hashes.items())), dict(sorted(provenance.items())), feature_identity, next(iter(initial_equities))


def _calendar_block_starts(rows: Sequence[WeeklyStrategyEvidence]) -> tuple[int, ...]:
    return tuple(index for index, (left, right) in enumerate(zip(rows, rows[1:])) if right.episode_start_at == left.episode_end_at)


def _metrics(rows: Sequence[WeeklyStrategyEvidence], *, valid_block_starts: tuple[int, ...]) -> Mapping[str, Decimal]:
    n = len(rows)
    if n < 1:
        raise ValueError("mapping metrics require weekly episodes")
    returns = tuple(row.return_ratio for row in rows)
    ordered = sorted(returns)
    mean = sum(returns, Decimal(0)) / Decimal(n)
    median = ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / Decimal(2)
    # Conservative nearest-rank lower quantile: ceil(p*n), one-based.
    q10 = ordered[max(0, math.ceil(0.1 * n) - 1)]
    blocks = tuple((Decimal(1) + returns[index]) * (Decimal(1) + returns[index + 1]) - Decimal(1) for index in valid_block_starts)
    with localcontext() as context:
        context.prec = 28
        downside = (sum((min(value, Decimal(0)) ** 2 for value in returns), Decimal(0)) / Decimal(n)).sqrt()
    tail_count = max(1, math.ceil(n * 0.10))
    tail = tuple(ordered[:tail_count])
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
        # Zero is the audited neutral sentinel; insufficient block coverage is
        # separately persisted as an eligibility rejection.
        "worst_14_day_block_return": min(blocks) if blocks else Decimal(0),
        "downside_deviation": downside,
        "expected_shortfall": sum(tail, Decimal(0)) / Decimal(len(tail)),
        "profit_factor": profit_factor,
        "time_in_market": time_in_market,
        "exposure_adjusted_return": mean / time_in_market if time_in_market else Decimal(0),
        "top_5_trade_pnl_share": sum(sorted(positive, reverse=True)[:5], Decimal(0)) / sum(positive, Decimal(0)) if positive else Decimal(0),
        "top_1_episode_pnl_share": max(positive_episode_pnl) / sum(positive_episode_pnl, Decimal(0)) if positive_episode_pnl else Decimal(0),
        "return_without_best_episode": (sum((value for index, value in enumerate(returns) if index != best_index), Decimal(0)) / Decimal(n - 1) if n >= 2 else Decimal(0)),
    }
    return metrics


def _zero_metrics() -> Mapping[str, Decimal]:
    return {name: Decimal(0) for name in MAPPING_METRIC_NAMES}


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _canonical_json(value: object) -> str:
    def plain(item: object) -> object:
        if isinstance(item, Mapping):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, tuple):
            return [plain(child) for child in item]
        return item
    return json.dumps(plain(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _match_optional(expected: str | None, actual: str, field: str) -> None:
    if expected is not None and expected != actual:
        raise ValueError(f"{field} mismatch")
