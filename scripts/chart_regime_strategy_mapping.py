from __future__ import annotations

import hashlib
import json
import math
import mmap
import argparse
import csv
import os
import sys
import tempfile
import zipfile
import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, silhouette_score
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from io import TextIOWrapper
from typing import Callable, Mapping, Sequence
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.deferred_strategy_registry import (
    ensure_candidate_group_allowed,
    ensure_candidate_ids_allowed,
)
from scripts.scheduler_driven_scalping_backtest import (
    BACKTEST_ENGINE_VERSION,
    FEE_RATE,
    SLIPPAGE_RATE,
    TIMEFRAME,
    _update_drawdown,
    SchedulerBacktestCandidate,
    alpha_entry_candidates,
    build_scheduler_candidates,
    build_strategies,
    counter_microstructure_candidates,
    discovered_metrics_candidates,
    exact_historical_candidates,
    feature_provider_config_hash,
    metrics_positioning_candidates,
    microstructure_alpha_candidates,
    multi_frequency_candidates,
    run_scheduler_driven_backtest,
    run_scheduler_driven_regime_backtest,
    required_warmup_candles,
    validate_unique_candidate_ids,
    default_candidate,
)
from src.application.usecases.regime.build_strategy_mapping_usecase import (
    BuildStrategyMappingCommand,
    BuildStrategyMappingUseCase,
)
from src.application.usecases.regime.select_regime_model_usecase import (
    RegimeModelEvidence,
    SelectRegimeModelCommand,
    SelectRegimeModelUseCase,
)
from src.domain.regime.model import RegimeModelConfig
from src.domain.regime.selection import SelectionConfidenceThresholds
from src.infrastructure.regime.json_regime_artifact_repository import (
    JsonRegimeArtifactRepository,
    mapping_artifact_hash,
    model_artifact_hash,
    model_fingerprint_hash,
)
from src.infrastructure.regime.sklearn_regime_model import SklearnRegimeModel
from src.application.services.chart_feature_extractor import ChartFeatureExtractor
from src.domain.market import Candle, Timeframe
from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue
from src.domain.market import MarketSnapshot, Symbol
from src.domain.regime import (
    CHART_FEATURE_REGISTRY_V1,
    CHART_FEATURE_SCHEMA_VERSION,
    RegimeWalkForwardFold,
    UtcInterval,
    WeeklyEpisode,
    build_weekly_episodes,
    candidate_definition_hash,
    candidate_universe_hash,
)


_WEEK = timedelta(days=7)
_SUMMARY_DECIMAL_FIELDS = (
    "initial_equity",
    "final_equity",
    "trades_per_day",
    "gross_pnl",
    "net_pnl",
    "fee_paid",
    "return_ratio",
    "daily_return_ratio",
    "max_drawdown_ratio",
    "net_win_rate",
    "average_net_trade_roe",
    "average_net_trade_expectancy_ratio",
)
_TRADE_DECIMAL_FIELDS = (
    "entry_price",
    "exit_price",
    "quantity",
    "margin",
    "gross_pnl",
    "net_pnl",
    "fee_paid",
)
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
    if selected_symbol != market.symbol:
        raise ValueError("symbol must match the execution market symbol")
    if market.timeframe != TIMEFRAME:
        raise ValueError("execution market timeframe must be exactly 1m")

    warmup_candles = required_warmup_candles(resolved, market_feature_provider)
    candidate_hashes = {
        candidate.candidate_id: _canonical_hash(
            {
                "engine_version": BACKTEST_ENGINE_VERSION,
                "symbol": selected_symbol.pair,
                "initial_equity": initial_equity,
                "fee_rate_per_side": FEE_RATE,
                "slippage_rate_per_side": SLIPPAGE_RATE,
                "account_risk": {
                    "base_risk_ratio": Decimal("0.02"),
                    "max_total_exposure_ratio": Decimal("1"),
                    "max_symbol_exposure_ratio": Decimal("1"),
                },
                "candidate": _candidate_behavior_payload(candidate),
            }
        )
        for candidate in resolved
    }

    rows: list[dict[str, object]] = []
    for episode in normalized_episodes:
        context_start_at = episode.start_at - timedelta(minutes=warmup_candles)
        sliced = _slice_episode(market, episode, context_start_at=context_start_at)
        market_payload_hash = _canonical_hash(
            {
                "context_start_at": context_start_at.isoformat(),
                "execution_start_at": episode.start_at.isoformat(),
                "execution_end_at": episode.end_at.isoformat(),
                "market": _market_payload(sliced),
            }
        )
        for candidate in resolved:
            result = run_scheduler_driven_backtest(
                sliced,
                context_start_at=context_start_at,
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
            validated = _validate_backtest_evidence(
                result,
                candidate=candidate,
                initial_equity=initial_equity,
                market_feature_provider=market_feature_provider,
                episode=episode,
            )
            feature_identity = {
                "feature_cache_hash": validated["feature_cache_hash"],
                "feature_config_hash": validated["feature_config_hash"],
                "feature_provenance": validated["feature_provenance"],
            }
            data_hash = _canonical_hash(
                {"market_payload_hash": market_payload_hash, "feature_identity": feature_identity}
            )
            row = {
                "context_start_at": context_start_at.isoformat(),
                "episode_start_at": episode.start_at.isoformat(),
                "episode_end_at": episode.end_at.isoformat(),
                "cluster_fingerprint": cluster_by_anchor[episode.anchor_at],
                "candidate_id": candidate.candidate_id,
                "market_context_hash": market_payload_hash,
                "data_hash": data_hash,
                "candidate_hash": candidate_hashes[candidate.candidate_id],
            }
            row.update(validated)
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


def _slice_episode(
    market: MarketSnapshot,
    episode: WeeklyEpisode,
    *,
    context_start_at: datetime,
) -> MarketSnapshot:
    candles = tuple(
        candle for candle in market.candles
        if context_start_at <= candle.opened_at and candle.closed_at <= episode.end_at
    )
    if not candles or candles[0].opened_at != context_start_at or candles[-1].closed_at != episode.end_at:
        raise ValueError("episode market context or execution data is absent or incomplete")
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
                "open": candle.open_price,
                "high": candle.high_price,
                "low": candle.low_price,
                "close": candle.close_price,
                "volume": candle.volume,
            }
            for candle in market.candles
        ],
    }


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonicalize(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical hash decimals must be finite")
        normalized = "0" if value == 0 else format(value.normalize(), "f")
        return {"$decimal": normalized}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical hash mapping keys must be strings")
        return {key: _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical hash floats must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical hash value: {type(value).__name__}")


def _candidate_behavior_payload(candidate: SchedulerBacktestCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "take_profit_ratio": candidate.take_profit_ratio,
        "stop_loss_ratio": candidate.stop_loss_ratio,
        "equity_ratio": candidate.equity_ratio,
        "leverage": candidate.leverage,
        "candle_limit": candidate.candle_limit,
        "max_holding_bars": candidate.max_holding_bars,
        "strategies": [
            {"kind": spec.kind, "params": spec.params} for spec in candidate.strategies
        ],
        "guard": {
            "min_minutes_between_entries": candidate.guard.min_minutes_between_entries,
            "pause_minutes_after_loss": candidate.guard.pause_minutes_after_loss,
            "max_daily_loss_ratio": candidate.guard.max_daily_loss_ratio,
            "max_daily_trades": candidate.guard.max_daily_trades,
            "max_consecutive_losses": candidate.guard.max_consecutive_losses,
            "max_peak_drawdown_ratio": candidate.guard.max_peak_drawdown_ratio,
            "min_signal_confidence": candidate.guard.min_signal_confidence,
            "min_1m_range_ratio": candidate.guard.min_1m_range_ratio,
            "max_1m_range_ratio": candidate.guard.max_1m_range_ratio,
        },
    }


def _validate_backtest_evidence(
    result: object,
    *,
    candidate: SchedulerBacktestCandidate,
    initial_equity: Decimal,
    market_feature_provider,
    episode: WeeklyEpisode,
) -> dict[str, object]:
    if not isinstance(result, Mapping):
        raise ValueError("backtest evidence must be a mapping")
    required = {
        "candidate_id",
        "trade_count",
        "trades",
        "feature_cache_hash",
        "feature_provenance",
        "feature_config_hash",
        *_SUMMARY_DECIMAL_FIELDS,
    }
    missing = sorted(required - set(result))
    if missing:
        raise ValueError(f"backtest evidence missing required fields: {', '.join(missing)}")
    if result["candidate_id"] != candidate.candidate_id:
        raise ValueError("backtest evidence candidate_id mismatch")

    decimals = {
        field: _finite_decimal(result[field], field) for field in _SUMMARY_DECIMAL_FIELDS
    }
    if decimals["initial_equity"] != initial_equity:
        raise ValueError("backtest evidence initial_equity mismatch")
    if decimals["final_equity"] != decimals["initial_equity"] + decimals["net_pnl"]:
        raise ValueError("backtest evidence final_equity is inconsistent with net_pnl")
    trade_count = result["trade_count"]
    if not isinstance(trade_count, int) or isinstance(trade_count, bool) or trade_count < 0:
        raise ValueError("backtest evidence trade_count must be a nonnegative integer")
    trades = result["trades"]
    if not isinstance(trades, list):
        raise ValueError("backtest evidence trades must be a list")
    validated_trades = [
        _validate_trade(item, index, episode=episode, candidate=candidate)
        for index, item in enumerate(trades)
    ]
    if trade_count != len(validated_trades):
        raise ValueError("backtest evidence trade_count does not match trades")
    for previous, current in zip(validated_trades, validated_trades[1:]):
        if current["entry_at_value"] < previous["exit_at_value"]:
            raise ValueError(
                "backtest evidence trades must be chronological and non-overlapping"
            )
    total_gross = sum((item["gross_pnl"] for item in validated_trades), Decimal("0"))
    total_net = sum((item["net_pnl"] for item in validated_trades), Decimal("0"))
    total_fees = sum((item["fee_paid"] for item in validated_trades), Decimal("0"))
    _require_decimal_match("gross_pnl", decimals["gross_pnl"], total_gross)
    _require_decimal_match("net_pnl", decimals["net_pnl"], total_net)
    _require_decimal_match("fee_paid", decimals["fee_paid"], total_fees)
    _require_decimal_match(
        "final_equity", decimals["final_equity"], initial_equity + total_net
    )
    expected_return = total_net / initial_equity
    _require_decimal_match("return_ratio", decimals["return_ratio"], expected_return)
    _require_decimal_match(
        "daily_return_ratio",
        decimals["daily_return_ratio"],
        expected_return / Decimal("7"),
    )
    _require_decimal_match(
        "trades_per_day",
        decimals["trades_per_day"],
        Decimal(trade_count) / Decimal("7"),
    )
    wins = sum(1 for item in validated_trades if item["net_pnl"] > 0)
    expected_win_rate = Decimal(wins) / Decimal(trade_count) if trade_count else Decimal("0")
    if not Decimal("0") <= decimals["net_win_rate"] <= Decimal("1"):
        raise ValueError("backtest evidence net_win_rate must be between zero and one")
    _require_decimal_match("net_win_rate", decimals["net_win_rate"], expected_win_rate)
    expected_average_roe = (
        sum((item["net_pnl"] / item["margin"] for item in validated_trades), Decimal("0"))
        / Decimal(trade_count)
        if trade_count
        else Decimal("0")
    )
    _require_decimal_match(
        "average_net_trade_roe",
        decimals["average_net_trade_roe"],
        expected_average_roe,
    )
    expected_expectancy = (
        (total_net / Decimal(trade_count)) / initial_equity
        if trade_count
        else Decimal("0")
    )
    _require_decimal_match(
        "average_net_trade_expectancy_ratio",
        decimals["average_net_trade_expectancy_ratio"],
        expected_expectancy,
    )
    equity = initial_equity
    peak = initial_equity
    reconstructed_drawdown = Decimal("0")
    for item in validated_trades:
        equity += item["net_pnl"]
        peak, reconstructed_drawdown = _update_drawdown(
            equity=equity,
            peak=peak,
            max_drawdown=reconstructed_drawdown,
        )
    if decimals["max_drawdown_ratio"] < 0:
        raise ValueError("backtest evidence max_drawdown_ratio must be nonnegative")
    _require_decimal_match(
        "max_drawdown_ratio",
        decimals["max_drawdown_ratio"],
        reconstructed_drawdown,
    )
    profit_factor = None
    if "profit_factor" in result:
        profit_factor = _finite_decimal(result["profit_factor"], "profit_factor")
        gross_profit = sum(
            (item["gross_pnl"] for item in validated_trades if item["gross_pnl"] > 0),
            Decimal("0"),
        )
        gross_loss = -sum(
            (item["gross_pnl"] for item in validated_trades if item["gross_pnl"] < 0),
            Decimal("0"),
        )
        if gross_loss == 0 and gross_profit > 0:
            raise ValueError("backtest evidence profit_factor is unbounded without losing trades")
        expected_profit_factor = gross_profit / gross_loss if gross_loss else Decimal("0")
        _require_decimal_match("profit_factor", profit_factor, expected_profit_factor)

    feature_cache_hash = result["feature_cache_hash"]
    feature_config_hash = result["feature_config_hash"]
    feature_provenance = result["feature_provenance"]
    if not isinstance(feature_provenance, Mapping):
        raise ValueError("backtest evidence feature_provenance must be a mapping")
    if market_feature_provider is None:
        if feature_cache_hash is not None or feature_config_hash is not None or feature_provenance:
            raise ValueError("backtest evidence without a feature provider must use null feature identity")
    else:
        if not isinstance(feature_cache_hash, str) or not feature_cache_hash.strip():
            raise ValueError("backtest evidence feature_cache_hash is required")
        if feature_cache_hash != getattr(market_feature_provider, "feature_cache_hash", None):
            raise ValueError("backtest evidence feature_cache_hash mismatch")
        if not isinstance(feature_config_hash, str) or not feature_config_hash.strip():
            raise ValueError("backtest evidence feature_config_hash is required")
        if feature_config_hash != feature_provider_config_hash(market_feature_provider):
            raise ValueError("backtest evidence feature_config_hash mismatch")
        declared_provenance = getattr(market_feature_provider, "feature_provenance", None)
        if declared_provenance is not None and dict(feature_provenance) != dict(declared_provenance):
            raise ValueError("backtest evidence feature_provenance mismatch")

    validated_result = {
        "initial_equity": _decimal_text(initial_equity),
        "final_equity": _decimal_text(initial_equity + total_net),
        "trade_count": trade_count,
        "trades_per_day": _decimal_text(Decimal(trade_count) / Decimal("7")),
        "gross_pnl": _decimal_text(total_gross),
        "net_pnl": _decimal_text(total_net),
        "fee_paid": _decimal_text(total_fees),
        "return_ratio": _decimal_text(expected_return),
        "daily_return_ratio": _decimal_text(expected_return / Decimal("7")),
        "max_drawdown_ratio": _decimal_text(reconstructed_drawdown),
        "net_win_rate": _decimal_text(expected_win_rate),
        "average_net_trade_roe": _decimal_text(expected_average_roe),
        "average_net_trade_expectancy_ratio": _decimal_text(expected_expectancy),
        "trades": [item["payload"] for item in validated_trades],
        "feature_cache_hash": feature_cache_hash,
        "feature_provenance": dict(feature_provenance),
        "feature_config_hash": feature_config_hash,
    }
    if profit_factor is not None:
        validated_result["profit_factor"] = _decimal_text(profit_factor)
    return validated_result


def _validate_trade(
    value: object,
    index: int,
    *,
    episode: WeeklyEpisode,
    candidate: SchedulerBacktestCandidate,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"trade {index} must be a mapping")
    required = {
        "entry_at", "exit_at", "direction", "exit_reason", "holding_bars", *_TRADE_DECIMAL_FIELDS
    }
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"trade {index} missing required fields: {', '.join(missing)}")
    entry_at = _parse_canonical_utc(value["entry_at"], f"trade {index} entry_at")
    exit_at = _parse_canonical_utc(value["exit_at"], f"trade {index} exit_at")
    if not episode.start_at <= entry_at < exit_at <= episode.end_at:
        raise ValueError(f"trade {index} entry_at/exit_at must stay within the episode")
    if value["direction"] not in {"long", "short"}:
        raise ValueError(f"trade {index} direction is invalid")
    if not isinstance(value["exit_reason"], str) or not value["exit_reason"].strip():
        raise ValueError(f"trade {index} exit_reason is required")
    holding_bars = value["holding_bars"]
    if not isinstance(holding_bars, int) or isinstance(holding_bars, bool) or holding_bars < 0:
        raise ValueError(f"trade {index} holding_bars must be a nonnegative integer")
    elapsed_minutes = Decimal(str((exit_at - entry_at).total_seconds())) / Decimal("60")
    if elapsed_minutes != Decimal(holding_bars):
        raise ValueError(f"trade {index} holding_bars must match its positive 1m duration")
    decimals = {
        field: _finite_decimal(value[field], f"trade {index} {field}")
        for field in _TRADE_DECIMAL_FIELDS
    }
    for field in ("entry_price", "exit_price", "quantity", "margin"):
        if decimals[field] <= 0:
            raise ValueError(f"trade {index} {field} must be positive")
    if decimals["fee_paid"] < 0:
        raise ValueError(f"trade {index} fee_paid must be nonnegative")
    expected_gross = (
        (decimals["exit_price"] - decimals["entry_price"]) * decimals["quantity"]
        if value["direction"] == "long"
        else (decimals["entry_price"] - decimals["exit_price"]) * decimals["quantity"]
    )
    _require_decimal_match(
        f"trade {index} gross_pnl",
        decimals["gross_pnl"],
        expected_gross,
    )
    expected_fee = (
        decimals["entry_price"] * decimals["quantity"]
        + decimals["exit_price"] * decimals["quantity"]
    ) * FEE_RATE
    _require_decimal_match(
        f"trade {index} fee_paid",
        decimals["fee_paid"],
        expected_fee,
    )
    expected_margin = (
        decimals["entry_price"] * decimals["quantity"] / candidate.leverage
    )
    _require_decimal_match(
        f"trade {index} margin",
        decimals["margin"],
        expected_margin,
    )
    _require_decimal_match(
        f"trade {index} net_pnl",
        decimals["net_pnl"],
        decimals["gross_pnl"] - decimals["fee_paid"],
    )
    return {
        **decimals,
        "entry_at_value": entry_at,
        "exit_at_value": exit_at,
        "payload": {
            "entry_at": entry_at.isoformat(),
            "exit_at": exit_at.isoformat(),
            "entry_price": _decimal_text(decimals["entry_price"]),
            "exit_price": _decimal_text(decimals["exit_price"]),
            "direction": value["direction"],
            "quantity": _decimal_text(decimals["quantity"]),
            "margin": _decimal_text(decimals["margin"]),
            "gross_pnl": _decimal_text(decimals["gross_pnl"]),
            "net_pnl": _decimal_text(decimals["net_pnl"]),
            "fee_paid": _decimal_text(decimals["fee_paid"]),
            "exit_reason": value["exit_reason"],
            "holding_bars": holding_bars,
        },
    }


def _require_decimal_match(field: str, actual: Decimal, expected: Decimal) -> None:
    tolerance = Decimal("1e-24")
    if abs(actual - expected) > tolerance:
        raise ValueError(f"backtest evidence {field} is inconsistent")


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _finite_decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"backtest evidence {field} must be a serialized Decimal")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"backtest evidence {field} is not a Decimal") from error
    if not parsed.is_finite():
        raise ValueError(f"backtest evidence {field} must be finite")
    return parsed


