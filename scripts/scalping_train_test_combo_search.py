from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_combo_search import Combo, FixedRatioTakeProfitStopLossStrategy  # noqa: E402
from scripts.novel_train_test_combo_search import (  # noqa: E402
    CACHE_PATH,
    FETCH_END,
    SYMBOL,
    TEST_END,
    TEST_START,
    TIMEFRAME,
    TRAIN_END,
    TRAIN_START,
    QualityVolatilitySizingStrategy,
    _average_net_trade_return,
    _candle_limit_for_combo,
    _prefix_result,
    gross_trade_metrics,
    load_or_fetch_market,
    stringify_mapping,
)
from src.domain.signal import Signal, SignalDirection  # noqa: E402
from src.domain.strategy.strategy_result import StrategyResult  # noqa: E402


RESULTS_PATH = Path("docs/backtests/scalping-train-test-combo-search.jsonl")
SUMMARY_PATH = Path("docs/backtests/scalping-train-test-combo-search-summary.json")
TEST_DAYS = Decimal(str((TEST_END - TEST_START).total_seconds())) / Decimal("86400")
_DATA_CACHE: dict[tuple[int, datetime, datetime], dict[str, object]] = {}


@dataclass(frozen=True)
class TrendPullbackScalper:
    name: str = "trend-pullback-scalper"
    trend_period: int = 120
    pullback_period: int = 8
    trigger_period: int = 2
    min_trend_return: Decimal = Decimal("0.004")
    min_pullback: Decimal = Decimal("0.0012")
    min_trigger_return: Decimal = Decimal("0.0004")
    min_range_ratio: Decimal = Decimal("0.0015")

    def evaluate(self, context) -> StrategyResult:
        candles = context.market.candles
        required = max(self.trend_period, self.pullback_period, self.trigger_period) + 2
        if len(candles) < required:
            return _wait(self.name)
        latest = candles[-1]
        trend_base = candles[-self.trend_period - 1].close_price
        trigger_base = candles[-self.trigger_period - 1].close_price
        trend_return = _return_ratio(latest.close_price, trend_base)
        trigger_return = _return_ratio(latest.close_price, trigger_base)
        pullback_window = candles[-self.pullback_period - 1 : -1]
        range_ratio = _range_ratio(pullback_window)
        if range_ratio < self.min_range_ratio:
            return _wait(self.name)
        high = max(candle.high_price for candle in pullback_window)
        low = min(candle.low_price for candle in pullback_window)

        if trend_return >= self.min_trend_return:
            pullback = (high - latest.close_price) / latest.close_price
            if pullback >= self.min_pullback and trigger_return >= self.min_trigger_return:
                return _signal(self.name, SignalDirection.LONG, Decimal("0.72"))
        if trend_return <= -self.min_trend_return:
            pullback = (latest.close_price - low) / latest.close_price
            if pullback >= self.min_pullback and trigger_return <= -self.min_trigger_return:
                return _signal(self.name, SignalDirection.SHORT, Decimal("0.72"))
        return _wait(self.name)


@dataclass(frozen=True)
class RangeEdgeReversionScalper:
    name: str = "range-edge-reversion-scalper"
    range_period: int = 90
    edge_ratio: Decimal = Decimal("0.12")
    min_reversal_body_ratio: Decimal = Decimal("0.25")
    min_range_ratio: Decimal = Decimal("0.002")

    def evaluate(self, context) -> StrategyResult:
        candles = context.market.candles
        if len(candles) < self.range_period + 2:
            return _wait(self.name)
        latest = candles[-1]
        window = candles[-self.range_period - 1 : -1]
        low = min(candle.low_price for candle in window)
        high = max(candle.high_price for candle in window)
        width = high - low
        if low <= Decimal("0") or width / low < self.min_range_ratio:
            return _wait(self.name)
        candle_range = latest.high_price - latest.low_price
        if candle_range <= Decimal("0"):
            return _wait(self.name)
        body = latest.close_price - latest.open_price
        body_ratio = abs(body) / candle_range
        close_position = (latest.close_price - low) / width
        if close_position <= self.edge_ratio and body > 0 and body_ratio >= self.min_reversal_body_ratio:
            return _signal(self.name, SignalDirection.LONG, Decimal("0.68"))
        if close_position >= Decimal("1") - self.edge_ratio and body < 0 and body_ratio >= self.min_reversal_body_ratio:
            return _signal(self.name, SignalDirection.SHORT, Decimal("0.68"))
        return _wait(self.name)


