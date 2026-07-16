from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import math
import re
from typing import Mapping, Sequence

import numpy as np

from src.domain.regime.daily_mapping import (
    DAILY_STRATEGY_MAPPING_ARTIFACT_VERSION,
    DailyCandidateAssessment,
    DailyStrategyEvidence,
    DailyStrategyMappingArtifact,
    DailyStrategyMappingEntry,
)
from src.domain.regime.mapping import candidate_universe_hash
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)
from src.domain.regime.three_day_daily_profile import (
    BOOTSTRAP_BLOCK_DAYS,
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_RESAMPLES,
    MIN_CALENDAR_MONTHS,
    MIN_CLOSED_TRADES,
    MIN_EPISODES,
    PROFILE_ID,
    RANDOM_SEED,
    STRICT_RISK_POLICY,
    ThreeDayDailyWalkForwardFold,
    decimal_arithmetic_context,
)


_SHA256 = re.compile(r"[0-9a-f]{64}")
_REJECTION_ORDER = (
    "insufficient_daily_episodes",
    "insufficient_calendar_months",
    "insufficient_closed_trades",
    "non_positive_net_performance_after_costs",
    "non_positive_corrected_lower_bound",
    "statistically_not_better_than_cash",
    "insufficient_complete_seven_day_blocks",
    "worst_seven_day_return_below_limit",
    "expected_shortfall_below_limit",
    "maximum_drawdown_above_limit",
    "non_positive_return_without_best_episode",
    "no_positive_episode_profit",
    "top_episode_profit_share_above_limit",
    "no_positive_trade_profit",
    "top_five_trade_profit_share_above_limit",
)


@dataclass(frozen=True)
class BuildDailyStrategyMappingCommand:
    model_artifact_hash: str
    candidate_manifest: tuple[tuple[str, str], ...]
    calendar: tuple[datetime, ...]
    component_assignments: tuple[str, ...]
    evidence_rows: tuple[DailyStrategyEvidence, ...]


@dataclass(frozen=True)
class BuildDailyStrategyMappingResult:
    artifact: DailyStrategyMappingArtifact