def _parse_canonical_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO UTC timestamp") from error
    if parsed.tzinfo is not timezone.utc:
        raise ValueError(f"{field} must use canonical UTC")
    return parsed


def _is_canonical_utc(value: datetime) -> bool:
    return value.tzinfo is timezone.utc


def _is_monday_midnight(value: datetime) -> bool:
    return value.weekday() == 0 and value.time() == datetime.min.time()


# The production search space is declared at import time.  Validation may select
# from it, but neither validation nor Test is allowed to alter it.
@dataclass(frozen=True)
class WalkForwardGrid:
    cluster_counts: tuple[int, ...] = (3, 4, 5, 6, 7, 8)
    model_types: tuple[str, ...] = ("kmeans", "gmm")
    gmm_covariance_types: tuple[str, ...] = ("diag", "tied")
    seeds: tuple[int, ...] = (20260714, 20260715, 20260716)
    spearman_threshold: float = 0.95
    bootstrap_resamples: tuple[int, ...] = (2000, 5000)
    confidence_levels: tuple[float, ...] = (0.90, 0.95)
    gmm_probability_mins: tuple[float, ...] = (0.55, 0.65, 0.75)
    gmm_margin_mins: tuple[float, ...] = (0.05, 0.10, 0.20)
    kmeans_distance_multipliers: tuple[float, ...] = (0.90, 1.00, 1.10)


PRODUCTION_WALK_FORWARD_GRID = WalkForwardGrid()
MAPPING_GATE_THRESHOLDS = {
    "minimum_weekly_episodes": 8,
    "minimum_distinct_months": 3,
    "minimum_trade_count": 30,
}
MODEL_GATE_THRESHOLDS = {
    "minimum_cluster_episodes": 8,
    "minimum_cluster_months": 3,
    "minimum_seed_ari": 0.8,
    "minimum_seed_nmi": 0.8,
    "maximum_matched_centroid_distance": 0.5,
    "maximum_prevalence_drift": 0.2,
    "maximum_low_confidence_rate": 0.25,
}
COMPARISON_NAMES = (
    "cash",
    "adopted_fixed",
    "train_selected_fixed",
    "manual_regime_router",
    "kmeans_dynamic",
    "gmm_dynamic",
)
MANUAL_ROUTER_CANDIDATE_ID = "range-first-p2-tp0060-sl0045-e0035-l3-guard-a"


def _manual_router_candidate() -> SchedulerBacktestCandidate:
    matches = tuple(
        candidate for candidate in build_scheduler_candidates()
        if candidate.candidate_id == MANUAL_ROUTER_CANDIDATE_ID
    )
    if len(matches) != 1 or tuple(spec.kind for spec in matches[0].strategies) != ("regime_router",):
        raise ValueError("predeclared manual regime-router candidate is unavailable")
    return matches[0]


def _manual_router_for_replay(
    *, include_deferred: bool,
) -> tuple[SchedulerBacktestCandidate | None, str | None]:
    candidate = _manual_router_candidate()
    try:
        ensure_candidate_ids_allowed(
            (candidate.candidate_id,), include_deferred=include_deferred
        )
    except ValueError as error:
        return None, str(error)
    return candidate, None


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


BTCUSDT_FIRST_FOLD = RegimeWalkForwardFold(
    cluster_fit=UtcInterval(_utc("2021-01-01T00:00:00"), _utc("2025-06-30T00:00:00")),
    mapping_fit=UtcInterval(_utc("2025-07-07T00:00:00"), _utc("2026-01-05T00:00:00")),
    validation=UtcInterval(_utc("2026-01-12T00:00:00"), _utc("2026-03-30T00:00:00")),
    test=UtcInterval(_utc("2026-04-06T00:00:00"), _utc("2026-07-01T00:00:00")),
)


@dataclass(frozen=True)
class WalkForwardDependencies:
    """Stage boundary used by both production and deterministic fixture runs."""

    prepare_data: Callable[[Mapping[str, object]], Mapping[str, object]]
    build_cluster_features: Callable[[Mapping[str, object], Mapping[str, object]], Mapping[str, object]]
    evaluate_models: Callable[[Mapping[str, object], Mapping[str, object]], Mapping[str, object]]
    build_mappings: Callable[[Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object]], Mapping[str, object]]
    validate: Callable[[Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object]], Mapping[str, object]]
    replay_test: Callable[[Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object]], Mapping[str, object]]


@dataclass(frozen=True)
class WalkForwardInputs:
    """Validated, compact boundary between archive IO and statistical stages."""

    market: MarketSnapshot
    cluster_fit_vectors: tuple[object, ...]
    mapping_vectors: tuple[object, ...]
    validation_vectors: tuple[object, ...]
    data_provenance: Mapping[str, object]
    market_feature_provider: object | None = None


@dataclass(frozen=True)
class TestReplayInputs:
    """Test-only inputs whose loader may not run before artifact freeze."""

    market: MarketSnapshot
    data_provenance: Mapping[str, object]
    market_feature_provider: object | None = None


def _default_prepare_data(context: Mapping[str, object]) -> Mapping[str, object]:
    inputs = context.get("inputs")
    if not isinstance(inputs, WalkForwardInputs):
        raise RuntimeError(
            "validated WalkForwardInputs are required; CLI archive loading did not complete"
        )
    market = inputs.market
    if market.timeframe != TIMEFRAME or market.symbol.pair != context["symbol"]:
        raise ValueError("walk-forward input market identity mismatch")
    validation: UtcInterval = context["validation"]  # type: ignore[assignment]
    pretest_candles = tuple(candle for candle in market.candles if candle.closed_at <= validation.end_at)
    if not pretest_candles:
        raise ValueError("walk-forward market does not cover pre-Test intervals")
    return {
        "market": MarketSnapshot(pretest_candles),
        "provenance": dict(inputs.data_provenance),
        "provider": inputs.market_feature_provider,
        "cluster_fit_vectors": inputs.cluster_fit_vectors,
        "mapping_vectors": inputs.mapping_vectors,
        "validation_vectors": inputs.validation_vectors,
    }


def _default_build_cluster_features(
    context: Mapping[str, object], prepared: Mapping[str, object]
) -> Mapping[str, object]:
    cluster = tuple(prepared.get("cluster_fit_vectors", ()))
    mapping = tuple(prepared.get("mapping_vectors", ()))
    validation = tuple(prepared.get("validation_vectors", ()))
    if not cluster or not mapping or not validation:
        raise ValueError("cluster, mapping, and validation feature vectors are required")
    return {
        "schema": CHART_FEATURE_SCHEMA_VERSION,
        "cluster_fit": cluster,
        "mapping_fit": mapping,
        "validation": validation,
    }


def _model_report(artifact, config_id: str, *, eligible: bool, reasons=()):
    return {
        "config_id": config_id,
        "model_type": artifact.config.model_type if artifact is not None else config_id.split(":", 1)[0],
        "cluster_count": artifact.config.cluster_count if artifact is not None else None,
        "eligible": eligible,
        "artifact_hash": model_artifact_hash(artifact) if artifact is not None else None,
        "rejection_reasons": list(reasons),
    }


def _gmm_parameter_count(cluster_count: int, dimensions: int, covariance_type: str) -> int:
    if cluster_count < 1 or dimensions < 1:
        raise ValueError("GMM parameter dimensions must be positive")
    if covariance_type == "diag":
        covariance_parameters = cluster_count * dimensions
    elif covariance_type == "tied":
        covariance_parameters = dimensions * (dimensions + 1) // 2
    else:
        raise ValueError("GMM covariance type must be diag or tied")
    return (cluster_count - 1) + cluster_count * dimensions + covariance_parameters


def _gmm_bic(log_likelihood: float, sample_count: int, parameter_count: int) -> float:
    if not math.isfinite(log_likelihood) or sample_count < 1 or parameter_count < 1:
        raise ValueError("BIC inputs must be finite and positive")
    return float(-2 * log_likelihood + parameter_count * math.log(sample_count))


def _normalize_bounded_metric(
    value: float,
    name: str,
    minimum: float,
    maximum: float,
    *,
    tolerance: float = 1e-12,
) -> tuple[float, dict[str, object]]:
    raw = float(value)
    if not math.isfinite(raw):
        raise ValueError(f"{name} must be finite")
    if raw < minimum - tolerance or raw > maximum + tolerance:
        raise ValueError(
            f"{name}={raw!r} is outside [{minimum}, {maximum}] beyond tolerance {tolerance}"
        )
    normalized = min(max(raw, minimum), maximum)
    return normalized, {
        "raw": raw,
        "normalized": normalized,
        "clamped": normalized != raw,
    }