@dataclass(frozen=True)
class MomentumBurstScalper:
    name: str = "momentum-burst-scalper"
    breakout_period: int = 30
    impulse_period: int = 3
    volume_period: int = 45
    min_impulse_return: Decimal = Decimal("0.0012")
    min_volume_ratio: Decimal = Decimal("1.2")
    breakout_buffer: Decimal = Decimal("0.0001")
    mode: str = "follow"

    def evaluate(self, context) -> StrategyResult:
        candles = context.market.candles
        required = max(self.breakout_period, self.impulse_period, self.volume_period) + 2
        if len(candles) < required:
            return _wait(self.name)
        latest = candles[-1]
        prior = candles[-self.breakout_period - 1 : -1]
        high = max(candle.high_price for candle in prior)
        low = min(candle.low_price for candle in prior)
        impulse_base = candles[-self.impulse_period - 1].close_price
        impulse = _return_ratio(latest.close_price, impulse_base)
        average_volume = _average(candle.volume for candle in candles[-self.volume_period - 1 : -1])
        volume_ratio = latest.volume / average_volume if average_volume > Decimal("0") else Decimal("0")
        if (
            impulse >= self.min_impulse_return
            and volume_ratio >= self.min_volume_ratio
            and latest.close_price > high * (Decimal("1") + self.breakout_buffer)
        ):
            direction = SignalDirection.SHORT if self.mode == "fade" else SignalDirection.LONG
            return _signal(self.name, direction, Decimal("0.64"))
        if (
            impulse <= -self.min_impulse_return
            and volume_ratio >= self.min_volume_ratio
            and latest.close_price < low * (Decimal("1") - self.breakout_buffer)
        ):
            direction = SignalDirection.LONG if self.mode == "fade" else SignalDirection.SHORT
            return _signal(self.name, direction, Decimal("0.64"))
        return _wait(self.name)


@dataclass(frozen=True)
class RegimeRouterScalper:
    name: str = "regime-router-scalper"
    trend_params: Mapping[str, object] | None = None
    range_params: Mapping[str, object] | None = None
    burst_params: Mapping[str, object] | None = None
    router_order: tuple[str, ...] = ("burst", "trend", "range")
    max_abs_trend_for_range: Decimal = Decimal("0.006")
    range_regime_period: int = 240
    trend_regime_period: int = 240

    def evaluate(self, context) -> StrategyResult:
        candles = context.market.candles
        if len(candles) < max(self.range_regime_period, self.trend_regime_period) + 2:
            return _wait(self.name)
        latest = candles[-1]
        trend_base = candles[-self.trend_regime_period - 1].close_price
        trend = _return_ratio(latest.close_price, trend_base)
        range_window = candles[-self.range_regime_period - 1 : -1]
        regime_range = _range_ratio(range_window)
        strategies = {
            "burst": MomentumBurstScalper(**dict(self.burst_params or {})),
            "trend": TrendPullbackScalper(**dict(self.trend_params or {})),
            "range": RangeEdgeReversionScalper(**dict(self.range_params or {})),
        }
        for key in self.router_order:
            if key == "range" and abs(trend) > self.max_abs_trend_for_range:
                continue
            if key == "trend" and regime_range <= Decimal("0"):
                continue
            result = strategies[key].evaluate(context)
            if result.signal.direction is not SignalDirection.WAIT:
                return StrategyResult(name=self.name, signal=result.signal)
        return _wait(self.name)


