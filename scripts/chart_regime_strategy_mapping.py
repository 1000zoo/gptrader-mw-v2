from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence

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
)
from src.domain.market import MarketSnapshot, Symbol
from src.domain.regime import WeeklyEpisode


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