def _chronological_block_stability(
    engine: SklearnRegimeModel,
    primary,
    cluster_fit_vectors: tuple[object, ...],
    mapping_vectors: tuple[object, ...],
) -> tuple[float, float, list[dict[str, object]]]:
    """Refit disjoint chronological halves and compare standardized profiles."""
    midpoint = len(cluster_fit_vectors) // 2
    blocks = (cluster_fit_vectors[:midpoint], cluster_fit_vectors[midpoint:])
    if any(len(block) < primary.config.cluster_count for block in blocks):
        raise ValueError("chronological blocks are too small for requested clusters")
    block_artifacts = tuple(
        engine.fit(
            primary.config,
            tuple(block),
            retained_feature_names=primary.feature_names,
        )
        for block in blocks
    )
    profiles = []
    primary_means = np.asarray(primary.means)
    matched_label_series = []
    max_distance = 0.0
    for index, artifact in enumerate(block_artifacts):
        block_means = _project_centroids_to_primary_coordinates(artifact, primary)
        distances = np.linalg.norm(primary_means[:, None, :] - block_means[None, :, :], axis=2)
        rows, columns = linear_sum_assignment(distances)
        component_to_primary = {
            artifact.fingerprints[column]: primary.fingerprints[row]
            for row, column in zip(rows, columns)
        }
        matched = [float(distances[row, column]) for row, column in zip(rows, columns)]
        max_distance = max(max_distance, max(matched))
        assignments = engine.assign(artifact, mapping_vectors)
        matched_labels = [component_to_primary[item.fingerprint] for item in assignments]
        matched_label_series.append(matched_labels)
        profiles.append({
            "block_index": index,
            "start_at": blocks[index][0].anchor_at.isoformat(),
            "end_at": blocks[index][-1].anchor_at.isoformat(),
            "matched_standardized_centroid_distances": matched,
        })
    prevalence_drift = max(
        abs(
            matched_label_series[0].count(fingerprint) / len(mapping_vectors)
            - matched_label_series[1].count(fingerprint) / len(mapping_vectors)
        )
        for fingerprint in primary.fingerprints
    )
    return max_distance, prevalence_drift, profiles


def _project_centroids_to_primary_coordinates(block_artifact, primary_artifact) -> np.ndarray:
    if block_artifact.feature_names != primary_artifact.feature_names:
        raise ValueError("centroid projection requires identical feature profiles")
    block_standardized = np.asarray(block_artifact.means, dtype=float)
    raw_feature_units = (
        block_standardized * np.asarray(block_artifact.scales, dtype=float)
        + np.asarray(block_artifact.medians, dtype=float)
    )
    clipped_to_primary = np.clip(
        raw_feature_units,
        np.asarray(primary_artifact.lower_bounds, dtype=float),
        np.asarray(primary_artifact.upper_bounds, dtype=float),
    )
    return (
        clipped_to_primary - np.asarray(primary_artifact.medians, dtype=float)
    ) / np.asarray(primary_artifact.scales, dtype=float)


def _default_evaluate_models(
    context: Mapping[str, object], features: Mapping[str, object]
) -> Mapping[str, object]:
    grid: WalkForwardGrid = context["configuration_grid"]  # type: ignore[assignment]
    engine = SklearnRegimeModel()
    vectors = tuple(features["cluster_fit"])
    failed_reports = []
    structural = {}
    for model_type in grid.model_types:
        covariance_types = (None,) if model_type == "kmeans" else grid.gmm_covariance_types
        for cluster_count in grid.cluster_counts:
            for covariance_type in covariance_types:
                fitted = []
                config_prefix = f"{model_type}:{cluster_count}:{covariance_type or 'none'}"
                for seed in grid.seeds:
                    config_id = f"{config_prefix}:{seed}"
                    try:
                        artifact = engine.fit(
                            RegimeModelConfig(
                                model_type=model_type,
                                cluster_count=cluster_count,
                                random_seed=seed,
                                covariance_type=covariance_type,
                            ),
                            vectors,
                        )
                    except (TypeError, ValueError) as error:
                        failed_reports.append(_model_report(None, config_id, eligible=False, reasons=(str(error),)))
                        continue
                    fitted.append(artifact)
                if len(fitted) == len(grid.seeds):
                    structural[config_prefix] = tuple(fitted)
    mapping_vectors = tuple(
        vector for vector in features["mapping_fit"]
        if vector.anchor_at.weekday() == 0 and vector.anchor_at.hour == 0
    )
    if not mapping_vectors:
        raise ValueError("weekly Mapping Fit feature vectors are required")
    evidences = []
    evidence_by_id = {}
    chronological_profiles_by_id = {}
    seed_metric_audits_by_id = {}
    for config_id, seed_artifacts in sorted(structural.items()):
        primary = seed_artifacts[0]
        seed_assignments = [engine.assign(artifact, mapping_vectors) for artifact in seed_artifacts]
        primary_labels = [item.fingerprint for item in seed_assignments[0]]
        weekly_counts = tuple(primary_labels.count(fp) for fp in primary.fingerprints)
        month_sets = {fp: set() for fp in primary.fingerprints}
        for vector, label in zip(mapping_vectors, primary_labels):
            month_sets[label].add((vector.anchor_at.year, vector.anchor_at.month))
        month_counts = tuple(len(month_sets[fp]) for fp in primary.fingerprints)
        aris = []
        nmis = []
        metric_audits = []
        primary_label_hash = _canonical_hash(primary_labels)
        for seed_index, values in enumerate(seed_assignments[1:], start=1):
            comparison_labels = [item.fingerprint for item in values]
            comparison_hash = _canonical_hash(comparison_labels)
            try:
                ari, ari_audit = _normalize_bounded_metric(
                    adjusted_rand_score(primary_labels, comparison_labels),
                    "seed_ari", -1.0, 1.0,
                )
                nmi, nmi_audit = _normalize_bounded_metric(
                    normalized_mutual_info_score(primary_labels, comparison_labels),
                    "seed_nmi", 0.0, 1.0,
                )
            except ValueError as error:
                raise ValueError(
                    f"{config_id} seed_index={seed_index} primary_labels={primary_label_hash} "
                    f"comparison_labels={comparison_hash}: {error}"
                ) from error
            aris.append(ari)
            nmis.append(nmi)
            metric_audits.append({
                "seed_index": seed_index,
                "primary_label_hash": primary_label_hash,
                "comparison_label_hash": comparison_hash,
                "ari": ari_audit,
                "nmi": nmi_audit,
            })
        try:
            matched_centroid_distance, prevalence_drift, chronological_profiles = (
                _chronological_block_stability(
                    engine, primary, vectors, mapping_vectors
                )
            )
        except ValueError as error:
            failed_reports.append(
                _model_report(primary, config_id, eligible=False, reasons=(str(error),))
            )
            continue
        chronological_profiles_by_id[config_id] = chronological_profiles
        seed_metric_audits_by_id[config_id] = metric_audits
        low_confidence = sum(
            1
            for item in seed_assignments[0]
            if (
                item.distance is not None
                and item.distance > dict(zip(primary.fingerprints, primary.distance_thresholds))[item.fingerprint]
            )
            or (
                item.distance is None
                and (item.dominant_probability < 0.65 or item.dominant_probability - item.second_probability < 0.10)
            )
        ) / len(seed_assignments[0])
        names = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)
        indices = [names.index(name) for name in primary.feature_names]
        raw = np.asarray([[float(vector.values[name]) for name in names] for vector in mapping_vectors])[:, indices]
        scaled = (np.clip(raw, primary.lower_bounds, primary.upper_bounds) - np.asarray(primary.medians)) / np.asarray(primary.scales)
        labels_as_int = [primary.fingerprints.index(label) for label in primary_labels]
        silhouette = float(silhouette_score(scaled, labels_as_int)) if primary.config.model_type == "kmeans" and len(set(labels_as_int)) > 1 else None
        # Frozen artifact arrays are sufficient for deterministic family ranking;
        # BIC uses the standard -2 log-likelihood + p log(n) form with diagonal
        # Gaussian density (tied covariances are expanded in the artifact).
        bic = None
        if primary.config.model_type == "gmm":
            log_terms = []
            dimensions = scaled.shape[1]
            for row in scaled:
                components = []
                for weight, mean, covariance in zip(primary.weights, primary.means, primary.covariances):
                    cov = np.asarray(covariance)
                    matrix = np.diag(cov) if cov.size == dimensions else cov.reshape(dimensions, dimensions)
                    sign, logdet = np.linalg.slogdet(matrix)
                    delta = row - np.asarray(mean)
                    components.append(math.log(weight) - 0.5 * (dimensions * math.log(2 * math.pi) + logdet + delta @ np.linalg.solve(matrix, delta)))
                maximum = max(components)
                log_terms.append(maximum + math.log(sum(math.exp(value - maximum) for value in components)))
            parameter_count = _gmm_parameter_count(
                primary.config.cluster_count,
                dimensions,
                primary.config.covariance_type,
            )
            bic = _gmm_bic(sum(log_terms), len(scaled), parameter_count)
        evidence = RegimeModelEvidence(
            artifact_id=config_id, model_type=primary.config.model_type,
            cluster_fingerprints=primary.fingerprints,
            weekly_episode_counts=weekly_counts,
            distinct_calendar_month_counts=month_counts,
            seed_ari=min(aris), seed_nmi=min(nmis),
            matched_centroid_distance=matched_centroid_distance,
            prevalence_drift=prevalence_drift, low_confidence_rate=low_confidence,
            silhouette=silhouette, bic=bic,
        )
        evidences.append(evidence)
        evidence_by_id[config_id] = evidence
    selection = SelectRegimeModelUseCase().execute(SelectRegimeModelCommand(candidates=tuple(evidences)))
    decisions = {item.artifact_id: item for item in selection.decisions}
    candidates = failed_reports + [
        {
            **_model_report(structural[item.artifact_id][0], item.artifact_id, eligible=item.eligible, reasons=item.rejection_reasons),
            "evidence": {
                "weekly_episode_counts": list(evidence_by_id[item.artifact_id].weekly_episode_counts),
                "distinct_calendar_month_counts": list(evidence_by_id[item.artifact_id].distinct_calendar_month_counts),
                "seed_ari": evidence_by_id[item.artifact_id].seed_ari,
                "seed_nmi": evidence_by_id[item.artifact_id].seed_nmi,
                "seed_metric_normalization": seed_metric_audits_by_id[item.artifact_id],
                "matched_centroid_distance": evidence_by_id[item.artifact_id].matched_centroid_distance,
                "prevalence_drift": evidence_by_id[item.artifact_id].prevalence_drift,
                "low_confidence_rate": evidence_by_id[item.artifact_id].low_confidence_rate,
                "silhouette": evidence_by_id[item.artifact_id].silhouette,
                "bic": evidence_by_id[item.artifact_id].bic,
                "chronological_block_refits": chronological_profiles_by_id[item.artifact_id],
            },
        }
        for item in selection.decisions
    ]
    selected_artifacts = {
        winner.model_family: structural[winner.artifact_id][0]
        for winner in selection.family_winners
    }
    selected = {
        family: {
            "config_id": next(key for key, value in structural.items() if value[0] is artifact),
            "artifact_hash": model_artifact_hash(artifact),
            "fingerprint_hash": model_fingerprint_hash(artifact),
            "fingerprints": list(artifact.fingerprints),
        }
        for family, artifact in sorted(selected_artifacts.items())
    }
    return {"selected": selected, "candidates": candidates, "_artifacts": selected_artifacts}


def _selection_policy(artifact) -> SelectionConfidenceThresholds:
    if artifact.config.model_type == "kmeans":
        return SelectionConfidenceThresholds(
            model_type="kmeans",
            kmeans_max_standardized_distances=dict(
                zip(artifact.fingerprints, artifact.distance_thresholds)
            ),
        )
    return SelectionConfidenceThresholds(
        model_type="gmm", gmm_probability_min=0.65, gmm_margin_min=0.10
    )


def _mapping_report(artifact) -> dict[str, object]:
    return {
        "artifact_hash": mapping_artifact_hash(artifact),
        "bootstrap": {
            "resamples": artifact.bootstrap.resamples,
            "confidence": artifact.bootstrap.confidence,
            "block_length_weeks": artifact.bootstrap.block_length_weeks,
        },
        "entries": {
            fingerprint: {
                "decision": entry.decision,
                "strategy_profile_id": entry.strategy_profile_id,
                "weekly_episode_count": entry.weekly_episode_count,
                "distinct_month_count": entry.distinct_month_count,
                "closed_trade_count": entry.closed_trade_count,
                "corrected_lower_bound": entry.corrected_lower_bound,
                "metrics": dict(entry.metrics),
                "rejection_reasons": list(entry.rejection_reasons),
            }
            for fingerprint, entry in sorted(artifact.entries.items())
        },
        "candidate_assessments": {
            fingerprint: {
                candidate_id: {
                    "candidate_hash": assessment.candidate_hash,
                    "eligible": assessment.eligible,
                    "weekly_episode_count": assessment.weekly_episode_count,
                    "distinct_month_count": assessment.distinct_month_count,
                    "closed_trade_count": assessment.closed_trade_count,
                    "corrected_lower_bound": assessment.corrected_lower_bound,
                    "observed_mean": assessment.observed_mean,
                    "metrics": dict(assessment.metrics),
                    "rejection_reasons": list(assessment.rejection_reasons),
                }
                for candidate_id, assessment in sorted(assessments.items())
            }
            for fingerprint, assessments in sorted(artifact.candidate_assessments.items())
        },
    }


def _combine_requirement_alternatives(
    groups: Sequence[tuple[dict[str, tuple[str, ...]], ...]],
) -> tuple[dict[str, tuple[str, ...]], ...]:
    combined = ({},)
    for alternatives in groups:
        expanded = []
        for left in combined:
            for right in alternatives:
                merged = dict(left)
                for name, sources in right.items():
                    merged[name] = tuple(sorted(set(merged.get(name, ())) | set(sources)))
                expanded.append(merged)
        combined = tuple(expanded)
    unique = {
        tuple((name, tuple(sources)) for name, sources in sorted(item.items())): item
        for item in combined
    }
    return tuple(unique[key] for key in sorted(unique))