def run_combo_for_period(market, combo: Combo, *, start_at: datetime, end_at: datetime, fee_rate: Decimal) -> dict[str, object]:
    result = _simulate_scalping_fast(
        market=market,
        combo=combo,
        start_at=start_at,
        end_at=end_at,
        fee_rate=float(fee_rate),
    )
    return {
        "combo_id": combo.combo_id,
        "trade_count": result["trade_count"],
        "win_rate": str(result["net_win_rate"]),
        "return_ratio": str(result["return_ratio"]),
        "net_pnl": str(result["net_pnl"]),
        "max_drawdown_ratio": str(result["max_drawdown_ratio"]),
        "average_net_trade_return": str(result["average_net_trade_return"]),
        "gross_win_rate": str(result["gross_win_rate"]),
        "average_gross_trade_return": str(result["average_gross_trade_return"]),
        "average_gross_trade_roe": str(result["average_gross_trade_roe"]),
        "gross_pnl": str(result["gross_pnl"]),
        "fee_paid": str(result["fee_paid"]),
        "strategy_params": stringify_mapping(combo.strategy_params),
        "tpsl_params": stringify_mapping(combo.tpsl_params),
        "position_sizing_params": stringify_mapping(combo.position_sizing_params),
    }


def combine_result(train_result: Mapping[str, object], test_result: Mapping[str, object]) -> dict[str, object]:
    combined = {
        "combo_id": train_result["combo_id"],
        "train_period": {"start_at": TRAIN_START.isoformat(), "end_at": TRAIN_END.isoformat()},
        "test_period": {"start_at": TEST_START.isoformat(), "end_at": TEST_END.isoformat()},
        "strategy_params": train_result["strategy_params"],
        "tpsl_params": train_result["tpsl_params"],
        "position_sizing_params": train_result["position_sizing_params"],
        **_prefix_scalping_result("train", train_result),
        **_prefix_scalping_result("test", test_result),
    }
    combined["test_trades_per_day"] = str(
        Decimal(str(test_result["trade_count"])) / TEST_DAYS
    )
    combined["train_trades_per_day"] = str(
        Decimal(str(train_result["trade_count"]))
        / (Decimal(str((TRAIN_END - TRAIN_START).total_seconds())) / Decimal("86400"))
    )
    return combined


