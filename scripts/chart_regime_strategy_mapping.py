from __future__ import annotations

import hashlib
import json
import math
import argparse
import csv
import os
import tempfile
import zipfile
import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, silhouette_score
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from io import TextIOWrapper
from typing import Callable, Mapping, Sequence
from urllib.request import urlopen

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
    for config_id, seed_artifacts in sorted(structural.items()):
        primary = seed_artifacts[0]
        seed_assignments = [engine.assign(artifact, mapping_vectors) for artifact in seed_artifacts]
        primary_labels = [item.fingerprint for item in seed_assignments[0]]
        weekly_counts = tuple(primary_labels.count(fp) for fp in primary.fingerprints)
        month_sets = {fp: set() for fp in primary.fingerprints}
        for vector, label in zip(mapping_vectors, primary_labels):
            month_sets[label].add((vector.anchor_at.year, vector.anchor_at.month))
        month_counts = tuple(len(month_sets[fp]) for fp in primary.fingerprints)
        aris = [adjusted_rand_score(primary_labels, [item.fingerprint for item in values]) for values in seed_assignments[1:]]
        nmis = [normalized_mutual_info_score(primary_labels, [item.fingerprint for item in values]) for values in seed_assignments[1:]]
        centroid_distances = []
        primary_means = np.asarray(primary.means)
        for artifact in seed_artifacts[1:]:
            distances = np.linalg.norm(primary_means[:, None, :] - np.asarray(artifact.means)[None, :, :], axis=2)
            rows, columns = linear_sum_assignment(distances)
            centroid_distances.append(float(np.mean(distances[rows, columns])))
        midpoint = max(1, len(primary_labels) // 2)
        first = primary_labels[:midpoint]
        second = primary_labels[midpoint:]
        prevalence_drift = max(
            abs(first.count(fp) / len(first) - second.count(fp) / max(1, len(second)))
            for fp in primary.fingerprints
        )
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
            parameter_count = primary.config.cluster_count * (2 * dimensions + 1) - 1
            bic = float(-2 * sum(log_terms) + parameter_count * math.log(len(scaled)))
        evidence = RegimeModelEvidence(
            artifact_id=config_id, model_type=primary.config.model_type,
            cluster_fingerprints=primary.fingerprints,
            weekly_episode_counts=weekly_counts,
            distinct_calendar_month_counts=month_counts,
            seed_ari=min(aris), seed_nmi=min(nmis),
            matched_centroid_distance=max(centroid_distances),
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
                "matched_centroid_distance": evidence_by_id[item.artifact_id].matched_centroid_distance,
                "prevalence_drift": evidence_by_id[item.artifact_id].prevalence_drift,
                "low_confidence_rate": evidence_by_id[item.artifact_id].low_confidence_rate,
                "silhouette": evidence_by_id[item.artifact_id].silhouette,
                "bic": evidence_by_id[item.artifact_id].bic,
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
        "entries": {
            fingerprint: {
                "decision": entry.decision,
                "strategy_profile_id": entry.strategy_profile_id,
                "rejection_reasons": list(entry.rejection_reasons),
            }
            for fingerprint, entry in sorted(artifact.entries.items())
        },
    }


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
    evidence = run_mapping_episodes(
        prepared["market"],
        episodes=episodes,
        assignments=reference,
        candidates=tuple(context["candidates"]),
        market_feature_provider=prepared.get("provider"),
    )
    by_key = {(row["episode_start_at"], row["candidate_id"]): row for row in evidence}
    mapping_artifacts = {}
    reports = {}
    grid: WalkForwardGrid = context["configuration_grid"]  # type: ignore[assignment]
    for family, model_artifact in artifacts.items():
        family_rows = []
        assignment = assignments_by_family[family]
        for episode in episodes:
            for candidate in context["candidates"]:
                row = dict(by_key[(episode.start_at.isoformat(), candidate.candidate_id)])
                row["cluster_fingerprint"] = assignment[episode.anchor_at]
                family_rows.append(row)
        result = BuildStrategyMappingUseCase().execute(
            BuildStrategyMappingCommand(
                evidence_rows=tuple(family_rows),
                regime_model_artifact_hash=model_artifact_hash(model_artifact),
                regime_model_fingerprint_hash=model_fingerprint_hash(model_artifact),
                selection_confidence_thresholds=_selection_policy(model_artifact),
                bootstrap_resamples=grid.bootstrap_resamples[0],
                confidence=Decimal(str(grid.confidence_levels[-1])),
            )
        )
        mapping_artifacts[family] = result.artifact
        reports[family] = _mapping_report(result.artifact)
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
        base_mapping = mapping_objects[family]
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
        for config_id, candidate_model, policy in policies:
            candidate_mapping = replace(
                base_mapping,
                regime_model_artifact_hash=model_artifact_hash(candidate_model),
                regime_model_fingerprint_hash=model_fingerprint_hash(candidate_model),
                selection_confidence_thresholds=policy,
            )
            replay = run_scheduler_driven_regime_backtest(
                prepared["market"], start_at=interval.start_at, end_at=interval.end_at,
                candidates=candidates, model_artifact=candidate_model,
                mapping_artifact=candidate_mapping, market_feature_provider=provider,
                include_deferred=bool(context["include_deferred"]),
            )
            continuous_return = Decimal(str(replay.get("return_ratio", "0")))
            drawdown = Decimal(str(replay.get("max_drawdown_ratio", "0")))
            turnover = Decimal(str(replay.get("turnover", replay.get("strategy_turnover", "0"))))
            record = {
                "family": family, "config_id": config_id,
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
            force_close_at_end=True,
        )
        results["train_selected_fixed"] = {
            "status": "ok",
            "candidate_id": selected.candidate_id,
            "continuous_metrics": fixed,
        }
    else:
        results["train_selected_fixed"] = _cash_comparison("mapping-fit statistical gate selected cash")
    manual_router = replace(adopted, candidate_id="manual-regime-router-ohlcv-v1")
    manual_result = run_scheduler_driven_backtest(
        market,
        context_start_at=test.start_at - timedelta(
            minutes=required_warmup_candles((manual_router,), provider)
        ),
        start_at=test.start_at, end_at=test.end_at, candidate=manual_router,
        market_feature_provider=provider, force_close_at_end=True,
    )
    results["manual_regime_router"] = {
        "status": "ok",
        "router_rule": "predeclared_ohlcv_trend_range_volatility_v1",
        "candidate_id": manual_router.candidate_id,
        "continuous_metrics": manual_result,
    }
    for family in ("kmeans", "gmm"):
        if family not in mapping_objects or family not in model_objects:
            results[f"{family}_dynamic"] = _cash_comparison("no frozen eligible artifact")
            continue
        replay = run_scheduler_driven_regime_backtest(
            market,
            start_at=test.start_at,
            end_at=test.end_at,
            candidates=candidates,
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
    progress: Callable[[str], None] | None = None,
    fixture_grid: WalkForwardGrid | None = None,
    output_json: Path | None = None,
    output_markdown: Path | None = None,
    output_model: Path | None = None,
    output_mapping: Path | None = None,
) -> dict[str, object]:
    """Run one leakage-guarded four-interval pipeline.

    Test access exists in exactly one stage and is structurally after both freeze
    events.  Stage dependencies receive the same context in production and tests.
    """
    if symbol != "BTCUSDT" or timeframe != "1m":
        raise ValueError("the first walk-forward pipeline supports BTCUSDT 1m only")
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
    mappings = dict(dependencies.build_mappings(context, prepared, features, models))
    emit("mapping_evidence_ready")
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
    emit("first_test_classification")
    access_audit.append({"interval": "test", "stage": "test_result"})
    test_context = {**context, "test": fold.test}
    test_prepared = dict(prepared)
    if inputs is not None:
        test_prepared["market"] = inputs.market
    raw_comparisons = dict(
        dependencies.replay_test(test_context, test_prepared, features, models, mappings, validation)
    )
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
    data_provenance = prepared.get("provenance", {})
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
        "candidate_behavior_hashes": candidate_hashes,
        "candidate_behaviors": {
            item.candidate_id: _candidate_behavior_payload(item)
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
        "validation": validation,
        "frozen_artifact_hashes": {"model": model_frozen, "mapping": mapping_frozen},
        "comparisons": comparisons,
        "pipeline_events": events,
        "data_access_audit": access_audit,
        "leakage_audit": {"frozen_before_test": events.index("mapping_frozen") < events.index("first_test_classification")},
        "cost_model": {"fee_rate_per_side": _decimal_text(FEE_RATE), "slippage_rate_per_side": _decimal_text(SLIPPAGE_RATE)},
    }
    output_paths = (output_json, output_markdown, output_model, output_mapping)
    if any(path is not None for path in output_paths):
        if any(path is None for path in output_paths):
            raise ValueError("all report and artifact output paths must be supplied together")
        family = validation.get("selected_family")
        model_objects = dict(models.get("_artifacts", {}))
        mapping_objects = dict(mappings.get("_artifacts", {}))
        if family not in model_objects or family not in mapping_objects:
            raise ValueError("no validation-frozen model/mapping pair is available for output")
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
        f"- Candidate universe: {payload.get('candidate_universe_hash', 'unknown')}",
        "",
        "## Untouched Test comparisons",
        "",
    ]
    for name in COMPARISON_NAMES:
        result = comparisons.get(name, {}) if isinstance(comparisons, Mapping) else {}
        lines.append(f"- {name}: {result.get('status', 'missing')}")
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