def _strategy_feature_requirements(
    strategy: object,
) -> tuple[dict[str, tuple[str, ...]], ...]:
    direct = getattr(strategy, "required_features", None)
    if isinstance(direct, Mapping):
        return ({name: tuple(sources) for name, sources in direct.items()},)
    inner = getattr(strategy, "inner", None)
    if inner is not None:
        return _strategy_feature_requirements(inner)
    children = getattr(strategy, "children", ())
    if children:
        return _combine_requirement_alternatives(
            tuple(_strategy_feature_requirements(child) for child in children)
        )
    name = type(strategy).__name__
    if name == "FlowExhaustionReversalStrategy":
        return ({
            "taker_imbalance": tuple(strategy.taker_imbalance_sources),
            "cvd_delta": tuple(strategy.cvd_delta_sources),
        },)
    if name in {"OpenInterestImpulseStrategy", "OpenInterestDivergenceStrategy"}:
        return ({
            "open_interest_change_ratio_5m": ("metrics",),
            "taker_long_short_volume_ratio": ("metrics",),
        },)
    if name == "PositioningCrowdingReversalStrategy":
        return ({
            "top_trader_position_long_short_ratio": ("metrics",),
            "global_long_short_ratio": ("metrics",),
            "taker_long_short_volume_ratio": ("metrics",),
        },)
    if name == "GlobalRatioShockReversalStrategy":
        return ({"global_long_short_change_5m": ("metrics",)},)
    if name == "PremiumFundingReversionStrategy":
        flow = {
            "taker_imbalance": tuple(strategy.taker_imbalance_sources),
            "cvd_delta": tuple(strategy.cvd_delta_sources),
        }
        return (
            {**flow, "premium_index": tuple(strategy.premium_sources)},
            {
                **flow,
                "mark_price": tuple(strategy.mark_sources),
                "index_price": tuple(strategy.index_sources),
            },
        )
    if name == "SessionOpeningRangeStrategy":
        return ({
            "taker_imbalance": tuple(strategy.taker_imbalance_sources),
            "cvd_delta": tuple(strategy.cvd_delta_sources),
            "trade_intensity": tuple(strategy.trade_intensity_sources),
        },)
    return ({},)


def _candidate_feature_requirements(
    candidate: SchedulerBacktestCandidate,
) -> tuple[dict[str, tuple[str, ...]], ...]:
    try:
        strategies = build_strategies(candidate)
    except ValueError:
        return ({},)
    return _combine_requirement_alternatives(
        tuple(_strategy_feature_requirements(strategy) for strategy in strategies)
    )


def _mapping_feature_coverage(
    market: MarketSnapshot,
    episodes: tuple[WeeklyEpisode, ...],
    candidates: tuple[SchedulerBacktestCandidate, ...],
    provider: object | None,
) -> tuple[dict[str, set[datetime]], dict[str, object]]:
    valid: dict[str, set[datetime]] = {}
    reports = {}
    cache = {}
    for candidate in candidates:
        alternatives = _candidate_feature_requirements(candidate)
        signature = tuple(
            tuple((name, sources) for name, sources in sorted(requirements.items()))
            for requirements in alternatives
        )
        valid[candidate.candidate_id] = set()
        episode_reports = []
        for episode in episodes:
            key = (signature, episode.start_at)
            if key not in cache:
                expected = 7 * 24 * 60
                if alternatives == ({},):
                    cache[key] = (True, expected, None)
                elif provider is None:
                    cache[key] = (False, 0, "market feature provider unavailable")
                else:
                    available = 0
                    missing_reason = None
                    for candle in market.candles:
                        if not episode.start_at <= candle.opened_at < episode.end_at:
                            continue
                        as_of = candle.closed_at
                        feature_set = provider.load_features(market.symbol, market.timeframe, as_of)
                        missing_by_alternative = []
                        for requirements in alternatives:
                            missing = []
                            for feature_name, allowed_sources in requirements.items():
                                value = feature_set.get(feature_name)
                                if (
                                    value is None
                                    or value.source not in allowed_sources
                                    or value.available_at > as_of
                                ):
                                    missing.append(feature_name)
                            missing_by_alternative.append(missing)
                        if all(missing_by_alternative):
                            missing_reason = (
                                f"missing point-in-time alternatives at {as_of.isoformat()}: "
                                + " OR ".join(
                                    ",".join(sorted(missing))
                                    for missing in missing_by_alternative
                                )
                            )
                            break
                        available += 1
                    cache[key] = (available == expected, available, missing_reason)
            is_valid, available_minutes, reason = cache[key]
            if is_valid:
                valid[candidate.candidate_id].add(episode.start_at)
            episode_reports.append({
                "episode_start_at": episode.start_at.isoformat(),
                "expected_minutes": 7 * 24 * 60,
                "available_minutes": available_minutes,
                "eligible": is_valid,
                "rejection_reason": reason,
            })
        reports[candidate.candidate_id] = {
            "required_alternatives": [
                {name: list(sources) for name, sources in requirements.items()}
                for requirements in alternatives
            ],
            "eligible_episode_count": len(valid[candidate.candidate_id]),
            "rejected_episode_count": len(episodes) - len(valid[candidate.candidate_id]),
            "episodes": episode_reports,
        }
    return valid, reports


def _run_mapping_coverage_filtered_evidence(
    market: MarketSnapshot,
    *,
    episodes: tuple[WeeklyEpisode, ...],
    assignments: Mapping[datetime, str],
    candidates: tuple[SchedulerBacktestCandidate, ...],
    valid_episodes: Mapping[str, set[datetime]],
    market_feature_provider: object | None,
) -> list[dict[str, object]]:
    rows = []
    for episode in episodes:
        eligible = tuple(
            candidate for candidate in candidates
            if episode.start_at in valid_episodes[candidate.candidate_id]
        )
        if not eligible:
            continue
        rows.extend(
            run_mapping_episodes(
                market,
                episodes=(episode,),
                assignments={episode.anchor_at: assignments[episode.anchor_at]},
                candidates=eligible,
                market_feature_provider=market_feature_provider,
            )
        )
    return rows


def _default_build_mappings(
    context: Mapping[str, object],
    prepared: Mapping[str, object],
    features: Mapping[str, object],
    models: Mapping[str, object],
) -> Mapping[str, object]:
    artifacts = dict(models.get("_artifacts", {}))
    if not artifacts:
        return {"selected": {}, "_artifacts": {}, "mapping_metrics": {"status": "cash_only"}}
    mapping_interval: UtcInterval = context["mapping_fit"]  # type: ignore[assignment]
    episodes = tuple(build_weekly_episodes(mapping_interval.start_at, mapping_interval.end_at))
    engine = SklearnRegimeModel()
    mapping_vectors = {vector.anchor_at: vector for vector in features["mapping_fit"]}
    assignments_by_family = {}
    for family, artifact in artifacts.items():
        episode_vectors = tuple(mapping_vectors[episode.anchor_at] for episode in episodes)
        assigned = engine.assign(artifact, episode_vectors)
        assignments_by_family[family] = {
            episode.anchor_at: assignment.fingerprint
            for episode, assignment in zip(episodes, assigned)
        }
    # Candidate evidence is independent of cluster/model. Execute it once, then
    # replace only the assignment label for each frozen model family.
    reference = next(iter(assignments_by_family.values()))
    resolved_candidates = tuple(context["candidates"])
    valid_episodes, feature_coverage = _mapping_feature_coverage(
        prepared["market"], episodes, resolved_candidates, prepared.get("provider")
    )
    evidence = _run_mapping_coverage_filtered_evidence(
        prepared["market"], episodes=episodes, assignments=reference,
        candidates=resolved_candidates, valid_episodes=valid_episodes,
        market_feature_provider=prepared.get("provider"),
    )
    if not evidence:
        return {
            "selected": {}, "_artifacts": {},
            "feature_coverage": feature_coverage,
            "mapping_metrics": {"status": "cash_only", "evidence_rows": 0},
        }
    by_key = {(row["episode_start_at"], row["candidate_id"]): row for row in evidence}
    mapping_artifacts = {}
    reports = {}
    grid: WalkForwardGrid = context["configuration_grid"]  # type: ignore[assignment]
    for family, model_artifact in artifacts.items():
        family_rows = []
        assignment = assignments_by_family[family]
        for episode in episodes:
            for candidate in context["candidates"]:
                key = (episode.start_at.isoformat(), candidate.candidate_id)
                if key not in by_key:
                    continue
                row = dict(by_key[key])
                row["cluster_fingerprint"] = assignment[episode.anchor_at]
                family_rows.append(row)
        family_artifacts = {}
        family_reports = {}
        for resamples in grid.bootstrap_resamples:
            for confidence in grid.confidence_levels:
                mapping_config_id = f"bootstrap:{resamples}:confidence:{confidence}"
                result = BuildStrategyMappingUseCase().execute(
                    BuildStrategyMappingCommand(
                        evidence_rows=tuple(family_rows),
                        regime_model_artifact_hash=model_artifact_hash(model_artifact),
                        regime_model_fingerprint_hash=model_fingerprint_hash(model_artifact),
                        selection_confidence_thresholds=_selection_policy(model_artifact),
                        bootstrap_resamples=resamples,
                        confidence=Decimal(str(confidence)),
                    )
                )
                family_artifacts[mapping_config_id] = result.artifact
                family_reports[mapping_config_id] = _mapping_report(result.artifact)
        mapping_artifacts[family] = family_artifacts
        reports[family] = family_reports
    global_rows = [dict(row, cluster_fingerprint="all") for row in evidence]
    global_mapping = BuildStrategyMappingUseCase().execute(
        BuildStrategyMappingCommand(
            evidence_rows=tuple(global_rows),
            regime_model_artifact_hash="0" * 64,
            regime_model_fingerprint_hash="1" * 64,
            selection_confidence_thresholds=SelectionConfidenceThresholds(
                model_type="gmm", gmm_probability_min=0.65, gmm_margin_min=0.10
            ),
            bootstrap_resamples=grid.bootstrap_resamples[0],
            confidence=Decimal(str(grid.confidence_levels[-1])),
        )
    ).artifact
    global_entry = global_mapping.entries["all"]
    return {
        "selected": reports,
        "_artifacts": mapping_artifacts,
        "train_selected_candidate_id": global_entry.strategy_profile_id,
        "train_selected_decision": global_entry.decision,
        "feature_coverage": feature_coverage,
        "mapping_metrics": {"weekly_episode_count": len(episodes), "evidence_rows": len(evidence)},
    }


def _default_validate(
    context: Mapping[str, object], prepared: Mapping[str, object], features: Mapping[str, object],
    models: Mapping[str, object], mappings: Mapping[str, object],
) -> Mapping[str, object]:
    model_objects = dict(models.get("_artifacts", {}))
    mapping_objects = dict(mappings.get("_artifacts", {}))
    available = sorted(set(model_objects) & set(mapping_objects))
    if not available:
        return {"status": "cash_only", "selected_family": None, "candidates": [], "_mapping_artifacts": {}}
    interval: UtcInterval = context["validation"]  # type: ignore[assignment]
    grid: WalkForwardGrid = context["configuration_grid"]  # type: ignore[assignment]
    candidates = tuple(context["candidates"])
    provider = prepared.get("provider")
    scored = []
    selected_by_family = {}
    selected_models = {}
    for family in available:
        model_artifact = model_objects[family]
        policies = []
        if family == "gmm":
            for probability in grid.gmm_probability_mins:
                for margin in grid.gmm_margin_mins:
                    policies.append((f"gmm:p{probability}:m{margin}", model_artifact, SelectionConfidenceThresholds(model_type="gmm", gmm_probability_min=probability, gmm_margin_min=margin)))
        else:
            for multiplier in grid.kmeans_distance_multipliers:
                distance_model = replace(
                    model_artifact,
                    distance_thresholds=tuple(value * multiplier for value in model_artifact.distance_thresholds),
                )
                policies.append((
                    f"kmeans:d{multiplier}",
                    distance_model,
                    SelectionConfidenceThresholds(
                        model_type="kmeans",
                        kmeans_max_standardized_distances={
                            fingerprint: threshold
                            for fingerprint, threshold in zip(distance_model.fingerprints, distance_model.distance_thresholds)
                        },
                    ),
                ))
        family_scores = []
        for mapping_config_id, base_mapping in sorted(mapping_objects[family].items()):
            audited_candidates = tuple(
                candidate for candidate in candidates
                if candidate.candidate_id in base_mapping.candidate_hashes
            )
            for policy_config_id, candidate_model, policy in policies:
                config_id = f"{mapping_config_id}:{policy_config_id}"
                candidate_mapping = replace(
                    base_mapping,
                    regime_model_artifact_hash=model_artifact_hash(candidate_model),
                    regime_model_fingerprint_hash=model_fingerprint_hash(candidate_model),
                    selection_confidence_thresholds=policy,
                )
                replay = run_scheduler_driven_regime_backtest(
                    prepared["market"], start_at=interval.start_at, end_at=interval.end_at,
                    candidates=audited_candidates, model_artifact=candidate_model,
                    mapping_artifact=candidate_mapping, market_feature_provider=provider,
                    include_deferred=bool(context["include_deferred"]),
                )
                continuous_return = Decimal(str(replay.get("return_ratio", "0")))
                drawdown = Decimal(str(replay.get("max_drawdown_ratio", "0")))
                turnover = Decimal(str(replay.get("turnover", replay.get("strategy_turnover", "0"))))
                record = {
                    "family": family, "config_id": config_id,
                    "mapping_config_id": mapping_config_id,
                    "policy_config_id": policy_config_id,
                    "return_ratio": _decimal_text(continuous_return),
                    "max_drawdown_ratio": _decimal_text(drawdown),
                    "turnover": _decimal_text(turnover),
                    "mapping_artifact_hash": mapping_artifact_hash(candidate_mapping),
                    "_artifact": candidate_mapping,
                    "_model_artifact": candidate_model,
                }
                scored.append(record)
                family_scores.append(record)
        winner = min(
            family_scores,
            key=lambda item: (
                -Decimal(item["return_ratio"]), Decimal(item["max_drawdown_ratio"]),
                Decimal(item["turnover"]), item["config_id"],
            ),
        )
        selected_by_family[family] = winner["_artifact"]
        selected_models[family] = winner["_model_artifact"]
    overall = min(
        (item for item in scored if selected_by_family[item["family"]] is item["_artifact"]),
        key=lambda item: (-Decimal(item["return_ratio"]), Decimal(item["max_drawdown_ratio"]), Decimal(item["turnover"]), item["config_id"]),
    )
    return {
        "status": "selected", "selected_family": overall["family"],
        "selected_config_id": overall["config_id"],
        "score_order": "net_return_desc,max_drawdown_asc,turnover_asc,config_id_asc",
        "candidates": [{key: value for key, value in item.items() if not key.startswith("_artifact") and key != "_model_artifact"} for item in scored],
        "_mapping_artifacts": selected_by_family,
        "_model_artifacts": selected_models,
    }


