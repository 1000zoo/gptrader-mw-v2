from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Mapping, Sequence

from scripts.deferred_strategy_registry import (
    ensure_candidate_group_allowed,
    ensure_candidate_ids_allowed,
)
from scripts.scheduler_driven_scalping_backtest import (
    BACKTEST_ENGINE_VERSION,
    FEE_RATE,
    SLIPPAGE_RATE,
    SchedulerBacktestCandidate,
    alpha_entry_candidates,
    build_scheduler_candidates,
    candidate_payload,
    counter_microstructure_candidates,
    discovered_metrics_candidates,
    exact_historical_candidates,
    metrics_positioning_candidates,
    microstructure_alpha_candidates,
    multi_frequency_candidates,
    run_scheduler_driven_backtest,
    validate_unique_candidate_ids,
)
from src.domain.market import MarketSnapshot, Symbol
from src.domain.regime import WeeklyEpisode


_WEEK = timedelta(days=7)
_CANDIDATE_FACTORIES = {
    "all": build_scheduler_candidates,
    "exact": exact_historical_candidates,
    "alpha": alpha_entry_candidates,
    "multi": multi_frequency_candidates,
    "microstructure": microstructure_alpha_candidates,
    "counter": counter_microstructure_candidates,
    "metrics": metrics_positioning_candidates,
    "discovered": discovered_metrics_candidates,
}


def run_mapping_episodes(
    market: MarketSnapshot,
    *,
    episodes: Sequence[WeeklyEpisode],
    assignments: Mapping[datetime, str],
    candidate_groups: Sequence[str] = (),
    candidate_ids: Sequence[str] = (),
    include_deferred_groups: Sequence[str] = (),
    candidates: Sequence[SchedulerBacktestCandidate] | None = None,
    initial_equity: Decimal = Decimal("10000"),
    symbol: Symbol | None = None,
    market_feature_provider=None,
) -> list[dict[str, object]]:
    """Collect independent weekly candidate evidence through the real scheduler simulator."""
    normalized_episodes = _validate_episodes(episodes)
    cluster_by_anchor = _validate_assignments(normalized_episodes, assignments)
    resolved, allow_deferred = _resolve_candidates(
        candidates=candidates,
        candidate_groups=candidate_groups,
        candidate_ids=candidate_ids,
        include_deferred_groups=include_deferred_groups,
    )
    if not isinstance(initial_equity, Decimal) or not initial_equity.is_finite() or initial_equity <= 0:
        raise ValueError("initial_equity must be a finite positive Decimal")
    selected_symbol = symbol or market.symbol

    rows: list[dict[str, object]] = []
    for episode in normalized_episodes:
        sliced = _slice_episode(market, episode)
        data_hash = _canonical_hash(_market_payload(sliced))
        for candidate in resolved:
            candidate_hash = _canonical_hash(
                {
                    "engine_version": BACKTEST_ENGINE_VERSION,
                    "symbol": selected_symbol.pair,
                    "initial_equity": str(initial_equity),
                    "fee_rate_per_side": str(FEE_RATE),
                    "slippage_rate_per_side": str(SLIPPAGE_RATE),
                    "account_risk": {
                        "base_risk_ratio": "0.02",
                        "max_total_exposure_ratio": "1",
                        "max_symbol_exposure_ratio": "1",
                    },
                    "candidate": candidate_payload(candidate),
                }
            )
            result = run_scheduler_driven_backtest(
                sliced,
                start_at=episode.start_at,
                end_at=episode.end_at,
                candidate=candidate,
                symbol=selected_symbol,
                market_feature_provider=market_feature_provider,
                include_deferred=allow_deferred,
                initial_equity=initial_equity,
                include_trade_details=True,
                force_close_at_end=True,
            )
            net_pnl = Decimal(str(result.get("net_pnl", "0")))
            row = {
                "episode_start_at": episode.start_at.isoformat(),
                "episode_end_at": episode.end_at.isoformat(),
                "cluster_fingerprint": cluster_by_anchor[episode.anchor_at],
                "candidate_id": candidate.candidate_id,
                "initial_equity": str(initial_equity),
                "final_equity": str(initial_equity + net_pnl),
                "data_hash": data_hash,
                "candidate_hash": candidate_hash,
            }
            row.update(
                (key, result[key])
                for key in (
                    "trade_count",
                    "gross_pnl",
                    "net_pnl",
                    "fee_paid",
                    "return_ratio",
                    "daily_return_ratio",
                    "max_drawdown_ratio",
                    "net_win_rate",
                    "average_net_trade_roe",
                    "average_net_trade_expectancy_ratio",
                    "trades",
                )
                if key in result
            )
            rows.append(row)
    return rows