class BuildDailyStrategyMappingUseCase:
    def execute(
        self, command: BuildDailyStrategyMappingCommand
    ) -> BuildDailyStrategyMappingResult:
        if not isinstance(command, BuildDailyStrategyMappingCommand):
            raise ValueError("daily strategy mapping command is required")
        candidate_ids, candidate_hashes = _validate_manifest(command.candidate_manifest)
        calendar = _validate_calendar(command.calendar)
        assignments, components = _validate_assignments(
            calendar, command.component_assignments
        )
        rows_by_key = _validate_evidence_grid(
            command.evidence_rows,
            calendar=calendar,
            assignments=assignments,
            candidate_ids=candidate_ids,
            candidate_hashes=candidate_hashes,
            model_artifact_hash=command.model_artifact_hash,
        )

        assessments: list[DailyCandidateAssessment] = []
        entries: list[DailyStrategyMappingEntry] = []
        for component in components:
            assigned_indices = tuple(
                index for index, label in enumerate(assignments) if label == component
            )
            aligned_returns: dict[str, tuple[Decimal | None, ...]] = {}
            preliminary: dict[str, dict[str, object]] = {}
            coverage_eligible: list[str] = []
            for candidate in candidate_ids:
                candidate_rows = tuple(rows_by_key[(candidate, day)] for day in calendar)
                component_rows = tuple(candidate_rows[index] for index in assigned_indices)
                available_rows = tuple(
                    row for row in component_rows if row.availability_status == "available"
                )
                unavailable = Counter(
                    row.availability_reason
                    for row in component_rows
                    if row.availability_status == "unavailable"
                )
                returns = tuple(row.net_return_ratio for row in available_rows)
                months = len(
                    {(row.outcome_start_at.year, row.outcome_start_at.month) for row in available_rows}
                )
                trade_count = sum(row.closed_trade_count for row in available_rows)
                aligned = tuple(
                    Decimal(0)
                    if assignments[index] != component
                    else (
                        rows_by_key[(candidate, day)].net_return_ratio
                        if rows_by_key[(candidate, day)].availability_status == "available"
                        else None
                    )
                    for index, day in enumerate(calendar)
                )
                aligned_returns[candidate] = aligned
                preliminary[candidate] = {
                    "component_rows": component_rows,
                    "available_rows": available_rows,
                    "unavailable": unavailable,
                    "returns": returns,
                    "months": months,
                    "trade_count": trade_count,
                    "aligned": aligned,
                }
                if (
                    len(returns) >= MIN_EPISODES
                    and months >= MIN_CALENDAR_MONTHS
                ):
                    coverage_eligible.append(candidate)

            lower_bounds = {candidate: Decimal(0) for candidate in candidate_ids}
            if coverage_eligible:
                lower_bounds.update(
                    _aligned_component_corrected_lower_bounds(
                        {
                            candidate: aligned_returns[candidate]
                            for candidate in coverage_eligible
                        },
                        assignments,
                        component,
                    )
                )

            component_assessments: list[DailyCandidateAssessment] = []
            for candidate in candidate_ids:
                data = preliminary[candidate]
                rows = data["available_rows"]
                returns = data["returns"]
                aligned = data["aligned"]
                if not isinstance(rows, tuple) or not isinstance(returns, tuple) or not isinstance(aligned, tuple):
                    raise RuntimeError("invalid internal daily mapping state")
                metrics = _metrics(rows, returns, aligned)
                unavailable = data["unavailable"]
                if not isinstance(unavailable, Counter):
                    raise RuntimeError("invalid unavailable evidence state")
                reasons = rejection_reasons(
                    episode_count=len(returns),
                    calendar_month_count=int(data["months"]),
                    closed_trade_count=int(data["trade_count"]),
                    net_compounded_return=metrics["net_compounded_return"],
                    corrected_lower_bound=lower_bounds[candidate],
                    worst_seven_day_return=metrics["worst_seven_day_return"],
                    expected_shortfall=metrics["expected_shortfall"],
                    drawdown=metrics["drawdown"],
                    return_without_best=metrics["return_without_best"],
                    top_episode_share=metrics["top_episode_share"],
                    top_five_trade_share=metrics["top_five_trade_share"],
                    has_positive_episode_profit=bool(metrics["has_positive_episode_profit"]),
                    has_positive_trade_profit=bool(metrics["has_positive_trade_profit"]),
                    has_complete_seven_day_block=bool(
                        metrics["has_complete_seven_day_block"]
                    ),
                )
                assessment = DailyCandidateAssessment(
                    component_fingerprint=component,
                    candidate_id=candidate,
                    candidate_hash=candidate_hashes[candidate],
                    assigned_day_count=len(assigned_indices),
                    episode_count=len(returns),
                    unavailable_day_count=sum(unavailable.values()),
                    unavailable_reason_counts=tuple(sorted(unavailable.items())),
                    calendar_month_count=int(data["months"]),
                    closed_trade_count=int(data["trade_count"]),
                    mean_daily_return_ratio=metrics["mean"],
                    median_daily_return_ratio=metrics["median"],
                    corrected_lower_bound_ratio=lower_bounds[candidate],
                    worst_seven_day_return_ratio=metrics["worst_seven_day_return"],
                    expected_shortfall_10_ratio=metrics["expected_shortfall"],
                    maximum_drawdown_ratio=metrics["drawdown"],
                    return_without_best_episode_ratio=metrics["return_without_best"],
                    top_episode_profit_share=metrics["top_episode_share"],
                    top_five_trade_profit_share=metrics["top_five_trade_share"],
                    eligible=not reasons,
                    rejection_reasons=reasons,
                )
                assessments.append(assessment)
                component_assessments.append(assessment)

            eligible = tuple(item for item in component_assessments if item.eligible)
            if eligible:
                winner = min(eligible, key=_winner_order_key)
                entries.append(
                    DailyStrategyMappingEntry(component, "strategy", winner.candidate_id)
                )
            else:
                aggregate = tuple(
                    reason
                    for reason in _REJECTION_ORDER
                    if any(reason in item.rejection_reasons for item in component_assessments)
                )
                entries.append(
                    DailyStrategyMappingEntry(
                        component,
                        "cash",
                        None,
                        ("no_eligible_candidate",) + aggregate,
                    )
                )

        fold = ThreeDayDailyWalkForwardFold.default()
        artifact = DailyStrategyMappingArtifact(
            artifact_version=DAILY_STRATEGY_MAPPING_ARTIFACT_VERSION,
            profile_id=PROFILE_ID,
            feature_schema_version=THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
            model_artifact_hash=command.model_artifact_hash,
            candidate_universe_hash=candidate_universe_hash(candidate_ids),
            candidate_ids=candidate_ids,
            candidate_hashes=candidate_hashes,
            component_fingerprints=components,
            entries=tuple(entries),
            candidate_assessments=tuple(assessments),
            risk_policy=STRICT_RISK_POLICY,
            cluster_fit=fold.cluster_fit,
            mapping_fit=fold.mapping_fit,
        )
        return BuildDailyStrategyMappingResult(artifact)


