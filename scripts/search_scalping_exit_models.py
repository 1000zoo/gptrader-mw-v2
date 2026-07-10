from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.novel_train_test_combo_search import load_or_fetch_market  # noqa: E402
from scripts.scalping_train_test_combo_search import (  # noqa: E402
    _apply_entry_slippage,
    _apply_exit_slippage,
    _evaluate_scalping_direction,
    _precomputed,
    _rolling_prior_average,
    _scaled,
)
from scripts.validate_scalping_external_periods import (  # noqa: E402
    BTC_RECHECK_PERIODS,
    PeriodSpec,
    load_period_market,
    selected_combo,
)


RESULTS_PATH = Path("docs/backtests/scalping-exit-model-search.json")
SUMMARY_PATH = Path("docs/backtests/scalping-exit-model-search.md")
EXTERNAL_RESULTS_PATH = Path("docs/backtests/scalping-exit-model-external-validation.json")
EXTERNAL_SUMMARY_PATH = Path("docs/backtests/scalping-exit-model-external-validation.md")
EXIT_TRAIN_START = datetime(2025, 11, 9, 0, 0, tzinfo=timezone.utc)
EXIT_TRAIN_END = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)
EXIT_TEST_START = EXIT_TRAIN_END
EXIT_TEST_END = datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)
FEE_RATE = 0.0004
SLIPPAGE_RATE = 0.0002
INITIAL_EQUITY = 10000.0
WARMUP = 260
_DATA_CACHE: dict[tuple[int, datetime, datetime], dict[str, list[float]]] = {}


@dataclass(frozen=True)
class ExitCandidate:
    candidate_id: str
    kind: str
    params: Mapping[str, float | int | str]
    filters: Mapping[str, float | int]