def _cash_comparison(reason: str | None = None) -> dict[str, object]:
    result = {
        "status": "cash",
        "continuous_metrics": {"return_ratio": "0", "max_drawdown_ratio": "0", "trade_count": 0},
    }
    if reason:
        result["rejection_reasons"] = [reason]
    return result


def _continuous_diagnostics(comparisons: Mapping[str, object]) -> dict[str, object]:
    report = {}
    for name in COMPARISON_NAMES:
        comparison = comparisons.get(name, {})
        metrics = comparison.get("continuous_metrics", {}) if isinstance(comparison, Mapping) else {}
        if not isinstance(metrics, Mapping):
            metrics = {}
        trades = metrics.get("trades", ())
        trades = trades if isinstance(trades, (tuple, list)) else ()
        positive = sorted(
            (Decimal(str(item.get("net_pnl", "0"))) for item in trades if Decimal(str(item.get("net_pnl", "0"))) > 0),
            reverse=True,
        )
        positive_total = sum(positive, Decimal(0))
        owners = {}
        for trade in trades:
            owner = trade.get("owner_strategy_profile_id") or comparison.get("candidate_id") or "unknown"
            owners[owner] = owners.get(owner, 0) + 1
        total_bars = int(metrics.get("cash_bars", 0)) + sum(
            int(value) for value in metrics.get("time_in_cluster_bars", {}).values()
        ) if isinstance(metrics.get("time_in_cluster_bars", {}), Mapping) else int(metrics.get("cash_bars", 0))
        report[name] = {
            "cash_contribution": {
                "cash_bars": int(metrics.get("cash_bars", 0)),
                "cash_bar_share": (
                    str(Decimal(int(metrics.get("cash_bars", 0))) / Decimal(total_bars))
                    if total_bars else "0"
                ),
                "entries_while_cash": int(metrics.get("entries_while_cash", 0)),
            },
            "confidence": {
                "assignment_count": len(metrics.get("confidence_diagnostics", ())),
                "diagnostics": metrics.get("confidence_diagnostics", ()),
            },
            "transitions": metrics.get("transition_counts", {}),
            "actual_turnover_notional": metrics.get("actual_turnover_notional", "0"),
            "signal_discontinuity_count": metrics.get("signal_discontinuity_count", 0),
            "concentration": {
                "top_5_positive_trade_pnl_share": (
                    str(sum(positive[:5], Decimal(0)) / positive_total) if positive_total else "0"
                ),
                "strategy_trade_shares": {
                    owner: str(Decimal(count) / Decimal(len(trades)))
                    for owner, count in sorted(owners.items())
                } if trades else {},
                "single_fold_return_share": "1" if trades else "0",
            },
        }
    return report


def _default_replay_test(
    context: Mapping[str, object], prepared: Mapping[str, object], features: Mapping[str, object],
    models: Mapping[str, object], mappings: Mapping[str, object], validation: Mapping[str, object],
) -> Mapping[str, object]:
    test: UtcInterval = context["test"]  # type: ignore[assignment]
    market = prepared["market"]
    candidates = tuple(context["candidates"])
    provider = prepared.get("provider")
    results = {name: _cash_comparison() for name in COMPARISON_NAMES}
    adopted = default_candidate()
    adopted_result = run_scheduler_driven_backtest(
        market,
        context_start_at=test.start_at - timedelta(
            minutes=required_warmup_candles((adopted,), provider)
        ),
        start_at=test.start_at,
        end_at=test.end_at,
        candidate=adopted,
        market_feature_provider=provider,
        include_deferred=bool(context["include_deferred"]),
        include_trade_details=True,
        force_close_at_end=True,
    )
    results["adopted_fixed"] = {
        "status": "ok",
        "candidate_id": adopted.candidate_id,
        "continuous_metrics": adopted_result,
    }
    mapping_objects = dict(mappings.get("_artifacts", {}))
    model_objects = dict(models.get("_artifacts", {}))
    train_selected_id = mappings.get("train_selected_candidate_id")
    if train_selected_id is not None:
        selected = next(item for item in candidates if item.candidate_id == train_selected_id)
        fixed = run_scheduler_driven_backtest(
            market,
            context_start_at=test.start_at - timedelta(
                minutes=required_warmup_candles((selected,), provider)
            ),
            start_at=test.start_at,
            end_at=test.end_at,
            candidate=selected,
            market_feature_provider=provider,
            include_deferred=bool(context["include_deferred"]),
            include_trade_details=True,
            force_close_at_end=True,
        )
        results["train_selected_fixed"] = {
            "status": "ok",
            "candidate_id": selected.candidate_id,
            "continuous_metrics": fixed,
        }
    else:
        results["train_selected_fixed"] = _cash_comparison(
            mappings.get("skipped_reason", "mapping-fit statistical gate selected cash")
        )
    manual_router, manual_unavailable = _manual_router_for_replay(
        include_deferred=bool(context["include_deferred"])
    )
    if manual_router is None:
        results["manual_regime_router"] = _cash_comparison(manual_unavailable)
        results["manual_regime_router"]["status"] = "unavailable"
        results["manual_regime_router"]["router_rule"] = (
            "existing_hand_authored_regime_router"
        )
    else:
        manual_result = run_scheduler_driven_backtest(
            market,
            context_start_at=test.start_at - timedelta(
                minutes=required_warmup_candles((manual_router,), provider)
            ),
            start_at=test.start_at, end_at=test.end_at, candidate=manual_router,
            market_feature_provider=provider,
            include_deferred=bool(context["include_deferred"]),
            include_trade_details=True,
            force_close_at_end=True,
        )
        results["manual_regime_router"] = {
            "status": "ok",
            "router_rule": "existing_hand_authored_regime_router",
            "candidate_id": manual_router.candidate_id,
            "continuous_metrics": manual_result,
        }
    for family in ("kmeans", "gmm"):
        if family not in mapping_objects or family not in model_objects:
            results[f"{family}_dynamic"] = _cash_comparison("no frozen eligible artifact")
            continue
        selector_callback = context.get("on_test_selector_invoked")
        if callable(selector_callback):
            selector_callback(family)
        replay = run_scheduler_driven_regime_backtest(
            market,
            start_at=test.start_at,
            end_at=test.end_at,
            candidates=tuple(
                candidate for candidate in candidates
                if candidate.candidate_id in mapping_objects[family].candidate_hashes
            ),
            model_artifact=model_objects[family],
            mapping_artifact=mapping_objects[family],
            market_feature_provider=provider,
            include_deferred=bool(context["include_deferred"]),
        )
        results[f"{family}_dynamic"] = {
            "status": "ok",
            "continuous_metrics": replay,
        }
    return results


DEFAULT_WALK_FORWARD_DEPENDENCIES = WalkForwardDependencies(
    _default_prepare_data,
    _default_build_cluster_features,
    _default_evaluate_models,
    _default_build_mappings,
    _default_validate,
    _default_replay_test,
)


def _fold_payload(fold: RegimeWalkForwardFold) -> dict[str, object]:
    intervals = {}
    for name in ("cluster_fit", "mapping_fit", "validation", "test"):
        interval = getattr(fold, name)
        intervals[name] = {"start_at": interval.start_at.isoformat(), "end_at": interval.end_at.isoformat()}
    intervals["purges"] = [
        {
            "start_at": earlier.end_at.isoformat(),
            "end_at": later.start_at.isoformat(),
            "days": (later.start_at - earlier.end_at).days,
        }
        for earlier, later in zip(
            (fold.cluster_fit, fold.mapping_fit, fold.validation),
            (fold.mapping_fit, fold.validation, fold.test),
        )
    ]
    return intervals


def _grid_payload(grid: WalkForwardGrid) -> dict[str, object]:
    return {
        "cluster_counts": list(grid.cluster_counts),
        "model_types": list(grid.model_types),
        "gmm_covariance_types": list(grid.gmm_covariance_types),
        "seeds": list(grid.seeds),
        "spearman_threshold": grid.spearman_threshold,
        "bootstrap_resamples": list(grid.bootstrap_resamples),
        "confidence_levels": list(grid.confidence_levels),
        "gmm_probability_mins": list(grid.gmm_probability_mins),
        "gmm_margin_mins": list(grid.gmm_margin_mins),
        "kmeans_distance_multipliers": list(grid.kmeans_distance_multipliers),
    }


def _resolve_walk_forward_candidates(
    *,
    candidates: Sequence[SchedulerBacktestCandidate] | None,
    candidate_groups: Sequence[str],
    include_deferred: bool,
) -> tuple[tuple[SchedulerBacktestCandidate, ...], dict[str, str]]:
    built: list[SchedulerBacktestCandidate] = []
    if candidates is not None:
        if candidate_groups:
            raise ValueError("direct candidates cannot be combined with candidate groups")
        built.extend(candidates)
    else:
        if not candidate_groups:
            raise ValueError("at least one candidate group is required")
        for group in candidate_groups:
            if group not in _CANDIDATE_FACTORIES:
                raise ValueError(f"unknown candidate group: {group}")
            ensure_candidate_group_allowed(group, include_deferred=include_deferred)
            built.extend(_CANDIDATE_FACTORIES[group]())
    if not built:
        raise ValueError("candidate set cannot be empty")
    by_id: dict[str, SchedulerBacktestCandidate] = {}
    hashes: dict[str, str] = {}
    for candidate in built:
        behavior_hash = _canonical_hash(_candidate_behavior_payload(candidate))
        previous = hashes.get(candidate.candidate_id)
        if previous is not None and previous != behavior_hash:
            raise ValueError(f"conflicting candidate definition: {candidate.candidate_id}")
        hashes[candidate.candidate_id] = behavior_hash
        by_id.setdefault(candidate.candidate_id, candidate)
    ordered = tuple(by_id[key] for key in sorted(by_id))
    ensure_candidate_ids_allowed(tuple(item.candidate_id for item in ordered), include_deferred=include_deferred)
    return ordered, dict(sorted(hashes.items()))