def _circular_moving_block_indices(
    calendar_length: int,
    *,
    random_seed: int = RANDOM_SEED,
    block_days: int = BOOTSTRAP_BLOCK_DAYS,
) -> tuple[int, ...]:
    if not isinstance(calendar_length, int) or isinstance(calendar_length, bool) or calendar_length < 1:
        raise ValueError("calendar length must be a positive integer")
    if not isinstance(block_days, int) or isinstance(block_days, bool) or block_days < 1:
        raise ValueError("block days must be a positive integer")
    _validate_random_seed(random_seed)
    rng = np.random.default_rng(random_seed)
    return tuple(int(value) for value in _draw_block_indices(rng, calendar_length, block_days))


def _draw_block_indices(
    rng: np.random.Generator, calendar_length: int, block_days: int
) -> np.ndarray:
    block_count = math.ceil(calendar_length / block_days)
    starts = rng.integers(0, calendar_length, size=block_count, dtype=np.int64)
    offsets = np.arange(block_days, dtype=np.int64)
    return ((starts[:, None] + offsets[None, :]) % calendar_length).reshape(-1)[:calendar_length]


def _aligned_component_corrected_lower_bounds(
    returns_by_candidate: Mapping[str, Sequence[Decimal | None]],
    component_labels: Sequence[str],
    component_fingerprint: str,
    *,
    random_seed: int = RANDOM_SEED,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = BOOTSTRAP_CONFIDENCE,
    block_days: int = BOOTSTRAP_BLOCK_DAYS,
    maximum_attempts: int | None = None,
) -> dict[str, Decimal]:
    candidates = tuple(sorted(returns_by_candidate))
    labels = tuple(component_labels)
    if not candidates or not labels:
        raise ValueError("aligned bootstrap requires candidates and calendar labels")
    if any(len(returns_by_candidate[candidate]) != len(labels) for candidate in candidates):
        raise ValueError("aligned bootstrap candidate coverage mismatch")
    if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < 1:
        raise ValueError("bootstrap resamples must be positive")
    _validate_random_seed(random_seed)
    if not isinstance(block_days, int) or isinstance(block_days, bool) or block_days < 1:
        raise ValueError("block days must be a positive integer")
    if not 0 < confidence < 1:
        raise ValueError("bootstrap confidence must be between zero and one")
    if maximum_attempts is None:
        maximum_attempts = 100 * resamples
    if (
        not isinstance(maximum_attempts, int)
        or isinstance(maximum_attempts, bool)
        or maximum_attempts < 1
    ):
        raise ValueError("bootstrap maximum attempts must be a positive integer")
    if maximum_attempts < resamples:
        raise ValueError("bootstrap maximum attempts cannot be smaller than resamples")

    target = np.asarray([label == component_fingerprint for label in labels], dtype=np.bool_)
    values: dict[str, np.ndarray] = {}
    masks: dict[str, np.ndarray] = {}
    means: dict[str, float] = {}
    decimal_means: dict[str, Decimal] = {}
    standard_errors: dict[str, float] = {}
    constant_positive: set[str] = set()
    for candidate in candidates:
        supplied = tuple(returns_by_candidate[candidate])
        mask = np.asarray(
            [isinstance(value, Decimal) and value.is_finite() for value in supplied],
            dtype=np.bool_,
        ) & target
        if any(value is not None and (not isinstance(value, Decimal) or not value.is_finite()) for value in supplied):
            raise ValueError("bootstrap returns must be finite Decimals or unavailable")
        observed_decimals = tuple(
            value for value, included in zip(supplied, mask) if included and isinstance(value, Decimal)
        )
        if len(observed_decimals) < 2:
            raise ValueError("bootstrap candidates require at least two component observations")
        if any(value <= Decimal("-1") for value in observed_decimals):
            raise ValueError("daily returns must be greater than -1")
        observed = np.asarray([float(value) for value in observed_decimals], dtype=np.float64)
        if not np.all(np.isfinite(observed)):
            raise ValueError("bootstrap returns must remain finite float64 values")
        calendar_values = np.zeros(len(labels), dtype=np.float64)
        calendar_values[mask] = observed
        mean = float(observed.mean())
        zero_variance = len(set(observed_decimals)) == 1
        standard_error = (
            0.0
            if zero_variance
            else float(observed.std(ddof=1) / math.sqrt(observed.size))
        )
        values[candidate] = calendar_values - np.where(mask, mean, 0.0)
        masks[candidate] = mask
        means[candidate] = mean
        with decimal_arithmetic_context():
            decimal_means[candidate] = sum(
                observed_decimals, Decimal(0)
            ) / Decimal(len(observed_decimals))
        standard_errors[candidate] = standard_error
        if zero_variance and observed_decimals[0] > 0:
            constant_positive.add(candidate)

    rng = np.random.default_rng(random_seed)
    statistics = np.empty(resamples, dtype=np.float64)
    accepted = 0
    attempts = 0
    while accepted < resamples and attempts < maximum_attempts:
        attempts += 1
        indices = _draw_block_indices(rng, len(labels), block_days)
        candidate_statistics: list[float] = []
        valid = True
        for candidate in candidates:
            selected = values[candidate][indices][masks[candidate][indices]]
            if selected.size < 2:
                valid = False
                break
            sample_standard_error = float(selected.std(ddof=1) / math.sqrt(selected.size))
            if sample_standard_error == 0.0:
                statistic = 0.0
            else:
                statistic = float(selected.mean() / sample_standard_error)
            if not math.isfinite(statistic):
                valid = False
                break
            candidate_statistics.append(statistic)
        if not valid:
            continue
        statistics[accepted] = max(candidate_statistics)
        accepted += 1
    if accepted != resamples:
        raise ValueError(
            f"bootstrap could not draw {resamples} valid aligned resamples within {maximum_attempts} attempts"
        )
    rank = max(1, math.ceil(confidence * resamples)) - 1
    critical_value = float(np.partition(statistics, rank)[rank])
    if not math.isfinite(critical_value):
        raise ValueError("bootstrap critical value is not finite")

    result: dict[str, Decimal] = {}
    for candidate in candidates:
        if candidate in constant_positive:
            result[candidate] = decimal_means[candidate]
            continue
        elif standard_errors[candidate] == 0.0:
            value = min(means[candidate], 0.0)
        else:
            value = means[candidate] - critical_value * standard_errors[candidate]
        if not math.isfinite(value):
            raise ValueError("corrected lower bound is not finite")
        result[candidate] = Decimal(str(value))
    return result