def _resolve_candidates(
    *,
    candidates: Sequence[SchedulerBacktestCandidate] | None,
    candidate_groups: Sequence[str],
    candidate_ids: Sequence[str],
    include_deferred_groups: Sequence[str],
) -> tuple[tuple[SchedulerBacktestCandidate, ...], bool]:
    if candidates is not None:
        if candidate_groups or candidate_ids or include_deferred_groups:
            raise ValueError("direct candidates cannot be combined with factory selection")
        resolved = validate_unique_candidate_ids(tuple(candidates))
        ensure_candidate_ids_allowed(tuple(item.candidate_id for item in resolved))
        allow_deferred = False
    else:
        groups = tuple(candidate_groups)
        if not groups:
            raise ValueError("candidate_groups must be explicitly selected")
        if len(set(groups)) != len(groups):
            raise ValueError("duplicate candidate group")
        opted_in = tuple(include_deferred_groups)
        if len(set(opted_in)) != len(opted_in) or any(group not in groups for group in opted_in):
            raise ValueError("deferred opt-ins must uniquely reference selected groups")
        unknown_groups = sorted(set(groups) - set(_CANDIDATE_FACTORIES))
        if unknown_groups:
            raise ValueError(f"unknown candidate group: {', '.join(unknown_groups)}")
        built = []
        for group in groups:
            ensure_candidate_group_allowed(group, include_deferred=group in opted_in)
            built.extend(_CANDIDATE_FACTORIES[group]())
        resolved = validate_unique_candidate_ids(tuple(built))
        allow_deferred = bool(opted_in)

    requested_ids = tuple(candidate_ids)
    if len(set(requested_ids)) != len(requested_ids):
        raise ValueError("duplicate candidate_id selection")
    if requested_ids:
        by_id = {candidate.candidate_id: candidate for candidate in resolved}
        unknown_ids = sorted(set(requested_ids) - set(by_id))
        if unknown_ids:
            raise ValueError(f"unknown candidate_id: {', '.join(unknown_ids)}")
        resolved = tuple(by_id[candidate_id] for candidate_id in requested_ids)
    if not resolved:
        raise ValueError("at least one candidate is required")
    return tuple(sorted(resolved, key=lambda item: item.candidate_id)), allow_deferred


def _validate_episodes(episodes: Sequence[WeeklyEpisode]) -> tuple[WeeklyEpisode, ...]:
    normalized = tuple(episodes)
    if not normalized:
        raise ValueError("at least one weekly episode is required")
    for index, episode in enumerate(normalized):
        if not all(_is_canonical_utc(value) for value in (
            episode.anchor_at, episode.feature_start_at, episode.start_at, episode.end_at
        )):
            raise ValueError("episode timestamps must use canonical UTC")
        if not _is_monday_midnight(episode.start_at):
            raise ValueError("episode must start Monday 00:00 UTC")
        if episode.anchor_at != episode.start_at:
            raise ValueError("episode anchor must equal episode start")
        if episode.feature_start_at != episode.start_at - _WEEK:
            raise ValueError("episode feature window must be the preceding seven days")
        if episode.end_at != episode.start_at + _WEEK:
            raise ValueError("episode must span exactly seven days")
        if index and normalized[index - 1].end_at != episode.start_at:
            raise ValueError("weekly episodes must be consecutive and non-overlapping")
    return normalized


def _validate_assignments(
    episodes: tuple[WeeklyEpisode, ...], assignments: Mapping[datetime, str]
) -> dict[datetime, str]:
    expected = {episode.anchor_at for episode in episodes}
    if set(assignments) != expected:
        raise ValueError("assignments must cover exactly every episode anchor")
    result = dict(assignments)
    if any(not isinstance(value, str) or not value.strip() for value in result.values()):
        raise ValueError("cluster fingerprint must be nonempty")
    return result


def _slice_episode(market: MarketSnapshot, episode: WeeklyEpisode) -> MarketSnapshot:
    candles = tuple(
        candle for candle in market.candles
        if episode.start_at <= candle.opened_at and candle.closed_at <= episode.end_at
    )
    if not candles or candles[0].opened_at != episode.start_at or candles[-1].closed_at != episode.end_at:
        raise ValueError("episode market data is absent or incomplete")
    if any(left.closed_at != right.opened_at for left, right in zip(candles, candles[1:])):
        raise ValueError("episode market data contains a gap")
    if any(not _is_canonical_utc(value) for candle in candles for value in (candle.opened_at, candle.closed_at)):
        raise ValueError("market timestamps must use canonical UTC")
    return MarketSnapshot(candles)


def _market_payload(market: MarketSnapshot) -> dict[str, object]:
    return {
        "symbol": market.symbol.pair,
        "timeframe": market.timeframe.label,
        "candles": [
            {
                "opened_at": candle.opened_at.isoformat(),
                "closed_at": candle.closed_at.isoformat(),
                "open": str(candle.open_price),
                "high": str(candle.high_price),
                "low": str(candle.low_price),
                "close": str(candle.close_price),
                "volume": str(candle.volume),
            }
            for candle in market.candles
        ],
    }


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_canonical_utc(value: datetime) -> bool:
    return value.tzinfo is timezone.utc


def _is_monday_midnight(value: datetime) -> bool:
    return value.weekday() == 0 and value.time() == datetime.min.time()