def _archive_candles(path: Path, symbol: str):
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


def _select_feature_cache(root: Path | None, *, required_start: datetime, required_end: datetime):
    if root is None:
        return None, {"selection_rule": "no feature cache configured", "candidates": []}
    valid = []
    for cache in sorted(root.rglob("*.jsonl"), key=lambda path: path.as_posix()):
        try:
            loaded = load_market_feature_cache(cache)
        except ValueError:
            continue
        rows = [
            measured_at
            for values in loaded.provider._rows_by_key.values()
            for measured_at, _ in values
        ]
        if rows and min(rows) <= required_start and max(rows) >= required_end - timedelta(minutes=1):
            valid.append((cache, loaded, min(rows), max(rows)))
    if not valid:
        return None, {"selection_rule": "no valid cache/manifest pair", "candidates": []}
    valid.sort(key=lambda item: (-(item[3] - item[2]).total_seconds(), item[0].as_posix(), item[1].cache_hash))
    widest = (valid[0][2], valid[0][3])
    exact_winners = [item for item in valid if (item[2], item[3]) == widest]
    if len({item[1].cache_hash for item in exact_winners}) > 1:
        raise ValueError("multiple incompatible exact feature-cache winners")
    cache, loaded, coverage_start, coverage_end = valid[0]
    return loaded.provider, {
        "selection_rule": "canonical path among valid cache/manifest pairs",
        "selected": cache.as_posix(),
        "cache_hash": loaded.cache_hash,
        "coverage": {"start_at": coverage_start.isoformat(), "end_at": coverage_end.isoformat()},
        "candidates": [path.as_posix() for path, *_ in valid],
        "provider_provenance": loaded.provenance,
    }