def expected_shortfall_10(returns: Sequence[Decimal]) -> Decimal:
    values = _finite_returns(returns)
    if not values:
        return Decimal(0)
    count = max(1, math.ceil(len(values) * 0.10))
    with decimal_arithmetic_context():
        return sum(sorted(values)[:count], Decimal(0)) / Decimal(count)


def worst_seven_calendar_day_return(
    aligned_returns: Sequence[Decimal | None],
) -> Decimal:
    _validate_optional_returns(aligned_returns)
    compounded: list[Decimal] = []
    for start in range(max(0, len(aligned_returns) - BOOTSTRAP_BLOCK_DAYS + 1)):
        block = tuple(aligned_returns[start : start + BOOTSTRAP_BLOCK_DAYS])
        if any(value is None for value in block):
            continue
        compounded.append(_compound(tuple(value for value in block if value is not None)))
    return min(compounded) if compounded else Decimal(0)


def maximum_drawdown(returns: Sequence[Decimal]) -> Decimal:
    values = _finite_returns(returns)
    with decimal_arithmetic_context():
        equity = Decimal(1)
        peak = Decimal(1)
        drawdown = Decimal(0)
        for value in values:
            equity *= Decimal(1) + value
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak - equity) / peak)
        return drawdown


def compounded_return_without_best_episode(returns: Sequence[Decimal]) -> Decimal:
    values = _finite_returns(returns)
    if len(values) < 2:
        return Decimal(0)
    best_index = max(range(len(values)), key=lambda index: (values[index], -index))
    return _compound(tuple(value for index, value in enumerate(values) if index != best_index))