def run_chart_regime_walk_forward(
    fold: RegimeWalkForwardFold,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    candidate_groups: Sequence[str] = (),
    include_deferred: bool = False,
    candidates: Sequence[SchedulerBacktestCandidate] | None = None,
    dependencies: WalkForwardDependencies = DEFAULT_WALK_FORWARD_DEPENDENCIES,
    inputs: WalkForwardInputs | None = None,
    test_input_loader: Callable[[], TestReplayInputs] | None = None,
    progress: Callable[[str], None] | None = None,
    fixture_grid: WalkForwardGrid | None = None,
    output_json: Path | None = None,
    output_markdown: Path | None = None,
    output_model: Path | None = None,
    output_mapping: Path | None = None,
    test_claim_status: str = "untouched",
    test_claim_reason: str | None = None,
    prior_run_timestamp: str | None = None,
    prior_run_hash: str | None = None,
) -> dict[str, object]:
    """Run one leakage-guarded four-interval pipeline.

    Test access exists in exactly one stage and is structurally after both freeze
    events.  Stage dependencies receive the same context in production and tests.
    """
    if symbol != "BTCUSDT" or timeframe != "1m":
        raise ValueError("the first walk-forward pipeline supports BTCUSDT 1m only")
    if test_claim_status not in {"untouched", "diagnostic_after_pipeline_defect"}:
        raise ValueError("unknown Test claim status")
    prior_fields = (test_claim_reason, prior_run_timestamp, prior_run_hash)
    if test_claim_status == "diagnostic_after_pipeline_defect":
        if any(not value for value in prior_fields):
            raise ValueError("diagnostic Test claim requires reason, prior timestamp, and prior hash")
        _parse_canonical_utc(prior_run_timestamp, "prior run timestamp")
        if len(prior_run_hash) != 64 or any(char not in "0123456789abcdef" for char in prior_run_hash):
            raise ValueError("prior run hash must be lowercase SHA-256")
    elif any(value is not None for value in prior_fields):
        raise ValueError("prior exposure audit fields require diagnostic Test claim status")
    if not isinstance(fold, RegimeWalkForwardFold):
        raise ValueError("fold must be a RegimeWalkForwardFold")
    purges = (
        fold.mapping_fit.start_at - fold.cluster_fit.end_at,
        fold.validation.start_at - fold.mapping_fit.end_at,
        fold.test.start_at - fold.validation.end_at,
    )
    if any(value != _WEEK for value in purges):
        raise ValueError("every fold boundary purge must be exactly seven days")
    selected_candidates, candidate_hashes = _resolve_walk_forward_candidates(
        candidates=candidates,
        candidate_groups=candidate_groups,
        include_deferred=include_deferred,
    )
    grid = fixture_grid or PRODUCTION_WALK_FORWARD_GRID
    events: list[str] = []
    access_audit: list[dict[str, str]] = []

    def emit(name: str) -> None:
        events.append(name)
        if progress is not None:
            progress(name)

    # Deliberately omit the Test interval from every fit/scoring dependency.
    # Merely asking a data loader for that slice early is leakage, even when the
    # caller promises not to inspect the returned candles.
    context = {
        "symbol": symbol,
        "timeframe": timeframe,
        "cluster_fit": fold.cluster_fit,
        "mapping_fit": fold.mapping_fit,
        "validation": fold.validation,
        "configuration_grid": grid,
        "candidates": selected_candidates,
        "candidate_hashes": candidate_hashes,
        "include_deferred": include_deferred,
        "data_access_audit": access_audit,
        "inputs": inputs,
    }
    prepared = dict(dependencies.prepare_data(context))
    access_audit.extend({"interval": name, "stage": "data_prepared"} for name in ("cluster_fit", "mapping_fit", "validation"))
    emit("data_prepared")
    features = dict(dependencies.build_cluster_features(context, prepared))
    emit("cluster_features_ready")
    models = dict(dependencies.evaluate_models(context, features))
    for candidate in models.get("candidates", ()):
        emit(f"model_candidate:{candidate.get('config_id', 'unknown')}")
    if models.get("selected"):
        mappings = dict(dependencies.build_mappings(context, prepared, features, models))
        emit("mapping_evidence_ready")
    else:
        mappings = {
            "selected": {},
            "_artifacts": {},
            "mapping_metrics": {"status": "not_evaluated_no_eligible_model"},
            "skipped_reason": "not evaluated: no eligible model",
        }
        emit("mapping_skipped_no_eligible_model")
    validation = dict(dependencies.validate(context, prepared, features, models, mappings))
    frozen_policy_artifacts = validation.pop("_mapping_artifacts", None)
    frozen_policy_models = validation.pop("_model_artifacts", None)
    if frozen_policy_models is not None:
        models["_artifacts"] = frozen_policy_models
        models["selected"] = {
            family: {
                "config_id": f"validation:{family}",
                "artifact_hash": model_artifact_hash(artifact),
                "fingerprint_hash": model_fingerprint_hash(artifact),
                "fingerprints": list(artifact.fingerprints),
            }
            for family, artifact in sorted(frozen_policy_models.items())
        }
    if frozen_policy_artifacts is not None:
        mappings["_artifacts"] = frozen_policy_artifacts
        mappings["selected"] = {
            family: _mapping_report(artifact)
            for family, artifact in sorted(frozen_policy_artifacts.items())
        }
    emit("validation_result")
    model_frozen = _canonical_hash(models.get("selected", {}))
    emit("model_frozen")
    mapping_frozen = _canonical_hash({"selected": mappings.get("selected", {}), "validation": validation})
    emit("mapping_frozen")

    if any(item["interval"] == "test" for item in access_audit):
        raise RuntimeError("Test interval was accessed before artifacts were frozen")
    test_inputs = test_input_loader() if test_input_loader is not None else None
    if test_inputs is not None:
        access_audit.append({"interval": "test", "stage": "test_data_loaded"})
        emit("test_data_prepared")
    selector_invoked = False
    selector_family = None

    def mark_test_selector_invoked(family: str) -> None:
        nonlocal selector_invoked, selector_family
        if selector_invoked:
            return
        selector_invoked = True
        selector_family = family
        access_audit.append({"interval": "test", "stage": "test_selector_invoked"})
        emit("first_test_classification")

    test_context = {
        **context,
        "test": fold.test,
        "on_test_selector_invoked": mark_test_selector_invoked,
    }
    test_prepared = dict(prepared)
    if test_inputs is not None:
        test_prepared["market"] = test_inputs.market
        test_prepared["provider"] = test_inputs.market_feature_provider
    elif inputs is not None:
        test_prepared["market"] = inputs.market
    try:
        raw_comparisons = dict(
            dependencies.replay_test(test_context, test_prepared, features, models, mappings, validation)
        )
    finally:
        if test_inputs is not None:
            close = getattr(test_inputs.market_feature_provider, "close", None)
            if callable(close):
                close()
    selector_not_reached_reason = None
    if not selector_invoked:
        selector_not_reached_reason = "no frozen eligible dynamic model/mapping selector was invoked"
        emit("test_selector_not_reached")
    access_audit.append({"interval": "test", "stage": "test_result"})
    unknown = set(raw_comparisons) - set(COMPARISON_NAMES)
    if unknown:
        raise ValueError(f"unknown comparison result: {', '.join(sorted(unknown))}")
    comparisons = {
        name: raw_comparisons.get(
            name,
            {"status": "cash", "rejection_reasons": ["no frozen eligible artifact"], "continuous_metrics": {}},
        )
        for name in COMPARISON_NAMES
    }
    emit("test_result")
    rejected = [
        item for item in models.get("candidates", ())
        if not item.get("eligible", False)
    ]
    data_provenance = {
        "pretest": prepared.get("provenance", {}),
        "test": test_inputs.data_provenance if test_inputs is not None else {},
    }
    payload = {
        "report_schema_version": 1,
        "artifact_schema_versions": {"feature": CHART_FEATURE_SCHEMA_VERSION},
        "symbol": symbol,
        "timeframe": timeframe,
        "fold": _fold_payload(fold),
        "configuration_grid": _grid_payload(grid),
        "gate_thresholds": {"model": MODEL_GATE_THRESHOLDS, "mapping": MAPPING_GATE_THRESHOLDS},
        "selection_score": "net_return_desc,max_drawdown_asc,turnover_asc,config_id_asc",
        "feature_schema_version": CHART_FEATURE_SCHEMA_VERSION,
        "candidate_ids": [item.candidate_id for item in selected_candidates],
        "candidate_behavior_hash_algorithm": "sha256(canonical-json-sort-keys,compact-separators,decimal-tag:$decimal)",
        "candidate_behavior_hashes": candidate_hashes,
        "candidate_behaviors": {
            item.candidate_id: _canonicalize(_candidate_behavior_payload(item))
            for item in selected_candidates
        },
        "candidate_universe_hash": candidate_universe_hash(tuple(candidate_hashes)),
        "candidate_definition_hash": candidate_definition_hash(candidate_hashes),
        "include_deferred": include_deferred,
        "data_provenance": data_provenance,
        "data_provenance_hash": _canonical_hash(data_provenance),
        "model_candidates": list(models.get("candidates", ())),
        "rejected_model_configurations": rejected,
        "selected_models": models.get("selected", {}),
        "mapping_artifacts": mappings.get("selected", {}),
        "mapping_metrics": mappings.get("mapping_metrics", {}),
        "candidate_feature_coverage": mappings.get("feature_coverage", {}),
        "validation": validation,
        "frozen_artifact_hashes": {"model": model_frozen, "mapping": mapping_frozen},
        "comparisons": comparisons,
        "continuous_diagnostics": _continuous_diagnostics(comparisons),
        "pipeline_events": events,
        "data_access_audit": access_audit,
        "leakage_audit": {
            "frozen_before_test": (
                not selector_invoked
                or events.index("mapping_frozen") < events.index("first_test_classification")
            ),
            "test_selector_reached": selector_invoked,
            "test_selector_family": selector_family,
            "test_selector_not_reached_reason": selector_not_reached_reason,
            "confirmatory_status": test_claim_status,
            "claim_reason": test_claim_reason,
            "prior_run_timestamp": prior_run_timestamp,
            "prior_run_hash": prior_run_hash,
            "thresholds_changed_after_prior_exposure": False,
            "configuration_grid_changed_after_prior_exposure": False,
            "gate_thresholds_hash": _canonical_hash({"model": MODEL_GATE_THRESHOLDS, "mapping": MAPPING_GATE_THRESHOLDS}),
            "configuration_grid_hash": _canonical_hash(_grid_payload(grid)),
        },
        "cost_model": {"fee_rate_per_side": _decimal_text(FEE_RATE), "slippage_rate_per_side": _decimal_text(SLIPPAGE_RATE)},
    }
    output_paths = (output_json, output_markdown, output_model, output_mapping)
    if any(path is not None for path in output_paths):
        if any(path is None for path in output_paths):
            raise ValueError("all report and artifact output paths must be supplied together")
        family = validation.get("selected_family")
        model_objects = dict(models.get("_artifacts", {}))
        mapping_objects = dict(mappings.get("_artifacts", {}))
        if family in model_objects and family in mapping_objects:
            with tempfile.TemporaryDirectory(prefix="regime-artifacts-") as directory:
                repository = JsonRegimeArtifactRepository(directory)
                repository.save_model(model_objects[family])
                repository.save_mapping(
                    mapping_objects[family],
                    expected_model_artifact_hash=model_artifact_hash(model_objects[family]),
                    expected_model_fingerprint_hash=model_fingerprint_hash(model_objects[family]),
                )
                _atomic_write(Path(output_model), (Path(directory) / "model.json").read_bytes())
                _atomic_write(Path(output_mapping), (Path(directory) / "mapping.json").read_bytes())
            payload["artifact_outputs"] = {"status": "written", "selected_family": family}
        else:
            reason = "no validation-frozen eligible model/mapping pair"
            for kind, destination in (("model", output_model), ("mapping", output_mapping)):
                body = {
                    "schema_version": 1, "kind": "cash_only", "artifact_type": kind,
                    "symbol": symbol, "timeframe": timeframe, "reason": reason,
                    "frozen_artifact_hashes": {"model": model_frozen, "mapping": mapping_frozen},
                }
                envelope = {**body, "artifact_hash": _canonical_hash(body)}
                _atomic_write(
                    Path(destination),
                    (json.dumps(envelope, sort_keys=True, indent=2) + "\n").encode("utf-8"),
                )
            payload["artifact_outputs"] = {"status": "cash_only", "reason": reason}
        emit("reports_written")
        normalized = _canonicalize_report(payload)
        write_walk_forward_reports(normalized, Path(output_json), Path(output_markdown))
        return normalized
    return _canonicalize_report(payload)