def load_walk_forward_inputs(
    fold: RegimeWalkForwardFold,
    *,
    symbol: str,
    candidates: Sequence[SchedulerBacktestCandidate],
    raw_kline_root: Path,
    feature_cache_root: Path | None = None,
) -> WalkForwardInputs:
    if symbol != "BTCUSDT":
        raise ValueError("archive loader supports BTCUSDT only")
    start_at = fold.cluster_fit.start_at - _WEEK
    end_at = fold.test.end_at
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
        url = _archive_url(symbol, month)
        path = raw_kline_root / symbol / Path(url).name
        sha256, expected_sha256, checksum_url = _ensure_archive(path, url)
        archives.append({
            "month": f"{month.year}-{month.month:02d}", "path": path.as_posix(),
            "source_url": url, "sha256": sha256, "expected_sha256": expected_sha256,
            "checksum_url": checksum_url, "checksum_verification": "remote_CHECKSUM_match",
            "size": path.stat().st_size,
        })
        for candle in _archive_candles(path, symbol):
            if candle.opened_at < start_at or candle.opened_at >= end_at:
                continue
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
    if expected != end_at:
        raise ValueError(f"OHLCV coverage ends at {expected.isoformat()}, expected {end_at.isoformat()}")
    provider, cache_provenance = _select_feature_cache(
        feature_cache_root,
        required_start=fold.mapping_fit.start_at,
        required_end=fold.test.end_at,
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


def parse_walk_forward_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Leakage-safe BTCUSDT regime walk-forward")
    parser.add_argument("--symbol", required=True)
    for name in ("cluster-fit-start", "cluster-fit-end", "mapping-fit-start", "mapping-fit-end", "validation-start", "validation-end", "test-start", "test-end"):
        parser.add_argument(f"--{name}", type=_date_argument)
    parser.add_argument("--candidate-group", action="append", default=[])
    parser.add_argument("--include-deferred", action="store_true")
    parser.add_argument("--feature-cache-root", type=Path)
    parser.add_argument("--raw-kline-root", type=Path, default=Path(".research-data/binance-usdm/raw/klines"))
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    parser.add_argument("--output-model", type=Path)
    parser.add_argument("--output-mapping", type=Path)
    args = parser.parse_args(argv)
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
        )
        payload = run_chart_regime_walk_forward(
            fold,
            symbol=args.symbol,
            candidates=resolved,
            include_deferred=args.include_deferred,
            inputs=inputs,
            progress=lambda event: print(event, flush=True),
            output_json=args.output_json,
            output_markdown=args.output_markdown,
            output_model=args.output_model,
            output_mapping=args.output_mapping,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"walk-forward failed: {error}")
        return 1
    print(f"wrote {args.output_json} and {args.output_markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