def positive_profit_concentration_shares(
    episode_pnls: Sequence[Decimal], trade_pnls: Sequence[Decimal]
) -> tuple[Decimal, Decimal, bool, bool]:
    episodes = _finite_decimals(episode_pnls, "episode PnLs")
    trades = _finite_decimals(trade_pnls, "trade PnLs")
    positive_episodes = tuple(value for value in episodes if value > 0)
    positive_trades = tuple(value for value in trades if value > 0)
    with decimal_arithmetic_context():
        episode_total = sum(positive_episodes, Decimal(0))
        trade_total = sum(positive_trades, Decimal(0))
        return (
            max(positive_episodes) / episode_total if episode_total else Decimal(0),
            sum(sorted(positive_trades, reverse=True)[:5], Decimal(0)) / trade_total
            if trade_total
            else Decimal(0),
            bool(episode_total),
            bool(trade_total),
        )


def rejection_reasons(
    *,
    episode_count: int,
    calendar_month_count: int,
    closed_trade_count: int,
    net_compounded_return: Decimal,
    corrected_lower_bound: Decimal,
    worst_seven_day_return: Decimal,
    expected_shortfall: Decimal,
    drawdown: Decimal,
    return_without_best: Decimal,
    top_episode_share: Decimal,
    top_five_trade_share: Decimal,
    has_positive_episode_profit: bool,
    has_positive_trade_profit: bool,
    has_complete_seven_day_block: bool,
) -> tuple[str, ...]:
    failed = {
        "insufficient_daily_episodes": episode_count < MIN_EPISODES,
        "insufficient_calendar_months": calendar_month_count < MIN_CALENDAR_MONTHS,
        "insufficient_closed_trades": closed_trade_count < MIN_CLOSED_TRADES,
        "non_positive_net_performance_after_costs": net_compounded_return <= 0,
        "non_positive_corrected_lower_bound": corrected_lower_bound <= 0,
        "statistically_not_better_than_cash": corrected_lower_bound <= 0,
        "insufficient_complete_seven_day_blocks": not has_complete_seven_day_block,
        "worst_seven_day_return_below_limit": worst_seven_day_return
        < STRICT_RISK_POLICY.minimum_worst_seven_day_return_ratio,
        "expected_shortfall_below_limit": expected_shortfall
        < STRICT_RISK_POLICY.minimum_expected_shortfall_10_ratio,
        "maximum_drawdown_above_limit": drawdown
        > STRICT_RISK_POLICY.maximum_drawdown_ratio,
        "non_positive_return_without_best_episode": return_without_best <= 0,
        "no_positive_episode_profit": not has_positive_episode_profit,
        "top_episode_profit_share_above_limit": top_episode_share
        > STRICT_RISK_POLICY.maximum_top_episode_profit_share,
        "no_positive_trade_profit": not has_positive_trade_profit,
        "top_five_trade_profit_share_above_limit": top_five_trade_share
        > STRICT_RISK_POLICY.maximum_top_five_trade_profit_share,
    }
    return tuple(reason for reason in _REJECTION_ORDER if failed[reason])


def _winner_order_key(item: DailyCandidateAssessment) -> tuple[object, ...]:
    return (
        item.corrected_lower_bound_ratio.copy_negate(),
        item.return_without_best_episode_ratio.copy_negate(),
        item.expected_shortfall_10_ratio.copy_negate(),
        item.maximum_drawdown_ratio,
        item.median_daily_return_ratio.copy_negate(),
        item.candidate_id,
    )


def _metrics(
    rows: tuple[DailyStrategyEvidence, ...],
    returns: tuple[Decimal, ...],
    aligned: tuple[Decimal | None, ...],
) -> dict[str, Decimal | bool]:
    ordered = sorted(returns)
    if returns:
        with decimal_arithmetic_context():
            mean = sum(returns, Decimal(0)) / Decimal(len(returns))
            middle = len(ordered) // 2
            median = (
                ordered[middle]
                if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
            )
    else:
        mean = median = Decimal(0)
    episode_pnls = tuple(row.net_pnl for row in rows)
    trade_pnls = tuple(
        pnl for row in rows for pnl in (row.trade_pnls or ())
    )
    top_episode, top_five, has_episode_profit, has_trade_profit = (
        positive_profit_concentration_shares(episode_pnls, trade_pnls)
    )
    return {
        "mean": mean,
        "median": median,
        "net_compounded_return": _compound(returns) if returns else Decimal(0),
        "worst_seven_day_return": worst_seven_calendar_day_return(aligned),
        "expected_shortfall": expected_shortfall_10(returns),
        "drawdown": maximum_drawdown(returns),
        "return_without_best": compounded_return_without_best_episode(returns),
        "top_episode_share": top_episode,
        "top_five_trade_share": top_five,
        "has_positive_episode_profit": has_episode_profit,
        "has_positive_trade_profit": has_trade_profit,
        "has_complete_seven_day_block": _has_complete_seven_day_block(aligned),
    }