def _canonicalize_report(value: object) -> object:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        if value.tzinfo is not timezone.utc:
            raise ValueError("report datetimes must use canonical UTC")
        return value.isoformat()
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("report object keys must be strings")
        return {key: _canonicalize_report(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonicalize_report(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("report floats must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported report value: {type(value).__name__}")


def render_walk_forward_markdown(payload: Mapping[str, object]) -> str:
    comparisons = payload.get("comparisons", {})
    lines = [
        "# BTCUSDT chart-regime strategy mapping",
        "",
        "This is walk-forward research evidence, not a promotion or live-trading claim.",
        "",
        f"- Symbol/timeframe: {payload.get('symbol', 'unknown')} {payload.get('timeframe', 'unknown')}",
        f"- Frozen before Test: {payload.get('leakage_audit', {}).get('frozen_before_test', False)}",
        f"- Test claim status: {payload.get('leakage_audit', {}).get('confirmatory_status', 'unknown')}",
        f"- Prior exposure reason: {payload.get('leakage_audit', {}).get('claim_reason') or 'none'}",
        f"- Candidate universe: {payload.get('candidate_universe_hash', 'unknown')}",
        "",
        "## Test comparisons",
        "",
    ]
    for name in COMPARISON_NAMES:
        result = comparisons.get(name, {}) if isinstance(comparisons, Mapping) else {}
        metrics = result.get("continuous_metrics", {})
        lines.append(
            f"- {name}: {result.get('status', 'missing')}; "
            f"return={metrics.get('return_ratio', 'n/a')}; "
            f"MDD={metrics.get('portfolio_max_drawdown_ratio', metrics.get('max_drawdown_ratio', 'n/a'))}; "
            f"trades={metrics.get('trade_count', 0)}"
        )
    lines.extend(("", "## Frozen models and mappings", ""))
    for family, model in payload.get("selected_models", {}).items():
        lines.append(f"- {family}: model `{model.get('artifact_hash')}`, mapping `{payload.get('mapping_artifacts', {}).get(family, {}).get('artifact_hash')}`")
        entries = payload.get("mapping_artifacts", {}).get(family, {}).get("entries", {})
        for fingerprint, entry in entries.items():
            destination = entry.get("strategy_profile_id") or "cash"
            lines.append(
                f"  - `{fingerprint}` -> `{destination}` "
                f"(episodes={entry.get('weekly_episode_count', 0)}, trades={entry.get('closed_trade_count', 0)}, LCB={entry.get('corrected_lower_bound', '0')})"
            )
    lines.extend(("", "## Evidence coverage and diagnostics", ""))
    coverage = payload.get("candidate_feature_coverage", {})
    lines.append(f"- Candidate coverage records: {len(coverage)}")
    lines.append(f"- Rejected model configurations: {len(payload.get('rejected_model_configurations', ())) }")
    for item in payload.get("rejected_model_configurations", ()):
        reasons = item.get("rejection_reasons", ()) if isinstance(item, Mapping) else ()
        if reasons:
            lines.append(
                f"  - `{item.get('config_id', 'unknown')}`: "
                + "; ".join(str(reason) for reason in reasons)
            )
    lines.append(f"- Mapping metrics: `{json.dumps(payload.get('mapping_metrics', {}), sort_keys=True)}`")
    lines.extend(("", "## Costs and provenance", "", f"- Cost model: `{json.dumps(payload.get('cost_model', {}), sort_keys=True)}`", f"- Data provenance hash: `{payload.get('data_provenance_hash', 'unknown')}`", ""))
    return "\n".join(lines)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except BaseException:
        try:
            Path(temporary).unlink(missing_ok=True)
        finally:
            raise


def write_walk_forward_reports(payload: Mapping[str, object], json_path: Path | str, markdown_path: Path | str) -> None:
    normalized = _canonicalize_report(payload)
    json_bytes = (json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    markdown_bytes = render_walk_forward_markdown(normalized).encode("utf-8")
    # Render both before replacing either destination.
    _atomic_write(Path(json_path), json_bytes)
    _atomic_write(Path(markdown_path), markdown_bytes)


def _date_argument(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error
    return parsed.replace(tzinfo=timezone.utc)


def _timestamp_argument(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timestamp must use canonical ISO-8601 UTC") from error
    if parsed.tzinfo is not timezone.utc or parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("timestamp must use canonical ISO-8601 UTC")
    return value


def _sha256_argument(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise argparse.ArgumentTypeError("hash must be lowercase SHA-256")
    return value


def _month_starts(start_at: datetime, end_at: datetime):
    cursor = datetime(start_at.year, start_at.month, 1, tzinfo=timezone.utc)
    while cursor < end_at:
        yield cursor
        cursor = (
            datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
            if cursor.month == 12
            else datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)
        )


def _archive_url(symbol: str, month: datetime) -> str:
    filename = f"{symbol}-1m-{month.year}-{month.month:02d}.zip"
    return f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/1m/{filename}"


def _remote_checksum(url: str) -> tuple[str, str]:
    checksum_url = f"{url}.CHECKSUM"
    try:
        with urlopen(checksum_url, timeout=30) as response:
            text = response.read().decode("ascii").strip()
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"failed to fetch archive checksum: {checksum_url}") from error
    expected = text.split()[0].lower() if text else ""
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ValueError(f"invalid archive checksum response: {checksum_url}")
    return expected, checksum_url


def _ensure_archive(path: Path, url: str) -> tuple[str, str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    expected, checksum_url = _remote_checksum(url)
    if not path.exists():
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as stream, urlopen(url, timeout=60) as response:
                while block := response.read(1024 * 1024):
                    digest.update(block)
                    stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
            actual = digest.hexdigest()
            if actual != expected:
                raise ValueError(f"downloaded archive checksum mismatch: {path.name}")
            Path(temporary).replace(path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(f"cached archive checksum mismatch: {path.name}")
    return actual, expected, checksum_url


def _archive_candles(
    path: Path,
    symbol: str,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    parsed_symbol = Symbol("BTC", "USDT")
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            if len(names) != 1:
                raise ValueError(f"archive must contain exactly one CSV: {path.name}")
            with archive.open(names[0]) as raw:
                reader = csv.reader(TextIOWrapper(raw, encoding="utf-8"))
                for row in reader:
                    if not row or row[0] == "open_time":
                        continue
                    if len(row) < 6:
                        raise ValueError(f"malformed kline row in {path.name}")
                    opened_at = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
                    if end_at is not None and opened_at >= end_at:
                        break
                    if start_at is not None and opened_at < start_at:
                        continue
                    yield Candle(
                        symbol=parsed_symbol,
                        timeframe=TIMEFRAME,
                        opened_at=opened_at,
                        closed_at=opened_at + timedelta(minutes=1),
                        open_price=Decimal(row[1]), high_price=Decimal(row[2]),
                        low_price=Decimal(row[3]), close_price=Decimal(row[4]),
                        volume=Decimal(row[5]),
                    )
    except (OSError, UnicodeError, zipfile.BadZipFile, ValueError, InvalidOperation) as error:
        raise ValueError(f"invalid Binance archive {path.name}: {error}") from error


@dataclass(frozen=True)
class FeatureCacheShardPlan:
    cache_path: Path
    manifest_path: Path
    start_at: datetime
    end_at: datetime
    row_count: int
    output_hash: str
    manifest_hash: str
    cache_identity_hash: str
    input_hashes: Mapping[str, object]
    raw_hashes: Mapping[str, object]
    sources: tuple[str, ...]
    source_coverage: Mapping[str, object]
    provenance: Mapping[str, object]


@dataclass(frozen=True)
class FeatureCachePlan:
    shards: tuple[FeatureCacheShardPlan, ...]
    required_start: datetime
    required_end: datetime
    verify_full_file: bool = False


def _parse_cache_manifest(manifest_path: Path) -> FeatureCacheShardPlan:
    try:
        manifest_bytes = manifest_path.read_bytes()
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid feature cache manifest: {manifest_path.name}") from error
    identity = payload.get("cache_identity")
    if not isinstance(identity, Mapping) or identity.get("schema_version") != "binance-usdm-market-features-v1":
        raise ValueError("feature cache manifest schema mismatch")
    if payload.get("symbol") != "BTCUSDT" or payload.get("timeframe") != "1m":
        raise ValueError("feature cache manifest identity mismatch")
    start_at = _parse_canonical_utc(identity.get("start"), "cache start")
    end_at = _parse_canonical_utc(identity.get("end"), "cache end")
    sources = tuple(identity.get("sources", ()))
    coverage = payload.get("source_coverage")
    output_hash = payload.get("output_hash")
    cache_identity_hash = payload.get("cache_identity_hash")
    input_hashes = payload.get("input_hashes", {})
    raw_hashes = payload.get("raw_hashes", {})
    provenance = payload.get("provenance", {})
    row_count = payload.get("row_count")
    if (
        not sources or len(set(sources)) != len(sources)
        or not isinstance(coverage, Mapping) or set(coverage) != set(sources)
        or not isinstance(output_hash, str) or len(output_hash) != 64
        or any(character not in "0123456789abcdef" for character in output_hash)
        or not isinstance(cache_identity_hash, str) or len(cache_identity_hash) != 64
        or not isinstance(input_hashes, Mapping) or not isinstance(raw_hashes, Mapping)
        or not isinstance(provenance, Mapping)
        or any(not isinstance(item, Mapping) for item in coverage.values())
        or not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 1
        or row_count != int((end_at - start_at).total_seconds() // 60)
    ):
        raise ValueError("feature cache manifest metadata is inconsistent")
    cache_path = manifest_path.with_name(
        manifest_path.name.removesuffix(".manifest.json") + ".jsonl"
    )
    if not cache_path.is_file():
        raise ValueError("feature cache data file is missing")
    return FeatureCacheShardPlan(
        cache_path=cache_path, manifest_path=manifest_path,
        start_at=start_at, end_at=end_at, row_count=row_count,
        output_hash=output_hash, manifest_hash=hashlib.sha256(manifest_bytes).hexdigest(),
        cache_identity_hash=cache_identity_hash,
        input_hashes=dict(input_hashes), raw_hashes=dict(raw_hashes),
        sources=tuple(sorted(sources)),
        source_coverage=dict(coverage), provenance=dict(provenance),
    )


def plan_feature_caches(
    root: Path | None, *, required_start: datetime, required_end: datetime,
    verify_full_file: bool = False,
) -> FeatureCachePlan | None:
    if root is None:
        return None
    candidates = []
    for manifest in sorted(root.rglob("*.manifest.json"), key=lambda path: path.as_posix()):
        try:
            shard = _parse_cache_manifest(manifest)
        except ValueError:
            continue
        if shard.start_at <= required_start and shard.end_at >= required_end:
            candidates.append(shard)
    if not candidates:
        return None
    widest_start = min(item.start_at for item in candidates)
    widest_end = max(
        item.end_at for item in candidates if item.start_at == widest_start
    )
    exact = tuple(
        item for item in candidates
        if item.start_at == widest_start and item.end_at == widest_end
    )
    # Same-coverage shards are intentionally complementary.  Deterministic
    # path/hash ordering makes the merge plan independent of mtime.
    selected = tuple(sorted(exact, key=lambda item: (item.cache_path.as_posix(), item.output_hash)))
    return FeatureCachePlan(selected, required_start, required_end, verify_full_file)


class _IndexedJsonlShard:
    def __init__(
        self,
        plan: FeatureCacheShardPlan,
        *,
        required_start: datetime,
        required_end: datetime,
        verify_full_file: bool,
        progress: Callable[[str], None] | None,
        progress_label: str,
    ) -> None:
        self.plan = plan
        self._stream = plan.cache_path.open("rb")
        self._mapping = None
        self._offsets: list[tuple[int, int]] = []
        self.slice_hash = ""
        self.indexed_row_count = 0
        self.indexed_byte_count = 0
        self.full_file_verified = False
        self.source_available_counts = {source: 0 for source in plan.sources}
        self.source_unavailable_counts = {source: 0 for source in plan.sources}
        try:
            self._mapping = mmap.mmap(self._stream.fileno(), 0, access=mmap.ACCESS_READ)
            self._build_index(
                required_start=required_start,
                required_end=required_end,
                verify_full_file=verify_full_file,
                progress=progress,
                progress_label=progress_label,
            )
        except BaseException:
            self.close()
            raise

    def _build_index(
        self, *, required_start: datetime, required_end: datetime, verify_full_file: bool,
        progress: Callable[[str], None] | None, progress_label: str,
    ) -> None:
        indexed_end = min(required_end, self.plan.end_at)
        target_count = (
            self.plan.row_count
            if verify_full_file
            else int((indexed_end - self.plan.start_at).total_seconds() // 60)
        )
        if target_count < 1 or target_count > self.plan.row_count:
            raise ValueError("feature cache indexed coverage is invalid")
        if progress is not None:
            progress(f"feature_cache_index_started:{progress_label}:{target_count}")
        raw_hasher = hashlib.sha256()
        slice_hasher = hashlib.sha256()
        cursor = 0
        for index in range(target_count):
            newline = self._mapping.find(b"\n", cursor)
            if newline < 0:
                raise ValueError("feature cache row count does not match manifest")
            raw_line = self._mapping[cursor:newline + 1]
            raw_hasher.update(raw_line)
            try:
                row = json.loads(raw_line[:-1])
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("feature cache contains invalid JSONL") from error
            if not isinstance(row, Mapping):
                raise ValueError("feature cache row schema mismatch")
            expected_at = self.plan.start_at + timedelta(minutes=index + 1)
            measured_at = _parse_canonical_utc(row.get("measured_at"), "measured_at")
            if measured_at != expected_at:
                raise ValueError("feature cache timestamps must be strict increasing one-minute UTC")
            if row.get("symbol") != "BTCUSDT" or row.get("timeframe") != "1m":
                raise ValueError("feature cache row identity mismatch")
            features = row.get("features")
            unavailable = row.get("unavailable_sources", ())
            if (
                not isinstance(features, Mapping) or not isinstance(unavailable, list)
                or any(not isinstance(source, str) for source in unavailable)
            ):
                raise ValueError("feature cache row schema mismatch")
            filtered_features = {}
            available_sources = set()
            for name, item in features.items():
                if not isinstance(name, str) or not isinstance(item, Mapping):
                    raise ValueError("feature cache feature schema mismatch")
                source = item.get("source")
                if source not in self.plan.sources:
                    raise ValueError("feature cache feature source is not declared")
                observed_at = _parse_canonical_utc(item.get("observed_at"), "observed_at")
                available_at = _parse_canonical_utc(item.get("available_at"), "available_at")
                if observed_at > measured_at or available_at > measured_at:
                    raise ValueError("feature cache row is not point-in-time safe")
                try:
                    parsed_value = Decimal(str(item.get("value")))
                except InvalidOperation as error:
                    raise ValueError("feature cache value is not decimal") from error
                if not parsed_value.is_finite():
                    raise ValueError("feature cache value must be finite")
                filtered_features[name] = {
                    "value": str(item.get("value")),
                    "source": source,
                    "observed_at": observed_at.isoformat(),
                    "available_at": available_at.isoformat(),
                }
                available_sources.add(source)
            if any(source not in self.plan.sources for source in unavailable):
                raise ValueError("feature cache unavailable source is not declared")
            self._offsets.append((cursor, newline))
            if required_start <= measured_at <= required_end:
                canonical_slice_row = {
                    "features": filtered_features,
                    "measured_at": measured_at.isoformat(),
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "unavailable_sources": sorted(unavailable),
                }
                slice_hasher.update(
                    (json.dumps(canonical_slice_row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                )
                for source in self.plan.sources:
                    if source in available_sources:
                        self.source_available_counts[source] += 1
                    if source in unavailable:
                        self.source_unavailable_counts[source] += 1
            cursor = newline + 1
            if progress is not None and ((index + 1) % 50_000 == 0 or index + 1 == target_count):
                progress(f"feature_cache_index_progress:{progress_label}:{index + 1}/{target_count}")
        self.indexed_row_count = target_count
        self.indexed_byte_count = cursor
        self.slice_hash = slice_hasher.hexdigest()
        if target_count == self.plan.row_count:
            if cursor != len(self._mapping):
                raise ValueError("feature cache row count does not match manifest")
            if raw_hasher.hexdigest() != self.plan.output_hash:
                raise ValueError("feature cache output hash mismatch")
            self.full_file_verified = True
        if progress is not None:
            progress(f"feature_cache_index_completed:{progress_label}:{target_count}")

    def row_at(self, as_of: datetime) -> Mapping[str, object] | None:
        index = int((as_of - self.plan.start_at).total_seconds() // 60) - 1
        if index < 0 or index >= self.plan.row_count:
            return None
        if self._mapping is None:
            raise RuntimeError("feature cache provider is closed")
        if index >= len(self._offsets):
            return None
        start, end = self._offsets[index]
        row = json.loads(self._mapping[start:end])
        measured_at = _parse_canonical_utc(row.get("measured_at"), "measured_at")
        if measured_at > as_of:
            raise ValueError("feature cache row is not point-in-time safe")
        return row

    def close(self) -> None:
        mapping, self._mapping = self._mapping, None
        if mapping is not None:
            mapping.close()
        stream, self._stream = getattr(self, "_stream", None), None
        if stream is not None:
            stream.close()


class IndexedCompositeFeatureProvider:
    required_warmup_candles = 0

    def __init__(
        self, plan: FeatureCachePlan, *, progress: Callable[[str], None] | None = None
    ) -> None:
        self._plan = plan
        built = []
        try:
            for index, item in enumerate(plan.shards):
                built.append(_IndexedJsonlShard(
                    item, required_start=plan.required_start, required_end=plan.required_end,
                    verify_full_file=plan.verify_full_file,
                    progress=progress, progress_label=f"shard_{index:02d}",
                ))
        except BaseException:
            for shard in built:
                shard.close()
            raise
        self._shards = tuple(built)
        definitions = [
            {
                "schema_version": "binance-usdm-market-features-v1",
                "sources": list(shard.plan.sources),
                "slice_hash": shard.slice_hash,
            }
            for shard in self._shards
        ]
        slice_identity = {
            "symbol": "BTCUSDT", "timeframe": "1m",
            "required_start": plan.required_start.isoformat(),
            "required_end": plan.required_end.isoformat(),
            "shards": definitions,
        }
        self.feature_cache_hash = _canonical_hash(slice_identity)
        self.feature_config_hash = _canonical_hash({
            **slice_identity,
            "provider": "indexed-composite-jsonl-v2",
        })
        self.feature_source_coverage = {
            source: max(
                shard.source_available_counts.get(source, 0)
                for shard in self._shards
            )
            for source in sorted({source for shard in self._shards for source in shard.plan.sources})
        }
        self.feature_unavailable_counts = {
            source: max(
                shard.source_unavailable_counts.get(source, 0)
                for shard in self._shards
            )
            for source in self.feature_source_coverage
        }
        self.feature_provenance = {
            f"shard_{index:02d}": {
                "schema_version": "binance-usdm-market-features-v1",
                "slice_hash": shard.slice_hash,
                "sources": list(shard.plan.sources),
                "required_start": plan.required_start.isoformat(),
                "required_end": plan.required_end.isoformat(),
            }
            for index, shard in enumerate(self._shards)
        }
        self.feature_read_audit = {
            f"shard_{index:02d}": {
                "indexed_row_count": shard.indexed_row_count,
                "indexed_byte_count": shard.indexed_byte_count,
                "full_file_verified": shard.full_file_verified,
            }
            for index, shard in enumerate(self._shards)
        }
        interval_minutes = int((plan.required_end - plan.required_start).total_seconds() // 60) + 1
        # A merged set is conservatively budgeted at 6 KiB.  131,072 entries
        # keep a complete 77-day Validation or 86-day Test replay hot while
        # bounding the worst-case cache estimate at 768 MiB.  Weekly mapping
        # episodes always retain at least their complete 10,080-row working set.
        self._cache_capacity = max(7 * 24 * 60, min(interval_minutes, 131_072))
        self._merged_cache = OrderedDict()
        self._closed = False

    def load_features(self, symbol: Symbol, timeframe: Timeframe, as_of: datetime) -> MarketFeatureSet:
        if self._closed:
            raise RuntimeError("feature cache provider is closed")
        if as_of < self._plan.required_start or as_of > self._plan.required_end:
            raise ValueError("feature request is outside the provider's frozen access boundary")
        key = (symbol.pair, timeframe.label, as_of)
        cached = self._merged_cache.get(key)
        if cached is not None:
            self._merged_cache.move_to_end(key)
            return cached
        merged = {}
        unavailable = set()
        for shard in self._shards:
            row = shard.row_at(as_of)
            if row is None:
                unavailable.update(shard.plan.sources)
                continue
            for name, value in row.get("features", {}).items():
                canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
                if name in merged and merged[name][0] != canonical:
                    raise ValueError(f"conflicting feature cache value: {name}")
                merged[name] = (canonical, value)
            unavailable.update(row.get("unavailable_sources", ()))
        values = tuple(
            MarketFeatureValue(
                name=name, value=Decimal(str(item["value"])), source=item["source"],
                observed_at=_parse_canonical_utc(item["observed_at"], "observed_at"),
                available_at=_parse_canonical_utc(item["available_at"], "available_at"),
            )
            for name, (_, item) in sorted(merged.items())
        )
        available_sources = {item.source for item in values}
        result = MarketFeatureSet(
            symbol=symbol, timeframe=timeframe, measured_at=as_of, values=values,
            unavailable_sources=tuple(sorted(unavailable - available_sources)),
        )
        self._merged_cache[key] = result
        self._merged_cache.move_to_end(key)
        if len(self._merged_cache) > self._cache_capacity:
            self._merged_cache.popitem(last=False)
        return result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._merged_cache.clear()
        for shard in self._shards:
            shard.close()


def _select_feature_cache(
    root: Path | None, *, required_start: datetime, required_end: datetime,
    verify_full_file: bool = False,
    progress: Callable[[str], None] | None = None,
):
    plan = plan_feature_caches(
        root, required_start=required_start, required_end=required_end,
        verify_full_file=verify_full_file,
    )
    if plan is None:
        return None, {"selection_rule": "no covering manifest plan", "selected_shards": []}
    provider = IndexedCompositeFeatureProvider(plan, progress=progress)
    return provider, {
        "selection_rule": "manifest plan with access-bounded verified slice index",
        "slice_hash": provider.feature_cache_hash,
        "provider_config_hash": provider.feature_config_hash,
        "coverage": {"start_at": required_start.isoformat(), "end_at": required_end.isoformat()},
        "selected_shards": list(provider.feature_provenance.values()),
        "read_audit": dict(provider.feature_read_audit),
    }


def load_walk_forward_inputs(
    fold: RegimeWalkForwardFold,
    *,
    symbol: str,
    candidates: Sequence[SchedulerBacktestCandidate],
    raw_kline_root: Path,
    feature_cache_root: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> WalkForwardInputs:
    if symbol != "BTCUSDT":
        raise ValueError("archive loader supports BTCUSDT only")
    start_at = fold.cluster_fit.start_at - _WEEK
    end_at = fold.validation.end_at
    retention_start = fold.mapping_fit.start_at - max(
        _WEEK, timedelta(minutes=required_warmup_candles(tuple(candidates), None))
    )
    window = deque(maxlen=7 * 24 * 60)
    retained = []
    vectors = {"cluster_fit": [], "mapping_fit": [], "validation": []}
    archives = []
    expected = start_at
    extractor = ChartFeatureExtractor()
    for month in _month_starts(start_at, end_at):
        if progress is not None:
            progress(f"archive_scan_started:{month.year}-{month.month:02d}")
        url = _archive_url(symbol, month)
        path = raw_kline_root / symbol / Path(url).name
        sha256, expected_sha256, checksum_url = _ensure_archive(path, url)
        archives.append({
            "month": f"{month.year}-{month.month:02d}", "path": path.as_posix(),
            "source_url": url, "sha256": sha256, "expected_sha256": expected_sha256,
            "checksum_url": checksum_url, "checksum_verification": "remote_CHECKSUM_match",
            "size": path.stat().st_size,
        })
        for candle in _archive_candles(path, symbol, start_at=start_at, end_at=end_at):
            if candle.opened_at != expected:
                kind = "duplicate/out-of-order" if candle.opened_at < expected else "gap"
                raise ValueError(f"{kind} OHLCV at {candle.opened_at.isoformat()}")
            expected = candle.closed_at
            window.append(candle)
            if candle.opened_at >= retention_start:
                retained.append(candle)
            anchor = candle.closed_at
            if len(window) == window.maxlen and anchor.hour % 4 == 0 and anchor.minute == 0:
                target = None
                if fold.cluster_fit.start_at <= anchor < fold.cluster_fit.end_at:
                    target = "cluster_fit"
                elif fold.mapping_fit.start_at <= anchor < fold.mapping_fit.end_at:
                    target = "mapping_fit"
                elif fold.validation.start_at <= anchor < fold.validation.end_at:
                    target = "validation"
                if target:
                    vectors[target].append(extractor.extract(tuple(window), anchor))
        if progress is not None:
            progress(f"archive_scan_completed:{month.year}-{month.month:02d}")
    if expected != end_at:
        raise ValueError(f"OHLCV coverage ends at {expected.isoformat()}, expected {end_at.isoformat()}")
    provider, cache_provenance = _select_feature_cache(
        feature_cache_root,
        required_start=fold.mapping_fit.start_at,
        required_end=fold.validation.end_at,
        progress=progress,
    )
    provenance = {
        "archives": archives,
        "archive_set_hash": _canonical_hash(archives),
        "coverage": {"start_at": start_at.isoformat(), "end_at": end_at.isoformat(), "gaps": []},
        "feature_cache": cache_provenance,
        "retained_candle_count": len(retained),
        "maximum_classification_buffer_candles": window.maxlen,
    }
    return WalkForwardInputs(
        market=MarketSnapshot(tuple(retained)),
        cluster_fit_vectors=tuple(vectors["cluster_fit"]),
        mapping_vectors=tuple(vectors["mapping_fit"]),
        validation_vectors=tuple(vectors["validation"]),
        data_provenance=provenance,
        market_feature_provider=provider,
    )


def load_test_replay_inputs(
    fold: RegimeWalkForwardFold,
    *,
    symbol: str,
    raw_kline_root: Path,
    feature_cache_root: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> TestReplayInputs:
    """Load the seven-day classifier context and Test candles after freeze."""
    if symbol != "BTCUSDT":
        raise ValueError("archive loader supports BTCUSDT only")
    start_at = fold.test.start_at - _WEEK
    end_at = fold.test.end_at
    candles = []
    archives = []
    expected = start_at
    for month in _month_starts(start_at, end_at):
        if progress is not None:
            progress(f"test_archive_scan_started:{month.year}-{month.month:02d}")
        url = _archive_url(symbol, month)
        path = raw_kline_root / symbol / Path(url).name
        sha256, expected_sha256, checksum_url = _ensure_archive(path, url)
        archives.append({
            "month": f"{month.year}-{month.month:02d}", "path": path.as_posix(),
            "source_url": url, "sha256": sha256, "expected_sha256": expected_sha256,
            "checksum_url": checksum_url, "checksum_verification": "remote_CHECKSUM_match",
            "size": path.stat().st_size,
        })
        for candle in _archive_candles(path, symbol, start_at=start_at, end_at=end_at):
            if candle.opened_at != expected:
                kind = "duplicate/out-of-order" if candle.opened_at < expected else "gap"
                raise ValueError(f"{kind} OHLCV at {candle.opened_at.isoformat()}")
            expected = candle.closed_at
            candles.append(candle)
        if progress is not None:
            progress(f"test_archive_scan_completed:{month.year}-{month.month:02d}")
    if expected != end_at:
        raise ValueError(f"OHLCV coverage ends at {expected.isoformat()}, expected {end_at.isoformat()}")
    provider, cache_provenance = _select_feature_cache(
        feature_cache_root, required_start=start_at, required_end=end_at,
        verify_full_file=True,
        progress=progress,
    )
    provenance = {
        "archives": archives,
        "archive_set_hash": _canonical_hash(archives),
        "coverage": {"start_at": start_at.isoformat(), "end_at": end_at.isoformat(), "gaps": []},
        "feature_cache": cache_provenance,
        "retained_candle_count": len(candles),
        "classification_context_candles": 7 * 24 * 60,
    }
    return TestReplayInputs(
        market=MarketSnapshot(tuple(candles)),
        data_provenance=provenance,
        market_feature_provider=provider,
    )


def parse_walk_forward_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Leakage-safe BTCUSDT regime walk-forward")
    parser.add_argument("--symbol", required=True)
    for name in ("cluster-fit-start", "cluster-fit-end", "mapping-fit-start", "mapping-fit-end", "validation-start", "validation-end", "test-start", "test-end"):
        parser.add_argument(f"--{name}", type=_date_argument)
    parser.add_argument("--candidate-group", action="append", default=[])
    parser.add_argument("--include-deferred", action="store_true")
    parser.add_argument(
        "--test-claim-status",
        choices=("untouched", "diagnostic_after_pipeline_defect"),
        default="untouched",
    )
    parser.add_argument("--test-claim-reason")
    parser.add_argument("--prior-run-timestamp", type=_timestamp_argument)
    parser.add_argument("--prior-run-hash", type=_sha256_argument)
    parser.add_argument("--feature-cache-root", type=Path)
    parser.add_argument("--raw-kline-root", type=Path, default=Path(".research-data/binance-usdm/raw/klines"))
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    parser.add_argument("--output-model", type=Path)
    parser.add_argument("--output-mapping", type=Path)
    args = parser.parse_args(argv)
    fold_dates = [
        getattr(args, name)
        for name in (
            "cluster_fit_start", "cluster_fit_end", "mapping_fit_start", "mapping_fit_end",
            "validation_start", "validation_end", "test_start", "test_end",
        )
    ]
    if any(value is None for value in fold_dates) and not all(value is None for value in fold_dates):
        parser.error("all eight fold date arguments must be supplied together")
    claim_fields = (args.test_claim_reason, args.prior_run_timestamp, args.prior_run_hash)
    if args.test_claim_status == "diagnostic_after_pipeline_defect":
        if any(not value for value in claim_fields):
            parser.error("diagnostic Test claim requires reason, prior timestamp, and prior hash")
    elif any(value is not None for value in claim_fields):
        parser.error("prior exposure audit fields require diagnostic Test claim status")
    args.output_model = args.output_model or args.output_json.with_name(f"{args.output_json.stem}-model.json")
    args.output_mapping = args.output_mapping or args.output_json.with_name(f"{args.output_json.stem}-mapping.json")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_walk_forward_args(argv)
    supplied = [getattr(args, name) for name in ("cluster_fit_start", "cluster_fit_end", "mapping_fit_start", "mapping_fit_end", "validation_start", "validation_end", "test_start", "test_end")]
    if any(value is None for value in supplied):
        fold = BTCUSDT_FIRST_FOLD
    else:
        fold = RegimeWalkForwardFold(*(UtcInterval(supplied[index], supplied[index + 1]) for index in range(0, 8, 2)))
    def report_progress(event: str) -> None:
        print(event, flush=True)

    inputs = None
    try:
        resolved, _ = _resolve_walk_forward_candidates(
            candidates=None,
            candidate_groups=tuple(args.candidate_group),
            include_deferred=args.include_deferred,
        )
        inputs = load_walk_forward_inputs(
            fold,
            symbol=args.symbol,
            candidates=resolved,
            raw_kline_root=args.raw_kline_root,
            feature_cache_root=args.feature_cache_root,
            progress=report_progress,
        )
        payload = run_chart_regime_walk_forward(
            fold,
            symbol=args.symbol,
            candidates=resolved,
            include_deferred=args.include_deferred,
            inputs=inputs,
            test_input_loader=lambda: load_test_replay_inputs(
                fold,
                symbol=args.symbol,
                raw_kline_root=args.raw_kline_root,
                feature_cache_root=args.feature_cache_root,
                progress=report_progress,
            ),
            progress=report_progress,
            output_json=args.output_json,
            output_markdown=args.output_markdown,
            output_model=args.output_model,
            output_mapping=args.output_mapping,
            test_claim_status=args.test_claim_status,
            test_claim_reason=args.test_claim_reason,
            prior_run_timestamp=args.prior_run_timestamp,
            prior_run_hash=args.prior_run_hash,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"walk-forward failed: {error}")
        return 1
    finally:
        if inputs is not None:
            close = getattr(inputs.market_feature_provider, "close", None)
            if callable(close):
                close()
    print(f"wrote {args.output_json} and {args.output_markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