def build_combos() -> list[Combo]:
    trend_grid = [
        {"trend_period": 60, "pullback_period": 5, "trigger_period": 1, "min_trend_return": Decimal("0.002"), "min_pullback": Decimal("0.0006"), "min_trigger_return": Decimal("0.0002"), "min_range_ratio": Decimal("0.0008")},
        {"trend_period": 120, "pullback_period": 8, "trigger_period": 2, "min_trend_return": Decimal("0.004"), "min_pullback": Decimal("0.0010"), "min_trigger_return": Decimal("0.0003"), "min_range_ratio": Decimal("0.0012")},
        {"trend_period": 240, "pullback_period": 12, "trigger_period": 3, "min_trend_return": Decimal("0.006"), "min_pullback": Decimal("0.0015"), "min_trigger_return": Decimal("0.0004"), "min_range_ratio": Decimal("0.0015")},
    ]
    range_grid = [
        {"range_period": 45, "edge_ratio": Decimal("0.18"), "min_reversal_body_ratio": Decimal("0.15"), "min_range_ratio": Decimal("0.0015")},
        {"range_period": 90, "edge_ratio": Decimal("0.15"), "min_reversal_body_ratio": Decimal("0.20"), "min_range_ratio": Decimal("0.0020")},
        {"range_period": 180, "edge_ratio": Decimal("0.12"), "min_reversal_body_ratio": Decimal("0.25"), "min_range_ratio": Decimal("0.0030")},
    ]
    burst_grid = [
        {"breakout_period": 12, "impulse_period": 1, "volume_period": 20, "min_impulse_return": Decimal("0.0008"), "min_volume_ratio": Decimal("1.0"), "breakout_buffer": Decimal("0.0000"), "mode": "follow"},
        {"breakout_period": 30, "impulse_period": 3, "volume_period": 45, "min_impulse_return": Decimal("0.0012"), "min_volume_ratio": Decimal("1.2"), "breakout_buffer": Decimal("0.0001"), "mode": "follow"},
        {"breakout_period": 60, "impulse_period": 5, "volume_period": 60, "min_impulse_return": Decimal("0.0018"), "min_volume_ratio": Decimal("1.5"), "breakout_buffer": Decimal("0.0002"), "mode": "follow"},
        {"breakout_period": 12, "impulse_period": 1, "volume_period": 20, "min_impulse_return": Decimal("0.0008"), "min_volume_ratio": Decimal("1.0"), "breakout_buffer": Decimal("0.0000"), "mode": "fade"},
        {"breakout_period": 30, "impulse_period": 3, "volume_period": 45, "min_impulse_return": Decimal("0.0012"), "min_volume_ratio": Decimal("1.2"), "breakout_buffer": Decimal("0.0001"), "mode": "fade"},
    ]
    router_grid = [
        ("router-btr", ("burst", "trend", "range"), Decimal("0.006")),
        ("router-rbt", ("range", "burst", "trend"), Decimal("0.004")),
        ("router-tbr", ("trend", "burst", "range"), Decimal("0.008")),
    ]
    tpsl_grid = [
        ("sl0030-rr0_35", Decimal("0.0030"), Decimal("0.35")),
        ("sl0040-rr0_30", Decimal("0.0040"), Decimal("0.30")),
        ("sl0050-rr0_25", Decimal("0.0050"), Decimal("0.25")),
        ("sl0025-rr0_50", Decimal("0.0025"), Decimal("0.50")),
        ("sl0020-rr0_70", Decimal("0.0020"), Decimal("0.70")),
        ("sl0012-rr2_5", Decimal("0.0012"), Decimal("2.5")),
        ("sl0015-rr2_2", Decimal("0.0015"), Decimal("2.2")),
        ("sl0020-rr1_8", Decimal("0.0020"), Decimal("1.8")),
        ("sl0025-rr1_5", Decimal("0.0025"), Decimal("1.5")),
        ("sl0030-rr1_2", Decimal("0.0030"), Decimal("1.2")),
    ]
    sizing_grid = [
        {"kind": "quality-volatility", "min_equity_ratio": Decimal("0.01"), "max_equity_ratio": Decimal("0.08"), "min_leverage": Decimal("1"), "max_leverage": Decimal("5")},
        {"kind": "quality-volatility", "min_equity_ratio": Decimal("0.02"), "max_equity_ratio": Decimal("0.12"), "min_leverage": Decimal("2"), "max_leverage": Decimal("8")},
    ]
    combos = []
    for trend_index, trend_params in enumerate(trend_grid, start=1):
        for range_index, range_params in enumerate(range_grid, start=1):
            for burst_index, burst_params in enumerate(burst_grid, start=1):
                for router_name, order, max_trend in router_grid:
                    strategy_params = {
                        "trend_params": trend_params,
                        "range_params": range_params,
                        "burst_params": burst_params,
                        "router_order": order,
                        "max_abs_trend_for_range": max_trend,
                        "range_regime_period": 240,
                        "trend_regime_period": 240,
                    }
                    for tpsl_name, stop_loss, reward_risk in tpsl_grid:
                        tpsl_params = {
                            "kind": "fixed",
                            "stop_loss_ratio": stop_loss,
                            "reward_risk_ratio": reward_risk,
                        }
                        for sizing_index, sizing_params in enumerate(sizing_grid, start=1):
                            combos.append(
                                Combo(
                                    combo_id=(
                                        f"scalp-multi-t{trend_index}-r{range_index}-"
                                        f"b{burst_index}-{router_name}-{tpsl_name}-p{sizing_index}"
                                    ),
                                    strategy_factory=RegimeRouterScalper,
                                    strategy_params=strategy_params,
                                    tpsl_factory=lambda params=tpsl_params: FixedRatioTakeProfitStopLossStrategy(
                                        stop_loss_ratio=params["stop_loss_ratio"],
                                        reward_risk_ratio=params["reward_risk_ratio"],
                                    ),
                                    tpsl_params=tpsl_params,
                                    position_sizing_factory=lambda params=sizing_params: QualityVolatilitySizingStrategy(
                                        min_equity_ratio=params["min_equity_ratio"],
                                        max_equity_ratio=params["max_equity_ratio"],
                                        min_leverage=params["min_leverage"],
                                        max_leverage=params["max_leverage"],
                                    ),
                                    position_sizing_params=sizing_params,
                                )
                            )
    return combos