def _validate_manifest(
    manifest: Sequence[tuple[str, str]],
) -> tuple[tuple[str, ...], dict[str, str]]:
    supplied = tuple(manifest)
    if not supplied:
        raise ValueError("candidate manifest must be nonempty")
    if any(
        not isinstance(item, tuple)
        or len(item) != 2
        or not isinstance(item[0], str)
        or not item[0]
        or item[0] != item[0].strip()
        or not isinstance(item[1], str)
        or _SHA256.fullmatch(item[1]) is None
        for item in supplied
    ):
        raise ValueError("candidate manifest contains an invalid entry")
    candidate_ids = tuple(item[0] for item in supplied)
    if candidate_ids != tuple(sorted(set(candidate_ids))):
        raise ValueError("candidate manifest must be ordered, unique, and canonical")
    return candidate_ids, dict(supplied)


def _validate_calendar(calendar: Sequence[datetime]) -> tuple[datetime, ...]:
    supplied = tuple(calendar)
    fold = ThreeDayDailyWalkForwardFold.default()
    count = (fold.mapping_fit.end_at - fold.mapping_fit.start_at).days
    expected = tuple(
        fold.mapping_fit.start_at + timedelta(days=index) for index in range(count)
    )
    if supplied != expected:
        raise ValueError("calendar must be the ordered complete Mapping Fit calendar")
    return supplied