@dataclass
class OpenPosition:
    direction: int
    entry_price: float
    entry_index: int
    notional: float
    margin: float
    remaining_ratio: float = 1.0
    realized_gross_pnl: float = 0.0
    exit_fee_paid: float = 0.0
    activated: bool = False
    extreme_price: float = 0.0
    partial_done: bool = False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--external-limit", type=int, default=5)
    parser.add_argument("--reuse-search", action="store_true")
    args = parser.parse_args()

    if args.reuse_search and RESULTS_PATH.exists():
        payload = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
        ranked = payload["results"]
    else:
        market = load_or_fetch_market()
        combo = selected_combo()
        candidates = build_exit_candidates()
        results = []
        for candidate in candidates:
            train = simulate_exit_candidate(
                market=market,
                candidate=candidate,
                start_at=EXIT_TRAIN_START,
                end_at=EXIT_TRAIN_END,
                strategy_params=combo.strategy_params,
                sizing_params=combo.position_sizing_params,
            )
            test = simulate_exit_candidate(
                market=market,
                candidate=candidate,
                start_at=EXIT_TEST_START,
                end_at=EXIT_TEST_END,
                strategy_params=combo.strategy_params,
                sizing_params=combo.position_sizing_params,
            )
            results.append(combine_result(candidate, train, test))

        ranked = rank_results(results)
        payload = {
            "cost_model": cost_model(),
            "train_period": {"start_at": EXIT_TRAIN_START.isoformat(), "end_at": EXIT_TRAIN_END.isoformat()},
            "test_period": {"start_at": EXIT_TEST_START.isoformat(), "end_at": EXIT_TEST_END.isoformat()},
            "result_count": len(ranked),
            "family_best": family_best(ranked),
            "results": ranked,
        }
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    if "family_best" not in payload:
        payload["family_best"] = family_best(ranked)
        RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    SUMMARY_PATH.write_text(markdown_search_summary(payload, limit=args.limit), encoding="utf-8")

    finalists = payload["family_best"][: args.external_limit]
    external = validate_external(finalists)
    EXTERNAL_RESULTS_PATH.write_text(
        json.dumps(external, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    EXTERNAL_SUMMARY_PATH.write_text(markdown_external_summary(external), encoding="utf-8")
    print(f"RESULTS {RESULTS_PATH}")
    print(f"SUMMARY {SUMMARY_PATH}")
    print(f"EXTERNAL_RESULTS {EXTERNAL_RESULTS_PATH}")
    print(f"EXTERNAL_SUMMARY {EXTERNAL_SUMMARY_PATH}")


def build_exit_candidates() -> list[ExitCandidate]:
    filters = [
        ("nofilter", {}),
        ("liq", {"min_volume_ratio": 0.8}),
        ("active", {"min_atr_ratio": 0.0010, "min_volume_ratio": 0.8}),
        ("rangeok", {"min_range_ratio": 0.0020, "min_volume_ratio": 0.8}),
    ]
    tp_values = [0.004, 0.006, 0.008, 0.010, 0.012, 0.015]
    candidates: list[ExitCandidate] = []
    for filter_name, filter_params in filters:
        for tp in tp_values:
            for sl in (0.006, 0.010):
                candidates.append(_candidate("fixed", filter_name, filter_params, tp=tp, sl=sl))
            for max_hold in (30, 60, 120):
                candidates.append(
                    _candidate("time", filter_name, filter_params, tp=tp, sl=0.008, max_holding_minutes=max_hold)
                )
            for trail in (0.002, 0.003, 0.004):
                candidates.append(
                    _candidate("trailing", filter_name, filter_params, activation=tp, trail=trail, sl=0.008)
                )
        for atr_tp in (1.5, 2.0, 2.5, 3.0):
            for atr_sl in (1.0, 1.5, 2.0):
                candidates.append(
                    _candidate(
                        "atr",
                        filter_name,
                        filter_params,
                        atr_period=60,
                        tp_atr_multiple=atr_tp,
                        sl_atr_multiple=atr_sl,
                        min_tp=0.004,
                        max_tp=0.015,
                        min_sl=0.004,
                        max_sl=0.012,
                    )
                )
        for first_tp in (0.004, 0.006, 0.008, 0.010):
            for partial_ratio in (0.5, 0.7):
                for trail in (0.0025, 0.004):
                    candidates.append(
                        _candidate(
                            "partial_trailing",
                            filter_name,
                            filter_params,
                            first_tp=first_tp,
                            partial_ratio=partial_ratio,
                            trail=trail,
                            sl=0.008,
                        )
                    )
    return candidates


def _candidate(kind: str, filter_name: str, filters: Mapping[str, float | int], **params) -> ExitCandidate:
    param_bits = "-".join(f"{key}{_param_text(value)}" for key, value in sorted(params.items()))
    candidate_id = f"{kind}-{filter_name}-{param_bits}"
    return ExitCandidate(candidate_id=candidate_id, kind=kind, params=params, filters=filters)


def simulate_exit_candidate(
    *,
    market,
    candidate: ExitCandidate,
    start_at: datetime,
    end_at: datetime,
    strategy_params: Mapping[str, object],
    sizing_params: Mapping[str, object],
) -> dict[str, object]:
    data = _data_for_period(market, start_at, end_at)
    equity = INITIAL_EQUITY
    peak = equity
    max_drawdown = 0.0
    gross_wins = 0
    net_wins = 0
    trade_count = 0
    gross_pnl = 0.0
    net_pnl = 0.0
    fee_paid = 0.0
    gross_roes: list[float] = []
    net_roes: list[float] = []
    net_returns: list[float] = []
    holding_minutes: list[int] = []
    exit_reasons: Counter[str] = Counter()
    position: OpenPosition | None = None

    for index in range(WARMUP, len(data["close"])):
        high = data["high"][index]
        low = data["low"][index]
        close = data["close"][index]
        if position is not None:
            exit_result = exit_for_candle(candidate, position, data, index)
            if exit_result is not None:
                exit_price, exit_reason = exit_result
                trade = close_position(position, exit_price, exit_reason)
                equity += trade["net_pnl"]
                gross_pnl += trade["gross_pnl"]
                net_pnl += trade["net_pnl"]
                fee_paid += trade["fee_paid"]
                trade_count += 1
                gross_wins += 1 if trade["gross_pnl"] > 0 else 0
                net_wins += 1 if trade["net_pnl"] > 0 else 0
                gross_roes.append(trade["gross_pnl"] / position.margin if position.margin > 0 else 0.0)
                net_roes.append(trade["net_pnl"] / position.margin if position.margin > 0 else 0.0)
                net_returns.append(trade["net_pnl"] / position.notional if position.notional > 0 else 0.0)
                holding_minutes.append(index - position.entry_index)
                exit_reasons[exit_reason] += 1
                peak = max(peak, equity)
                if peak > 0:
                    max_drawdown = max(max_drawdown, (peak - equity) / peak)
                position = None
                continue
            continue

        direction = _evaluate_scalping_direction(data, index, strategy_params)
        if direction == 0 or not entry_filter_passes(candidate, data, index):
            continue
        confidence = 0.68
        equity_ratio = _scaled(confidence, float(sizing_params["min_equity_ratio"]), float(sizing_params["max_equity_ratio"]))
        lev = _scaled(confidence, float(sizing_params["min_leverage"]), float(sizing_params["max_leverage"]))
        margin = equity * equity_ratio
        notional = margin * lev
        signed_direction = 1 if direction > 0 else -1
        entry_price = _apply_entry_slippage(close, signed_direction, SLIPPAGE_RATE)
        position = OpenPosition(
            direction=signed_direction,
            entry_price=entry_price,
            entry_index=index,
            notional=notional,
            margin=margin,
            extreme_price=entry_price,
        )
        _ = high, low

    if position is not None:
        exit_price = _apply_exit_slippage(data["close"][-1], position.direction, SLIPPAGE_RATE)
        trade = close_position(position, exit_price, "end_of_data")
        equity += trade["net_pnl"]
        gross_pnl += trade["gross_pnl"]
        net_pnl += trade["net_pnl"]
        fee_paid += trade["fee_paid"]
        trade_count += 1
        gross_wins += 1 if trade["gross_pnl"] > 0 else 0
        net_wins += 1 if trade["net_pnl"] > 0 else 0
        gross_roes.append(trade["gross_pnl"] / position.margin if position.margin > 0 else 0.0)
        net_roes.append(trade["net_pnl"] / position.margin if position.margin > 0 else 0.0)
        net_returns.append(trade["net_pnl"] / position.notional if position.notional > 0 else 0.0)
        holding_minutes.append(len(data["close"]) - 1 - position.entry_index)
        exit_reasons["end_of_data"] += 1
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    days = (end_at - start_at).total_seconds() / 86400
    return {
        "trade_count": trade_count,
        "trades_per_day": trade_count / days if days else 0.0,
        "gross_win_rate": gross_wins / trade_count if trade_count else 0.0,
        "net_win_rate": net_wins / trade_count if trade_count else 0.0,
        "return_ratio": (equity - INITIAL_EQUITY) / INITIAL_EQUITY,
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "fee_paid": fee_paid,
        "max_drawdown_ratio": max_drawdown,
        "average_gross_trade_roe": _avg(gross_roes),
        "average_net_trade_roe": _avg(net_roes),
        "average_net_trade_return": _avg(net_returns),
        "average_holding_minutes": _avg(holding_minutes),
        "exit_reasons": dict(exit_reasons),
    }


def exit_for_candle(
    candidate: ExitCandidate,
    position: OpenPosition,
    data: Mapping[str, list[float]],
    index: int,
) -> tuple[float, str] | None:
    if candidate.kind == "fixed":
        return fixed_exit(candidate, position, data, index)
    if candidate.kind == "time":
        timed = time_exit(candidate, position, data, index)
        return timed or fixed_exit(candidate, position, data, index)
    if candidate.kind == "atr":
        return atr_exit(candidate, position, data, index)
    if candidate.kind == "trailing":
        return trailing_exit(candidate, position, data, index)
    if candidate.kind == "partial_trailing":
        return partial_trailing_exit(candidate, position, data, index)
    raise ValueError(f"unsupported exit candidate kind: {candidate.kind}")


def fixed_exit(candidate: ExitCandidate, position: OpenPosition, data: Mapping[str, list[float]], index: int):
    tp = float(candidate.params["tp"])
    sl = float(candidate.params["sl"])
    return stop_take_exit(position, data, index, tp=tp, sl=sl)


def time_exit(candidate: ExitCandidate, position: OpenPosition, data: Mapping[str, list[float]], index: int):
    max_holding = int(candidate.params["max_holding_minutes"])
    if index - position.entry_index >= max_holding:
        return _apply_exit_slippage(data["close"][index], position.direction, SLIPPAGE_RATE), "time_exit"
    return None


def atr_exit(candidate: ExitCandidate, position: OpenPosition, data: Mapping[str, list[float]], index: int):
    atr_ratio = data["atr_ratio"][index]
    tp = _clamp(
        atr_ratio * float(candidate.params["tp_atr_multiple"]),
        float(candidate.params["min_tp"]),
        float(candidate.params["max_tp"]),
    )
    sl = _clamp(
        atr_ratio * float(candidate.params["sl_atr_multiple"]),
        float(candidate.params["min_sl"]),
        float(candidate.params["max_sl"]),
    )
    return stop_take_exit(position, data, index, tp=tp, sl=sl)


def trailing_exit(candidate: ExitCandidate, position: OpenPosition, data: Mapping[str, list[float]], index: int):
    sl = float(candidate.params["sl"])
    activation = float(candidate.params["activation"])
    trail = float(candidate.params["trail"])
    high = data["high"][index]
    low = data["low"][index]
    if position.direction > 0:
        hard_stop = position.entry_price * (1.0 - sl)
        if low <= hard_stop:
            return _apply_exit_slippage(hard_stop, position.direction, SLIPPAGE_RATE), "stop_loss"
        if not position.activated and high >= position.entry_price * (1.0 + activation):
            position.activated = True
            position.extreme_price = high
            return None
        if position.activated:
            position.extreme_price = max(position.extreme_price, high)
            trail_stop = position.extreme_price * (1.0 - trail)
            if low <= trail_stop:
                return _apply_exit_slippage(trail_stop, position.direction, SLIPPAGE_RATE), "trailing_take_profit"
    else:
        hard_stop = position.entry_price * (1.0 + sl)
        if high >= hard_stop:
            return _apply_exit_slippage(hard_stop, position.direction, SLIPPAGE_RATE), "stop_loss"
        if not position.activated and low <= position.entry_price * (1.0 - activation):
            position.activated = True
            position.extreme_price = low
            return None
        if position.activated:
            position.extreme_price = min(position.extreme_price, low)
            trail_stop = position.extreme_price * (1.0 + trail)
            if high >= trail_stop:
                return _apply_exit_slippage(trail_stop, position.direction, SLIPPAGE_RATE), "trailing_take_profit"
    return None


def partial_trailing_exit(candidate: ExitCandidate, position: OpenPosition, data: Mapping[str, list[float]], index: int):
    sl = float(candidate.params["sl"])
    first_tp = float(candidate.params["first_tp"])
    partial_ratio = float(candidate.params["partial_ratio"])
    trail = float(candidate.params["trail"])
    high = data["high"][index]
    low = data["low"][index]
    if position.direction > 0:
        hard_stop = position.entry_price * (1.0 - sl)
        if low <= hard_stop:
            return _apply_exit_slippage(hard_stop, position.direction, SLIPPAGE_RATE), "stop_loss"
        if not position.partial_done and high >= position.entry_price * (1.0 + first_tp):
            partial_price = _apply_exit_slippage(position.entry_price * (1.0 + first_tp), position.direction, SLIPPAGE_RATE)
            realize_partial(position, partial_price, partial_ratio)
            position.partial_done = True
            position.activated = True
            position.extreme_price = high
            return None
        if position.partial_done:
            position.extreme_price = max(position.extreme_price, high)
            trail_stop = position.extreme_price * (1.0 - trail)
            if low <= trail_stop:
                return _apply_exit_slippage(trail_stop, position.direction, SLIPPAGE_RATE), "partial_trailing_exit"
    else:
        hard_stop = position.entry_price * (1.0 + sl)
        if high >= hard_stop:
            return _apply_exit_slippage(hard_stop, position.direction, SLIPPAGE_RATE), "stop_loss"
        if not position.partial_done and low <= position.entry_price * (1.0 - first_tp):
            partial_price = _apply_exit_slippage(position.entry_price * (1.0 - first_tp), position.direction, SLIPPAGE_RATE)
            realize_partial(position, partial_price, partial_ratio)
            position.partial_done = True
            position.activated = True
            position.extreme_price = low
            return None
        if position.partial_done:
            position.extreme_price = min(position.extreme_price, low)
            trail_stop = position.extreme_price * (1.0 + trail)
            if high >= trail_stop:
                return _apply_exit_slippage(trail_stop, position.direction, SLIPPAGE_RATE), "partial_trailing_exit"
    return None


def stop_take_exit(position: OpenPosition, data: Mapping[str, list[float]], index: int, *, tp: float, sl: float):
    high = data["high"][index]
    low = data["low"][index]
    if position.direction > 0:
        stop = position.entry_price * (1.0 - sl)
        take = position.entry_price * (1.0 + tp)
        if low <= stop:
            return _apply_exit_slippage(stop, position.direction, SLIPPAGE_RATE), "stop_loss"
        if high >= take:
            return _apply_exit_slippage(take, position.direction, SLIPPAGE_RATE), "take_profit"
    else:
        stop = position.entry_price * (1.0 + sl)
        take = position.entry_price * (1.0 - tp)
        if high >= stop:
            return _apply_exit_slippage(stop, position.direction, SLIPPAGE_RATE), "stop_loss"
        if low <= take:
            return _apply_exit_slippage(take, position.direction, SLIPPAGE_RATE), "take_profit"
    return None


def realize_partial(position: OpenPosition, exit_price: float, partial_ratio: float) -> None:
    close_ratio = min(position.remaining_ratio, partial_ratio)
    close_notional = position.notional * close_ratio
    gross_return = (exit_price - position.entry_price) / position.entry_price * position.direction
    position.realized_gross_pnl += close_notional * gross_return
    position.exit_fee_paid += close_notional * FEE_RATE
    position.remaining_ratio -= close_ratio


def close_position(position: OpenPosition, exit_price: float, exit_reason: str) -> dict[str, float | str]:
    close_notional = position.notional * position.remaining_ratio
    gross_return = (exit_price - position.entry_price) / position.entry_price * position.direction
    gross_pnl = position.realized_gross_pnl + close_notional * gross_return
    entry_fee = position.notional * FEE_RATE
    exit_fee = position.exit_fee_paid + close_notional * FEE_RATE
    fee_paid = entry_fee + exit_fee
    net_pnl = gross_pnl - fee_paid
    return {
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "fee_paid": fee_paid,
        "exit_reason": exit_reason,
    }


def entry_filter_passes(candidate: ExitCandidate, data: Mapping[str, list[float]], index: int) -> bool:
    min_atr = float(candidate.filters.get("min_atr_ratio", 0.0))
    min_range = float(candidate.filters.get("min_range_ratio", 0.0))
    min_volume = float(candidate.filters.get("min_volume_ratio", 0.0))
    if min_atr and data["atr_ratio"][index] < min_atr:
        return False
    if min_range and data["range_ratio_60"][index] < min_range:
        return False
    if min_volume:
        avg_volume = data["volume_avg_60"][index]
        volume_ratio = data["volume"][index] / avg_volume if avg_volume > 0 else 0.0
        if volume_ratio < min_volume:
            return False
    return True


def combine_result(candidate: ExitCandidate, train: Mapping[str, object], test: Mapping[str, object]) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "exit_kind": candidate.kind,
        "exit_params": dict(candidate.params),
        "filters": dict(candidate.filters),
        **_prefix("train", train),
        **_prefix("test", test),
    }


def rank_results(results: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        dict(result)
        for result in sorted(
            results,
            key=lambda result: (
                float(result["train_return_ratio"]) > 0,
                float(result["test_return_ratio"]) > 0,
                -float(result["test_max_drawdown_ratio"]),
                float(result["test_average_net_trade_roe"]),
                float(result["test_return_ratio"]),
                float(result["train_return_ratio"]),
            ),
            reverse=True,
        )
    ]


def family_best(results: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    best: dict[str, dict[str, object]] = {}
    for row in results:
        kind = str(row["exit_kind"])
        if kind not in best:
            best[kind] = dict(row)
    return list(best.values())


def validate_external(finalists: Sequence[Mapping[str, object]]) -> dict[str, object]:
    combo = selected_combo()
    rows = []
    candidates = {candidate.candidate_id: candidate for candidate in build_exit_candidates()}
    for finalist in finalists:
        candidate = candidates[str(finalist["candidate_id"])]
        period_results = []
        for raw_period in BTC_RECHECK_PERIODS:
            period = PeriodSpec(*raw_period)
            print(f"external {candidate.candidate_id} {period.label}", flush=True)
            market = load_period_market(period)
            metrics = None if market is None else simulate_exit_candidate(
                market=market,
                candidate=candidate,
                start_at=period.start_at,
                end_at=period.end_at,
                strategy_params=combo.strategy_params,
                sizing_params=combo.position_sizing_params,
            )
            period_results.append({"period": period.label, "symbol": period.symbol, "status": "no_data" if metrics is None else "ok", "metrics": metrics})
        rows.append({"candidate": finalist, "period_results": period_results})
    return {"cost_model": cost_model(), "finalists": rows}


def _prepare_data(candles) -> dict[str, list[float]]:
    data = _precomputed(candles)
    highs = data["high"]
    lows = data["low"]
    closes = data["close"]
    volumes = data["volume"]
    atr = [0.0] * len(closes)
    for index in range(len(closes)):
        if index == 0:
            true_range = highs[index] - lows[index]
        else:
            true_range = max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        atr[index] = true_range
    atr_60 = _rolling_prior_average(atr, 60)
    data["atr_ratio"] = [atr_60[index] / closes[index] if closes[index] > 0 else 0.0 for index in range(len(closes))]
    data["volume_avg_60"] = _rolling_prior_average(volumes, 60)
    data["range_ratio_60"] = [
        (data["high_60"][index] - data["low_60"][index]) / closes[index] if closes[index] > 0 else 0.0
        for index in range(len(closes))
    ]
    return data


def _data_for_period(market, start_at: datetime, end_at: datetime) -> dict[str, list[float]]:
    cache_key = (id(market), start_at, end_at)
    data = _DATA_CACHE.get(cache_key)
    if data is None:
        candles = [candle for candle in market.candles if start_at <= candle.opened_at < end_at]
        data = _prepare_data(candles)
        _DATA_CACHE[cache_key] = data
    return data


def _prefix(prefix: str, metrics: Mapping[str, object]) -> dict[str, object]:
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


def markdown_search_summary(payload: Mapping[str, object], *, limit: int) -> str:
    lines = [
        "# Scalping Exit Model Search",
        "",
        _cost_line(),
        "",
        "| Rank | Candidate | Kind | Train Net | Test Net | Test Avg Net ROE | Test MDD | Test Trades | Test Trades/day |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, row in enumerate(payload["results"][:limit], start=1):
        lines.append(
            "| {rank} | {candidate_id} | {exit_kind} | {train_return_ratio:.4f} | {test_return_ratio:.4f} | "
            "{test_average_net_trade_roe:.4f} | {test_max_drawdown_ratio:.4f} | {test_trade_count} | {test_trades_per_day:.2f} |".format(
                rank=rank,
                **row,
            )
        )
    lines.append("")
    lines.extend(
        [
            "## Family Best",
            "",
            "| Kind | Candidate | Train Net | Test Net | Test Avg Net ROE | Test MDD | Test Trades/day |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in payload["family_best"]:
        lines.append(
            "| {exit_kind} | {candidate_id} | {train_return_ratio:.4f} | {test_return_ratio:.4f} | "
            "{test_average_net_trade_roe:.4f} | {test_max_drawdown_ratio:.4f} | {test_trades_per_day:.2f} |".format(
                **row
            )
        )
    lines.append("")
    return "\n".join(lines)


def markdown_external_summary(payload: Mapping[str, object]) -> str:
    lines = [
        "# Scalping Exit Model External Validation",
        "",
        _cost_line(),
        "",
    ]
    for finalist in payload["finalists"]:
        candidate = finalist["candidate"]
        lines.extend(
            [
                f"## {candidate['candidate_id']}",
                "",
                "| Period | Net | Avg Net ROE | MDD | Trades | Trades/day |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for row in finalist["period_results"]:
            if row["status"] != "ok":
                lines.append(f"| {row['period']} | no_data |  |  |  |  |")
                continue
            metrics = row["metrics"]
            lines.append(
                "| {period} | {return_ratio:.4f} | {average_net_trade_roe:.4f} | {max_drawdown_ratio:.4f} | {trade_count} | {trades_per_day:.2f} |".format(
                    period=row["period"],
                    **metrics,
                )
            )
        lines.append("")
    return "\n".join(lines)


def cost_model() -> dict[str, object]:
    return {
        "venue": "binance_usd_m_futures",
        "fee_model": "taker_fee_entry_and_exit",
        "fee_rate_per_side": FEE_RATE,
        "slippage_model": "adverse_fill_entry_and_exit",
        "slippage_rate_per_side": SLIPPAGE_RATE,
        "funding_fee": "excluded",
    }


def _cost_line() -> str:
    return (
        "Cost: Binance USD-M futures taker fee 0.04% per side, "
        "adverse slippage 0.02% per side, funding excluded."
    )


def _avg(values: Sequence[float | int]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def _param_text(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.4f}".replace(".", "_")
    return str(value)


if __name__ == "__main__":
    main()