def rank_results(results: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return sorted(
        results,
        key=lambda result: (
            Decimal(str(result["test_trades_per_day"])) >= Decimal("10"),
            Decimal(str(result["test_average_gross_trade_roe"])) >= Decimal("0.003"),
            Decimal(str(result["test_gross_win_rate"])) >= Decimal("0.55"),
            Decimal(str(result["test_return_ratio"])) > Decimal("0"),
            Decimal(str(result["train_return_ratio"])) > Decimal("0"),
            Decimal(str(result["test_return_ratio"])),
            Decimal(str(result["test_average_gross_trade_roe"])),
            Decimal(str(result["test_gross_win_rate"])),
        ),
        reverse=True,
    )


def _prefix_scalping_result(prefix: str, result: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "trade_count",
        "win_rate",
        "return_ratio",
        "net_pnl",
        "max_drawdown_ratio",
        "average_net_trade_return",
        "gross_win_rate",
        "average_gross_trade_return",
        "average_gross_trade_roe",
        "gross_pnl",
        "fee_paid",
    )
    return {f"{prefix}_{key}": result[key] for key in keys}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--combo-contains", default="")
    parser.add_argument("--fee-rate", type=Decimal, default=Decimal("0.0004"))
    args = parser.parse_args()

    market = load_or_fetch_market()
    combos = build_combos()
    if args.combo_contains:
        combos = [combo for combo in combos if args.combo_contains in combo.combo_id]
    if args.limit:
        combos = combos[: args.limit]
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with RESULTS_PATH.open("w", encoding="utf-8") as handle:
        for index, combo in enumerate(combos, start=1):
            train = run_combo_for_period(
                market,
                combo,
                start_at=TRAIN_START,
                end_at=TRAIN_END,
                fee_rate=args.fee_rate,
            )
            test = run_combo_for_period(
                market,
                combo,
                start_at=TEST_START,
                end_at=TEST_END,
                fee_rate=args.fee_rate,
            )
            combined = combine_result(train, test)
            results.append(combined)
            handle.write(json.dumps(combined, ensure_ascii=False, sort_keys=True) + "\n")
            print(
                f"{index}/{len(combos)} {combined['combo_id']} "
                f"test_trades_day={combined['test_trades_per_day']} "
                f"test_wr={combined['test_gross_win_rate']} "
                f"test_avg_gross_roe={combined['test_average_gross_trade_roe']} "
                f"test_return={combined['test_return_ratio']}"
            )
    ranked = rank_results(results)
    SUMMARY_PATH.write_text(
        json.dumps(
            {
                "cache_path": str(CACHE_PATH),
                "fetch_end": FETCH_END.isoformat(),
                "result_count": len(results),
                "top": ranked[:20],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print("SUMMARY", SUMMARY_PATH)
    for result in ranked[:10]:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def _candle_limit_for_scalping_combo(combo: Combo) -> int:
    return max(_candle_limit_for_combo(combo), 260)


def _simulate_scalping_fast(
    *,
    market,
    combo: Combo,
    start_at: datetime,
    end_at: datetime,
    fee_rate: float,
    slippage_rate: float = 0.0,
) -> dict[str, object]:
    cache_key = (id(market), start_at, end_at)
    data = _DATA_CACHE.get(cache_key)
    if data is None:
        candles = [candle for candle in market.candles if start_at <= candle.opened_at < end_at]
        data = _precomputed(candles)
        _DATA_CACHE[cache_key] = data
    strategy_params = combo.strategy_params
    tpsl_params = combo.tpsl_params
    sizing_params = combo.position_sizing_params
    stop_loss = float(tpsl_params["stop_loss_ratio"])
    reward_risk = float(tpsl_params["reward_risk_ratio"])
    leverage = float(sizing_params.get("max_leverage", Decimal("1")))
    equity = 10000.0
    peak = equity
    max_drawdown = 0.0
    trade_count = 0
    gross_wins = 0
    net_wins = 0
    gross_returns = []
    gross_roes = []
    net_returns = []
    gross_pnl = 0.0
    fee_paid = 0.0
    position = None

    candle_count = len(data["close"])
    for index in range(260, candle_count):
        high = data["high"][index]
        low = data["low"][index]
        close = data["close"][index]
        if position is not None:
            direction, entry_price, notional, margin = position
            if direction > 0:
                stop = entry_price * (1.0 - stop_loss)
                take = entry_price * (1.0 + stop_loss * reward_risk)
                exit_price = None
                if low <= stop:
                    exit_price = stop
                elif high >= take:
                    exit_price = take
            else:
                stop = entry_price * (1.0 + stop_loss)
                take = entry_price * (1.0 - stop_loss * reward_risk)
                exit_price = None
                if high >= stop:
                    exit_price = stop
                elif low <= take:
                    exit_price = take
            if exit_price is not None:
                filled_exit_price = _apply_exit_slippage(exit_price, direction, slippage_rate)
                gross_return = (filled_exit_price - entry_price) / entry_price * direction
                trade_gross_pnl = notional * gross_return
                trade_fee = notional * fee_rate * 2.0
                trade_net_pnl = trade_gross_pnl - trade_fee
                trade_count += 1
                gross_wins += 1 if trade_gross_pnl > 0 else 0
                net_wins += 1 if trade_net_pnl > 0 else 0
                gross_returns.append(gross_return)
                gross_roes.append(trade_gross_pnl / margin if margin > 0 else 0.0)
                net_returns.append(trade_net_pnl / notional if notional > 0 else 0.0)
                gross_pnl += trade_gross_pnl
                fee_paid += trade_fee
                equity += trade_net_pnl
                peak = max(peak, equity)
                if peak > 0:
                    max_drawdown = max(max_drawdown, (peak - equity) / peak)
                position = None
                continue

        direction = _evaluate_scalping_direction(data, index, strategy_params)
        if direction == 0:
            continue
        confidence = 0.68 if abs(direction) == 1 else 0.64
        equity_ratio = _scaled(confidence, float(sizing_params["min_equity_ratio"]), float(sizing_params["max_equity_ratio"]))
        lev = _scaled(confidence, float(sizing_params["min_leverage"]), float(sizing_params["max_leverage"]))
        margin = equity * equity_ratio
        notional = margin * lev
        signed_direction = 1 if direction > 0 else -1
        entry_price = _apply_entry_slippage(close, signed_direction, slippage_rate)
        position = (signed_direction, entry_price, notional, margin)

    if position is not None:
        direction, entry_price, notional, margin = position
        exit_price = _apply_exit_slippage(data["close"][-1], direction, slippage_rate)
        gross_return = (exit_price - entry_price) / entry_price * direction
        trade_gross_pnl = notional * gross_return
        trade_fee = notional * fee_rate * 2.0
        trade_net_pnl = trade_gross_pnl - trade_fee
        trade_count += 1
        gross_wins += 1 if trade_gross_pnl > 0 else 0
        net_wins += 1 if trade_net_pnl > 0 else 0
        gross_returns.append(gross_return)
        gross_roes.append(trade_gross_pnl / margin if margin > 0 else 0.0)
        net_returns.append(trade_net_pnl / notional if notional > 0 else 0.0)
        gross_pnl += trade_gross_pnl
        fee_paid += trade_fee
        equity += trade_net_pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    return {
        "trade_count": trade_count,
        "gross_win_rate": Decimal(str(gross_wins / trade_count if trade_count else 0.0)),
        "net_win_rate": Decimal(str(net_wins / trade_count if trade_count else 0.0)),
        "return_ratio": Decimal(str((equity - 10000.0) / 10000.0)),
        "net_pnl": Decimal(str(equity - 10000.0)),
        "max_drawdown_ratio": Decimal(str(max_drawdown)),
        "average_gross_trade_return": Decimal(str(sum(gross_returns) / len(gross_returns) if gross_returns else 0.0)),
        "average_gross_trade_roe": Decimal(str(sum(gross_roes) / len(gross_roes) if gross_roes else 0.0)),
        "average_net_trade_return": Decimal(str(sum(net_returns) / len(net_returns) if net_returns else 0.0)),
        "gross_pnl": Decimal(str(gross_pnl)),
        "fee_paid": Decimal(str(fee_paid)),
    }


def _apply_entry_slippage(price: float, direction: int, slippage_rate: float) -> float:
    if direction > 0:
        return price * (1.0 + slippage_rate)
    return price * (1.0 - slippage_rate)


def _apply_exit_slippage(price: float, direction: int, slippage_rate: float) -> float:
    if direction > 0:
        return price * (1.0 - slippage_rate)
    return price * (1.0 + slippage_rate)


def _evaluate_scalping_direction(data: Mapping[str, object], index: int, params: Mapping[str, object]) -> int:
    for key in params["router_order"]:
        if key == "range":
            trend = _ret(data, index, int(params["trend_regime_period"]))
            if abs(trend) > float(params["max_abs_trend_for_range"]):
                continue
            direction = _range_direction(data, index, params["range_params"])
        elif key == "trend":
            direction = _trend_direction(data, index, params["trend_params"])
        else:
            direction = _burst_direction(data, index, params["burst_params"])
        if direction != 0:
            return direction
    return 0


def _trend_direction(data, index: int, params: Mapping[str, object]) -> int:
    trend_period = int(params["trend_period"])
    pullback_period = int(params["pullback_period"])
    trigger_period = int(params["trigger_period"])
    trend = _ret(data, index, trend_period)
    trigger = _ret(data, index, trigger_period)
    high = data[f"high_{pullback_period}"][index]
    low = data[f"low_{pullback_period}"][index]
    close = data["close"][index]
    range_ratio = (high - low) / low if low > 0 else 0.0
    if range_ratio < float(params["min_range_ratio"]):
        return 0
    if trend >= float(params["min_trend_return"]):
        pullback = (high - close) / close
        if pullback >= float(params["min_pullback"]) and trigger >= float(params["min_trigger_return"]):
            return 1
    if trend <= -float(params["min_trend_return"]):
        pullback = (close - low) / close
        if pullback >= float(params["min_pullback"]) and trigger <= -float(params["min_trigger_return"]):
            return -1
    return 0


def _range_direction(data, index: int, params: Mapping[str, object]) -> int:
    period = int(params["range_period"])
    low = data[f"low_{period}"][index]
    high = data[f"high_{period}"][index]
    width = high - low
    if low <= 0 or width / low < float(params["min_range_ratio"]):
        return 0
    candle_range = data["high"][index] - data["low"][index]
    if candle_range <= 0:
        return 0
    body = data["close"][index] - data["open"][index]
    body_ratio = abs(body) / candle_range
    close_position = (data["close"][index] - low) / width
    if close_position <= float(params["edge_ratio"]) and body > 0 and body_ratio >= float(params["min_reversal_body_ratio"]):
        return 1
    if close_position >= 1.0 - float(params["edge_ratio"]) and body < 0 and body_ratio >= float(params["min_reversal_body_ratio"]):
        return -1
    return 0


def _burst_direction(data, index: int, params: Mapping[str, object]) -> int:
    breakout_period = int(params["breakout_period"])
    volume_period = int(params["volume_period"])
    impulse = _ret(data, index, int(params["impulse_period"]))
    high = data[f"high_{breakout_period}"][index]
    low = data[f"low_{breakout_period}"][index]
    avg_volume = data[f"volume_{volume_period}"][index]
    volume_ratio = data["volume"][index] / avg_volume if avg_volume > 0 else 0.0
    long_breakout = (
        impulse >= float(params["min_impulse_return"])
        and volume_ratio >= float(params["min_volume_ratio"])
        and data["close"][index] > high * (1.0 + float(params["breakout_buffer"]))
    )
    short_breakout = (
        impulse <= -float(params["min_impulse_return"])
        and volume_ratio >= float(params["min_volume_ratio"])
        and data["close"][index] < low * (1.0 - float(params["breakout_buffer"]))
    )
    fade = params.get("mode") == "fade"
    if long_breakout:
        return -1 if fade else 1
    if short_breakout:
        return 1 if fade else -1
    return 0


def _precomputed(candles) -> dict[str, object]:
    opens = [float(candle.open_price) for candle in candles]
    highs = [float(candle.high_price) for candle in candles]
    lows = [float(candle.low_price) for candle in candles]
    closes = [float(candle.close_price) for candle in candles]
    volumes = [float(candle.volume) for candle in candles]
    data: dict[str, object] = {
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    }
    for period in (5, 8, 12, 20, 30, 45, 60, 90, 120, 180, 240):
        data[f"high_{period}"] = _rolling_prior(highs, period, max)
        data[f"low_{period}"] = _rolling_prior(lows, period, min)
        data[f"volume_{period}"] = _rolling_prior_average(volumes, period)
    return data


def _rolling_prior(values: Sequence[float], period: int, fn) -> list[float]:
    output = [0.0] * len(values)
    for index in range(len(values)):
        start = max(0, index - period)
        window = values[start:index]
        output[index] = fn(window) if window else values[index]
    return output


def _rolling_prior_average(values: Sequence[float], period: int) -> list[float]:
    output = [0.0] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        if index > 0:
            running += values[index - 1]
        if index > period:
            running -= values[index - period - 1]
        count = min(index, period)
        output[index] = running / count if count else value
    return output


def _ret(data, index: int, period: int) -> float:
    base_index = index - period
    if base_index < 0:
        return 0.0
    base = data["close"][base_index]
    return (data["close"][index] - base) / base if base > 0 else 0.0


def _scaled(confidence: float, minimum: float, maximum: float) -> float:
    confidence = min(1.0, max(0.0, confidence))
    return minimum + (maximum - minimum) * confidence


def _signal(name: str, direction: SignalDirection, confidence: Decimal) -> StrategyResult:
    return StrategyResult(name=name, signal=Signal(direction=direction, confidence=confidence))


def _wait(name: str) -> StrategyResult:
    return StrategyResult(name=name, signal=Signal.wait())


def _return_ratio(current: Decimal, base: Decimal) -> Decimal:
    if base <= Decimal("0"):
        return Decimal("0")
    return (current - base) / base


def _range_ratio(candles) -> Decimal:
    candles = tuple(candles)
    if not candles:
        return Decimal("0")
    low = min(candle.low_price for candle in candles)
    high = max(candle.high_price for candle in candles)
    if low <= Decimal("0"):
        return Decimal("0")
    return (high - low) / low


def _average(values: Iterable[Decimal]) -> Decimal:
    values = tuple(values)
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


if __name__ == "__main__":
    main()