def _validate_assignments(
    calendar: tuple[datetime, ...], assignments: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    supplied = tuple(assignments)
    if len(supplied) != len(calendar):
        raise ValueError("one component assignment is required per calendar day")
    if any(not isinstance(value, str) or not value or value != value.strip() for value in supplied):
        raise ValueError("component assignments must be canonical strings")
    components = tuple(sorted(set(supplied)))
    if len(components) != 4:
        raise ValueError("component assignments must contain exactly four frozen components")
    return supplied, components


def _validate_evidence_grid(
    evidence_rows: Sequence[DailyStrategyEvidence],
    *,
    calendar: tuple[datetime, ...],
    assignments: tuple[str, ...],
    candidate_ids: tuple[str, ...],
    candidate_hashes: Mapping[str, str],
    model_artifact_hash: str,
) -> dict[tuple[str, datetime], DailyStrategyEvidence]:
    if _SHA256.fullmatch(model_artifact_hash) is None:
        raise ValueError("model hash must be a lowercase SHA256 hash")
    calendar_set = set(calendar)
    assignment_by_day = dict(zip(calendar, assignments))
    rows_by_key: dict[tuple[str, datetime], DailyStrategyEvidence] = {}
    cost_hash: str | None = None
    engine_hash: str | None = None
    data_hash_by_day: dict[datetime, str] = {}
    for row in tuple(evidence_rows):
        if not isinstance(row, DailyStrategyEvidence):
            raise ValueError("evidence rows must contain DailyStrategyEvidence values")
        if row.candidate_id not in candidate_hashes:
            raise ValueError("evidence candidate is not in the frozen manifest")
        if row.outcome_start_at not in calendar_set:
            raise ValueError("evidence date is outside the Mapping Fit calendar")
        key = (row.candidate_id, row.outcome_start_at)
        if key in rows_by_key:
            raise ValueError("duplicate or conflicting candidate/day evidence")
        if row.component_fingerprint != assignment_by_day[row.outcome_start_at]:
            raise ValueError("candidate/component coverage mismatch")
        if row.availability_status == "unavailable" and (
            any(
                value != 0
                for value in (
                    row.gross_pnl,
                    row.net_pnl,
                    row.gross_return_ratio,
                    row.net_return_ratio,
                    row.fees,
                    row.exposure_ratio,
                    row.turnover_ratio,
                    row.maximum_drawdown_ratio,
                    row.maximum_adverse_excursion_ratio,
                    row.profit_factor,
                    row.downside_deviation_ratio,
                    row.expected_shortfall_10_ratio,
                    row.median_daily_return_ratio,
                    row.tenth_percentile_daily_return_ratio,
                    row.worst_seven_day_return_ratio,
                    row.return_without_best_episode_ratio,
                    row.top_episode_profit_share,
                    row.top_five_trade_profit_share,
                )
            )
            or row.closed_trade_count != 0
            or row.trade_pnls is not None
        ):
            raise ValueError("unavailable evidence cannot contain performance")
        if row.availability_status == "available":
            if not isinstance(row.trade_pnls, tuple):
                raise ValueError("trade PnLs are required for concentration audit")
            if (
                len(row.trade_pnls) != row.closed_trade_count
                or any(
                    not isinstance(value, Decimal) or not value.is_finite()
                    for value in row.trade_pnls
                )
                or _decimal_sum(row.trade_pnls) != row.net_pnl
            ):
                raise ValueError("trade PnLs are inconsistent with available evidence")
        if row.candidate_hash != candidate_hashes[row.candidate_id]:
            raise ValueError("candidate hash drift")
        if row.model_artifact_hash != model_artifact_hash:
            raise ValueError("model hash drift")
        if cost_hash is None:
            cost_hash = row.cost_config_hash
        elif row.cost_config_hash != cost_hash:
            raise ValueError("cost configuration hash drift")
        if engine_hash is None:
            engine_hash = row.engine_config_hash
        elif row.engine_config_hash != engine_hash:
            raise ValueError("engine configuration hash drift")
        previous_data_hash = data_hash_by_day.setdefault(
            row.outcome_start_at, row.data_hash
        )
        if row.data_hash != previous_data_hash:
            raise ValueError("data hash drift across candidates")
        rows_by_key[key] = row
    expected = {(candidate, day) for candidate in candidate_ids for day in calendar}
    if set(rows_by_key) != expected:
        raise ValueError("evidence coverage must include every frozen candidate and calendar day")
    return rows_by_key


def _has_complete_seven_day_block(
    aligned_returns: Sequence[Decimal | None],
) -> bool:
    return any(
        all(value is not None for value in aligned_returns[start : start + BOOTSTRAP_BLOCK_DAYS])
        for start in range(max(0, len(aligned_returns) - BOOTSTRAP_BLOCK_DAYS + 1))
    )


def _validate_random_seed(random_seed: int) -> None:
    if (
        not isinstance(random_seed, int)
        or isinstance(random_seed, bool)
        or not 0 <= random_seed <= 2**64 - 1
    ):
        raise ValueError("random seed must be an integer between zero and 2**64 - 1")


def _decimal_sum(values: Sequence[Decimal]) -> Decimal:
    with decimal_arithmetic_context():
        return sum(values, Decimal(0))


def _finite_returns(values: Sequence[Decimal]) -> tuple[Decimal, ...]:
    result = _finite_decimals(values, "daily returns")
    if any(value <= Decimal("-1") for value in result):
        raise ValueError("daily returns must be greater than -1")
    return result


def _validate_optional_returns(values: Sequence[Decimal | None]) -> None:
    supplied = tuple(values)
    if any(
        value is not None
        and (
            not isinstance(value, Decimal)
            or not value.is_finite()
            or value <= Decimal("-1")
        )
        for value in supplied
    ):
        raise ValueError("daily returns must be finite Decimals greater than -1 or unavailable")


def _finite_decimals(values: Sequence[Decimal], field: str) -> tuple[Decimal, ...]:
    result = tuple(values)
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in result):
        raise ValueError(f"{field} must contain finite Decimals")
    return result


def _compound(values: Sequence[Decimal]) -> Decimal:
    returns = _finite_returns(values)
    with decimal_arithmetic_context():
        result = Decimal(1)
        for value in returns:
            result *= Decimal(1) + value
        return result - Decimal(1)


__all__ = [
    "BuildDailyStrategyMappingCommand",
    "BuildDailyStrategyMappingResult",
    "BuildDailyStrategyMappingUseCase",
    "compounded_return_without_best_episode",
    "expected_shortfall_10",
    "maximum_drawdown",
    "positive_profit_concentration_shares",
    "rejection_reasons",
    "worst_seven_calendar_day_return",
]
