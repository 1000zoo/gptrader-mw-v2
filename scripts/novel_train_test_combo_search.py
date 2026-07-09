from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO, TextIOWrapper
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_combo_search import (  # noqa: E402
    Combo,
    FixedRatioTakeProfitStopLossStrategy,
    candle_from_record,
    candle_record,
)
from src.application.usecases.research.dto import BacktestTrade  # noqa: E402
from src.application.usecases.research.backtest_simulator import (  # noqa: E402
    _OpenPosition,
    _backtest_exposure_limit,
    _close_trade,
    _drawdown_ratio,
    _entry_action,
    _entry_price,
    _exit_for_candle,
    _is_opposite_signal,
    _performance,
)
from src.domain.indicator import IndicatorSet  # noqa: E402
from src.domain.market import MarketSnapshot, Symbol, Timeframe  # noqa: E402
from src.domain.risk import (  # noqa: E402
    ExposureLimit,
    PositionSizingDecision,
)
from src.domain.signal import Signal, SignalDirection, TradeDecision  # noqa: E402
from src.domain.strategy import StaticStrategyCatalog, StrategyContext, StrategySpec  # noqa: E402
from src.domain.strategy.strategy_result import StrategyResult  # noqa: E402
from src.domain.strategy.take_profit_stop_loss import TakeProfitStopLossLevels  # noqa: E402
from src.observability.logging import configure_runtime_logging  # noqa: E402


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")
TRAIN_START = datetime(2025, 10, 1, 0, 0, tzinfo=timezone.utc)
TRAIN_END = datetime(2026, 4, 30, 0, 0, tzinfo=timezone.utc)
TEST_START = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)
TEST_END = datetime(2026, 7, 8, 0, 0, tzinfo=timezone.utc)
FETCH_END = TEST_END + timedelta(days=1)
CACHE_PATH = Path("docs/backtests/cache/btcusdt-1m-20251001-20260709.jsonl")
LOCK_PATH = Path("docs/backtests/cache/btcusdt-1m-20251001-20260709.lock")
RESULTS_PATH = Path("docs/backtests/novel-train-test-combo-search.jsonl")


@dataclass(frozen=True)
class VolatilityCompressionBreakoutStrategy:
    name: str = "volatility-compression-breakout"
    lookback: int = 180
    compression_period: int = 45
    compression_ratio: Decimal = Decimal("0.45")
    breakout_buffer: Decimal = Decimal("0.0006")
    min_volume_ratio: Decimal = Decimal("1.10")
    direction_filter_period: int = 720
    min_filter_return: Decimal = Decimal("0.002")
    _lookback_range: object = None
    _compression_range: object = None
    _volume_average: object = None

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.lookback, self.direction_filter_period) + 2
        if len(candles) < required:
            return StrategyResult(name=self.name, signal=Signal.wait())

        latest = candles[-1]
        full_low, full_high = self._range("lookback", candles)
        compression_low, compression_high = self._range("compression", candles)
        if full_low is None or compression_low is None:
            return StrategyResult(name=self.name, signal=Signal.wait())

        full_range = _range_ratio_from_bounds(full_low, full_high)
        compression_range = _range_ratio_from_bounds(compression_low, compression_high)
        if full_range <= Decimal("0"):
            return StrategyResult(name=self.name, signal=Signal.wait())
        if compression_range / full_range > self.compression_ratio:
            return StrategyResult(name=self.name, signal=Signal.wait())

        average_volume = self._average_volume(candles)
        if average_volume > Decimal("0") and latest.volume / average_volume < self.min_volume_ratio:
            return StrategyResult(name=self.name, signal=Signal.wait())

        trend_base = candles[-self.direction_filter_period - 1].close_price
        trend_return = (latest.close_price - trend_base) / trend_base
        high = full_high
        low = full_low

        if (
            trend_return >= self.min_filter_return
            and latest.close_price > high * (Decimal("1") + self.breakout_buffer)
        ):
            return _directional_result(self.name, SignalDirection.LONG, Decimal("0.86"))
        if (
            trend_return <= -self.min_filter_return
            and latest.close_price < low * (Decimal("1") - self.breakout_buffer)
        ):
            return _directional_result(self.name, SignalDirection.SHORT, Decimal("0.86"))
        return StrategyResult(name=self.name, signal=Signal.wait())

    def _range(self, kind: str, candles):
        attr = "_lookback_range" if kind == "lookback" else "_compression_range"
        period = self.lookback if kind == "lookback" else self.compression_period
        window = getattr(self, attr)
        if window is None:
            window = RollingRange(period)
            object.__setattr__(self, attr, window)
        return window.range(candles)

    def _average_volume(self, candles) -> Decimal:
        if self._volume_average is None:
            object.__setattr__(self, "_volume_average", RollingAverage(self.lookback))
        return self._volume_average.average(candles[-2])


@dataclass(frozen=True)
class LiquiditySweepReclaimStrategy:
    name: str = "liquidity-sweep-reclaim"
    sweep_period: int = 360
    reclaim_buffer: Decimal = Decimal("0.0004")
    min_wick_ratio: Decimal = Decimal("0.35")
    max_close_position_long: Decimal = Decimal("0.35")
    min_close_position_short: Decimal = Decimal("0.65")
    min_range_width: Decimal = Decimal("0.006")
    _sweep_range: object = None

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        if len(candles) < self.sweep_period + 2:
            return StrategyResult(name=self.name, signal=Signal.wait())

        latest = candles[-1]
        low, high = self._range(candles)
        if low is None or high is None:
            return StrategyResult(name=self.name, signal=Signal.wait())
        if low <= Decimal("0") or high <= low:
            return StrategyResult(name=self.name, signal=Signal.wait())
        if (high - low) / low < self.min_range_width:
            return StrategyResult(name=self.name, signal=Signal.wait())

        candle_range = latest.high_price - latest.low_price
        if candle_range <= Decimal("0"):
            return StrategyResult(name=self.name, signal=Signal.wait())
        close_position = (latest.close_price - latest.low_price) / candle_range
        lower_wick = min(latest.open_price, latest.close_price) - latest.low_price
        upper_wick = latest.high_price - max(latest.open_price, latest.close_price)

        swept_low = latest.low_price < low and latest.close_price > low * (
            Decimal("1") + self.reclaim_buffer
        )
        swept_high = latest.high_price > high and latest.close_price < high * (
            Decimal("1") - self.reclaim_buffer
        )
        if (
            swept_low
            and lower_wick / candle_range >= self.min_wick_ratio
            and close_position >= self.max_close_position_long
        ):
            return _directional_result(self.name, SignalDirection.LONG, Decimal("0.92"))
        if (
            swept_high
            and upper_wick / candle_range >= self.min_wick_ratio
            and close_position <= self.min_close_position_short
        ):
            return _directional_result(self.name, SignalDirection.SHORT, Decimal("0.92"))
        return StrategyResult(name=self.name, signal=Signal.wait())

    def _range(self, candles):
        if self._sweep_range is None:
            object.__setattr__(self, "_sweep_range", RollingRange(self.sweep_period))
        return self._sweep_range.range(candles)


@dataclass(frozen=True)
class MultiWindowPullbackResumeStrategy:
    name: str = "multi-window-pullback-resume"
    trend_period: int = 2880
    pullback_period: int = 240
    trigger_period: int = 12
    min_trend_return: Decimal = Decimal("0.018")
    min_pullback: Decimal = Decimal("0.004")
    resume_return: Decimal = Decimal("0.0008")
    _pullback_range: object = None

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.trend_period, self.pullback_period, self.trigger_period) + 2
        if len(candles) < required:
            return StrategyResult(name=self.name, signal=Signal.wait())
        latest = candles[-1]
        trend_base = candles[-self.trend_period - 1].close_price
        trend_return = (latest.close_price - trend_base) / trend_base
        pullback_low, pullback_high = self._range(candles)
        if pullback_low is None or pullback_high is None:
            return StrategyResult(name=self.name, signal=Signal.wait())
        trigger_base = candles[-self.trigger_period - 1].close_price
        trigger_return = (latest.close_price - trigger_base) / trigger_base

        if trend_return >= self.min_trend_return:
            pullback_from_high = (pullback_high - latest.close_price) / latest.close_price
            if pullback_from_high >= self.min_pullback and trigger_return >= self.resume_return:
                return _directional_result(self.name, SignalDirection.LONG, Decimal("0.88"))
        if trend_return <= -self.min_trend_return:
            pullback_from_low = (latest.close_price - pullback_low) / latest.close_price
            if pullback_from_low >= self.min_pullback and trigger_return <= -self.resume_return:
                return _directional_result(self.name, SignalDirection.SHORT, Decimal("0.88"))
        return StrategyResult(name=self.name, signal=Signal.wait())

    def _range(self, candles):
        if self._pullback_range is None:
            object.__setattr__(self, "_pullback_range", RollingRange(self.pullback_period))
        return self._pullback_range.range(candles)


@dataclass(frozen=True)
class TimeboxedTrendAccelerationStrategy:
    name: str = "timeboxed-trend-acceleration"
    trend_period: int = 1440
    impulse_period: int = 15
    min_trend: Decimal = Decimal("0.01")
    min_impulse: Decimal = Decimal("0.002")
    hour: int = 0
    side: str = "both"

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.trend_period, self.impulse_period) + 2
        if len(candles) < required:
            return StrategyResult(name=self.name, signal=Signal.wait())

        latest = candles[-1]
        if latest.opened_at.hour != self.hour or latest.opened_at.minute != 0:
            return StrategyResult(name=self.name, signal=Signal.wait())

        trend_base = candles[-self.trend_period - 1].close_price
        impulse_base = candles[-self.impulse_period - 1].close_price
        trend = (latest.close_price - trend_base) / trend_base
        impulse = (latest.close_price - impulse_base) / impulse_base

        if self.side in {"both", "long"} and trend >= self.min_trend and impulse >= self.min_impulse:
            return _directional_result(self.name, SignalDirection.LONG, Decimal("0.99"))
        if self.side in {"both", "short"} and trend <= -self.min_trend and impulse <= -self.min_impulse:
            return _directional_result(self.name, SignalDirection.SHORT, Decimal("0.99"))
        return StrategyResult(name=self.name, signal=Signal.wait())


@dataclass(frozen=True)
class SwingEnvelopeTakeProfitStopLossStrategy:
    name: str = "swing-envelope-take-profit-stop-loss"
    lookback: int = 180
    stop_buffer_ratio: Decimal = Decimal("0.001")
    reward_risk_ratio: Decimal = Decimal("0.35")
    min_stop_ratio: Decimal = Decimal("0.018")
    max_stop_ratio: Decimal = Decimal("0.12")

    def calculate(
        self,
        context: StrategyContext,
        direction: SignalDirection,
    ) -> TakeProfitStopLossLevels:
        candles = context.market.candles
        if len(candles) < self.lookback:
            raise ValueError("not enough candles for swing envelope levels")
        entry = context.market.latest_candle.close_price
        window = candles[-self.lookback:]
        if direction is SignalDirection.LONG:
            swing_stop = min(candle.low_price for candle in window) * (
                Decimal("1") - self.stop_buffer_ratio
            )
            stop_ratio = _clamp((entry - swing_stop) / entry, self.min_stop_ratio, self.max_stop_ratio)
            stop_loss = entry * (Decimal("1") - stop_ratio)
            take_profit = entry * (Decimal("1") + stop_ratio * self.reward_risk_ratio)
        else:
            swing_stop = max(candle.high_price for candle in window) * (
                Decimal("1") + self.stop_buffer_ratio
            )
            stop_ratio = _clamp((swing_stop - entry) / entry, self.min_stop_ratio, self.max_stop_ratio)
            stop_loss = entry * (Decimal("1") + stop_ratio)
            take_profit = entry * (Decimal("1") - stop_ratio * self.reward_risk_ratio)
        return TakeProfitStopLossLevels(
            strategy_name=self.name,
            entry_price=entry,
            take_profit=take_profit,
            stop_loss=stop_loss,
            metadata={"lookback": str(self.lookback), "reward_risk_ratio": str(self.reward_risk_ratio)},
        )


@dataclass(frozen=True)
class QualityVolatilitySizingStrategy:
    min_equity_ratio: Decimal = Decimal("0.03")
    max_equity_ratio: Decimal = Decimal("0.25")
    min_leverage: Decimal = Decimal("2")
    max_leverage: Decimal = Decimal("15")

    def decide(
        self,
        decision: TradeDecision,
        exposure_limit: ExposureLimit,
    ) -> PositionSizingDecision:
        quality = _clamp(decision.signal.confidence, Decimal("0"), Decimal("1"))
        convex_quality = quality * quality
        equity_ratio = self.min_equity_ratio + (
            self.max_equity_ratio - self.min_equity_ratio
        ) * convex_quality
        leverage = self.min_leverage + (
            self.max_leverage - self.min_leverage
        ) * convex_quality
        return PositionSizingDecision(
            equity_ratio=equity_ratio,
            leverage=min(leverage, Decimal("15")),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-path", type=Path, default=RESULTS_PATH)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--train-select-limit", type=int, default=25)
    parser.add_argument("--min-train-win-rate", type=Decimal, default=Decimal("0.80"))
    parser.add_argument("--min-train-average-gross-trade-return", type=Decimal, default=Decimal("0.006"))
    parser.add_argument("--min-train-trades", type=int, default=1)
    parser.add_argument("--fee-rate", type=Decimal, default=Decimal("0.0004"))
    args = parser.parse_args()

    configure_runtime_logging(level="ERROR")
    market = load_or_fetch_market()
    args.results_path.parent.mkdir(parents=True, exist_ok=True)
    candidates = build_novel_combos()
    if args.limit > 0:
        candidates = candidates[: args.limit]

    train_rows = []
    for combo in candidates:
        train_result = run_combo_for_period(
            market,
            combo,
            start_at=TRAIN_START,
            end_at=TRAIN_END,
            fee_rate=args.fee_rate,
        )
        train_rows.append(train_result)
        print("TRAIN " + json.dumps(train_result, ensure_ascii=False, sort_keys=True), flush=True)

    selected = rank_train_results(train_rows)[: args.train_select_limit]
    selected = filter_targets(
        selected,
        min_win_rate=args.min_train_win_rate,
        min_average_gross_trade_return=args.min_train_average_gross_trade_return,
        min_trades=args.min_train_trades,
    ) or rank_train_results(train_rows)[: args.train_select_limit]
    combo_by_id = {combo.combo_id: combo for combo in candidates}
    combined_rows = []
    for train_result in selected:
        combo = combo_by_id[str(train_result["combo_id"])]
        test_result = run_combo_for_period(
            market,
            combo,
            start_at=TEST_START,
            end_at=TEST_END,
            fee_rate=args.fee_rate,
        )
        combined = combine_result(train_result, test_result)
        append_result_to(args.results_path, combined)
        combined_rows.append(combined)
        print("TEST " + json.dumps(combined, ensure_ascii=False, sort_keys=True), flush=True)

    print(
        "TARGETS "
        + json.dumps(filter_targets(combined_rows), ensure_ascii=False, sort_keys=True),
        flush=True,
    )


def build_novel_combos() -> list[Combo]:
    combos: list[Combo] = []
    combos.extend(
        _build_combos(
            "novel-compression",
            VolatilityCompressionBreakoutStrategy,
            strategy_grid=[
                {"lookback": 120, "compression_period": 30, "compression_ratio": Decimal("0.40"), "breakout_buffer": Decimal("0.0004"), "min_volume_ratio": Decimal("0.90"), "direction_filter_period": 720, "min_filter_return": Decimal("0.001")},
                {"lookback": 180, "compression_period": 45, "compression_ratio": Decimal("0.45"), "breakout_buffer": Decimal("0.0006"), "min_volume_ratio": Decimal("1.00"), "direction_filter_period": 1440, "min_filter_return": Decimal("0.002")},
                {"lookback": 360, "compression_period": 60, "compression_ratio": Decimal("0.50"), "breakout_buffer": Decimal("0.0008"), "min_volume_ratio": Decimal("1.10"), "direction_filter_period": 2880, "min_filter_return": Decimal("0.004")},
            ],
        )
    )
    combos.extend(
        _build_combos(
            "novel-sweep",
            LiquiditySweepReclaimStrategy,
            strategy_grid=[
                {"sweep_period": 180, "reclaim_buffer": Decimal("0.0002"), "min_wick_ratio": Decimal("0.25"), "max_close_position_long": Decimal("0.35"), "min_close_position_short": Decimal("0.65"), "min_range_width": Decimal("0.004")},
                {"sweep_period": 360, "reclaim_buffer": Decimal("0.0004"), "min_wick_ratio": Decimal("0.30"), "max_close_position_long": Decimal("0.40"), "min_close_position_short": Decimal("0.60"), "min_range_width": Decimal("0.006")},
                {"sweep_period": 720, "reclaim_buffer": Decimal("0.0005"), "min_wick_ratio": Decimal("0.35"), "max_close_position_long": Decimal("0.45"), "min_close_position_short": Decimal("0.55"), "min_range_width": Decimal("0.010")},
            ],
        )
    )
    combos.extend(
        _build_combos(
            "novel-pullback",
            MultiWindowPullbackResumeStrategy,
            strategy_grid=[
                {"trend_period": 1440, "pullback_period": 120, "trigger_period": 8, "min_trend_return": Decimal("0.010"), "min_pullback": Decimal("0.003"), "resume_return": Decimal("0.0005")},
                {"trend_period": 2880, "pullback_period": 240, "trigger_period": 12, "min_trend_return": Decimal("0.018"), "min_pullback": Decimal("0.004"), "resume_return": Decimal("0.0008")},
                {"trend_period": 5760, "pullback_period": 480, "trigger_period": 20, "min_trend_return": Decimal("0.030"), "min_pullback": Decimal("0.006"), "resume_return": Decimal("0.0010")},
            ],
        )
    )
    combos.extend(build_timeboxed_finalist_combos())
    return unique_combos(combos)


def build_timeboxed_finalist_combos() -> list[Combo]:
    finalist_specs = [
        (
            "novel-timebox-t1440-i15-mt001-mi0002-h0-sl0012-rr07",
            {
                "trend_period": 1440,
                "impulse_period": 15,
                "min_trend": Decimal("0.01"),
                "min_impulse": Decimal("0.002"),
                "hour": 0,
                "side": "both",
            },
            Decimal("0.012"),
            Decimal("0.7"),
        ),
        (
            "novel-timebox-t1440-i30-mt001-mi0006-h0-sl0012-rr07",
            {
                "trend_period": 1440,
                "impulse_period": 30,
                "min_trend": Decimal("0.01"),
                "min_impulse": Decimal("0.006"),
                "hour": 0,
                "side": "both",
            },
            Decimal("0.012"),
            Decimal("0.7"),
        ),
    ]
    sizing_params = {
        "kind": "quality-volatility",
        "min_equity_ratio": Decimal("0.01"),
        "max_equity_ratio": Decimal("0.10"),
        "min_leverage": Decimal("1"),
        "max_leverage": Decimal("6"),
    }
    combos = []
    for combo_id, strategy_params, stop_loss_ratio, reward_risk_ratio in finalist_specs:
        tpsl_params = {
            "kind": "fixed-timebox",
            "stop_loss_ratio": stop_loss_ratio,
            "reward_risk_ratio": reward_risk_ratio,
        }
        combos.append(
            Combo(
                combo_id=combo_id,
                strategy_factory=TimeboxedTrendAccelerationStrategy,
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


def _build_combos(prefix: str, strategy_factory, *, strategy_grid: Iterable[Mapping[str, object]]) -> list[Combo]:
    tpsl_grid: list[tuple[str, Mapping[str, object]]] = [
        ("fixed-wide-low-rr", {"kind": "fixed", "stop_loss_ratio": Decimal("0.06"), "reward_risk_ratio": Decimal("0.12")}),
        ("fixed-wide-mid-rr", {"kind": "fixed", "stop_loss_ratio": Decimal("0.08"), "reward_risk_ratio": Decimal("0.10")}),
        ("fixed-verywide-low-rr", {"kind": "fixed", "stop_loss_ratio": Decimal("0.10"), "reward_risk_ratio": Decimal("0.08")}),
        ("swing-envelope-a", {"kind": "swing-envelope", "lookback": 180, "stop_buffer_ratio": Decimal("0.001"), "reward_risk_ratio": Decimal("0.18"), "min_stop_ratio": Decimal("0.035"), "max_stop_ratio": Decimal("0.12")}),
        ("swing-envelope-b", {"kind": "swing-envelope", "lookback": 360, "stop_buffer_ratio": Decimal("0.0015"), "reward_risk_ratio": Decimal("0.14"), "min_stop_ratio": Decimal("0.045"), "max_stop_ratio": Decimal("0.15")}),
    ]
    sizing_grid: list[Mapping[str, object]] = [
        {"kind": "quality-volatility", "min_equity_ratio": Decimal("0.02"), "max_equity_ratio": Decimal("0.18"), "min_leverage": Decimal("2"), "max_leverage": Decimal("12")},
        {"kind": "quality-volatility", "min_equity_ratio": Decimal("0.03"), "max_equity_ratio": Decimal("0.25"), "min_leverage": Decimal("3"), "max_leverage": Decimal("15")},
    ]
    combos = []
    for strategy_index, strategy_params in enumerate(strategy_grid, start=1):
        for tpsl_index, (tpsl_name, tpsl_params) in enumerate(tpsl_grid, start=1):
            for sizing_index, sizing_params in enumerate(sizing_grid, start=1):
                combos.append(
                    Combo(
                        combo_id=f"{prefix}-s{strategy_index}-t{tpsl_index}-{tpsl_name}-p{sizing_index}",
                        strategy_factory=strategy_factory,
                        strategy_params=dict(strategy_params),
                        tpsl_factory=lambda params=tpsl_params: make_tpsl(params),
                        tpsl_params=dict(tpsl_params),
                        position_sizing_factory=lambda params=sizing_params: QualityVolatilitySizingStrategy(
                            min_equity_ratio=params["min_equity_ratio"],
                            max_equity_ratio=params["max_equity_ratio"],
                            min_leverage=params["min_leverage"],
                            max_leverage=params["max_leverage"],
                        ),
                        position_sizing_params=dict(sizing_params),
                    )
                )
    return combos


def make_tpsl(params: Mapping[str, object]):
    if params["kind"] == "fixed":
        return FixedRatioTakeProfitStopLossStrategy(
            stop_loss_ratio=params["stop_loss_ratio"],
            reward_risk_ratio=params["reward_risk_ratio"],
        )
    if params["kind"] == "swing-envelope":
        return SwingEnvelopeTakeProfitStopLossStrategy(
            lookback=params["lookback"],
            stop_buffer_ratio=params["stop_buffer_ratio"],
            reward_risk_ratio=params["reward_risk_ratio"],
            min_stop_ratio=params["min_stop_ratio"],
            max_stop_ratio=params["max_stop_ratio"],
        )
    raise ValueError(f"unknown tpsl kind: {params['kind']}")


def load_or_fetch_market() -> MarketSnapshot:
    if CACHE_PATH.exists():
        return _read_cache(CACHE_PATH)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _acquire_cache_lock():
        while not CACHE_PATH.exists():
            time.sleep(5)
        return _read_cache(CACHE_PATH)
    try:
        if CACHE_PATH.exists():
            return _read_cache(CACHE_PATH)
        candles = load_public_kline_archives(start_at=TRAIN_START, end_at=FETCH_END)
        temp_path = CACHE_PATH.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            for candle in candles:
                handle.write(json.dumps(candle_record(candle), sort_keys=True) + "\n")
        temp_path.replace(CACHE_PATH)
        return MarketSnapshot(tuple(candles))
    finally:
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


def load_public_kline_archives(*, start_at: datetime, end_at: datetime):
    candles = []
    for year, month in _months_between(start_at, end_at):
        candles.extend(_download_archive_candles(_monthly_url(year, month)))
    for day in _days_between(datetime(2026, 7, 1, tzinfo=timezone.utc), end_at):
        candles.extend(_download_archive_candles(_daily_url(day)))
    selected = [
        candle
        for candle in candles
        if start_at <= candle.opened_at < end_at
    ]
    selected.sort(key=lambda candle: candle.opened_at)
    unique = {}
    for candle in selected:
        unique[candle.opened_at] = candle
    return tuple(unique.values())


def _download_archive_candles(url: str):
    try:
        with urlopen(url, timeout=60) as response:
            payload = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return ()
        raise
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as raw:
            text = TextIOWrapper(raw, encoding="utf-8")
            return tuple(_candle_from_csv_row(row) for row in text if row.strip() and not row.startswith("open_time"))


def _candle_from_csv_row(row: str):
    from src.domain.market import Candle

    values = row.strip().split(",")
    opened_at = datetime.fromtimestamp(int(values[0]) / 1000, tz=timezone.utc)
    return Candle(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=1),
        open_price=Decimal(values[1]),
        high_price=Decimal(values[2]),
        low_price=Decimal(values[3]),
        close_price=Decimal(values[4]),
        volume=Decimal(values[5]),
    )


def _monthly_url(year: int, month: int) -> str:
    return (
        "https://data.binance.vision/data/futures/um/monthly/klines/"
        f"BTCUSDT/1m/BTCUSDT-1m-{year}-{month:02d}.zip"
    )


def _daily_url(day: datetime) -> str:
    return (
        "https://data.binance.vision/data/futures/um/daily/klines/"
        f"BTCUSDT/1m/BTCUSDT-1m-{day:%Y-%m-%d}.zip"
    )


def _months_between(start_at: datetime, end_at: datetime):
    cursor = datetime(start_at.year, start_at.month, 1, tzinfo=timezone.utc)
    end_month = datetime(end_at.year, end_at.month, 1, tzinfo=timezone.utc)
    while cursor <= end_month:
        yield cursor.year, cursor.month
        if cursor.month == 12:
            cursor = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)


def _days_between(start_at: datetime, end_at: datetime):
    cursor = start_at
    while cursor < end_at:
        yield cursor
        cursor += timedelta(days=1)


def run_combo_for_period(
    market: MarketSnapshot,
    combo: Combo,
    *,
    start_at: datetime,
    end_at: datetime,
    fee_rate: Decimal,
) -> dict[str, object]:
    spec = StrategySpec(
        strategy_id=combo.combo_id,
        name=combo.combo_id,
        implementation=f"scripts.novel_train_test_combo_search.{combo.strategy_factory.__name__}",
        version="novel-search",
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        lookback_candle_limit=_candle_limit_for_combo(combo),
        parameters=combo.strategy_params,
        metadata={"family": "novel_train_test_search"},
    )
    result = _simulate_fast(
        market=market,
        spec=spec,
        combo=combo,
        start_at=start_at,
        end_at=end_at,
        fee_rate=fee_rate,
    )
    performance = result["performance"]
    trades = result["trades"]
    gross_metrics = gross_trade_metrics(trades)
    return {
        "combo_id": combo.combo_id,
        "trade_count": performance.trade_count if performance else 0,
        "win_rate": str(performance.win_rate if performance else Decimal("0")),
        "return_ratio": str(performance.return_ratio if performance else Decimal("0")),
        "net_pnl": str(performance.net_pnl if performance else Decimal("0")),
        "max_drawdown_ratio": str(performance.max_drawdown_ratio if performance else Decimal("0")),
        "average_net_trade_return": str(_average_net_trade_return(trades)),
        "gross_win_rate": str(gross_metrics["gross_win_rate"]),
        "average_gross_trade_return": str(gross_metrics["average_gross_trade_return"]),
        "gross_pnl": str(gross_metrics["gross_pnl"]),
        "fee_paid": str(gross_metrics["fee_paid"]),
        "strategy_params": stringify_mapping(combo.strategy_params),
        "tpsl_params": stringify_mapping(combo.tpsl_params),
        "position_sizing_params": stringify_mapping(combo.position_sizing_params),
    }


def _simulate_fast(
    *,
    market: MarketSnapshot,
    spec: StrategySpec,
    combo: Combo,
    start_at: datetime,
    end_at: datetime,
    fee_rate: Decimal,
) -> dict[str, object]:
    candles = tuple(candle for candle in market.candles if start_at <= candle.opened_at < end_at)
    strategy = StaticStrategyCatalog(entries=((spec, combo.strategy_factory),)).create_strategy(spec)
    tpsl = combo.tpsl_factory()
    sizing = combo.position_sizing_factory()
    equity = Decimal("10000")
    initial_equity = equity
    peak_equity = equity
    max_drawdown_ratio = Decimal("0")
    trades: list[BacktestTrade] = []
    position: _OpenPosition | None = None

    for index, candle in enumerate(candles):
        exited_this_candle = False
        if position is not None and index > 0:
            exit_price, exit_reason = _exit_for_candle(position, candle)
            if exit_price is not None:
                trade = _close_trade(
                    position=position,
                    candle=candle,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    fee_rate=fee_rate,
                    slippage_rate=Decimal("0"),
                )
                trades.append(trade)
                equity += trade.net_pnl
                peak_equity = max(peak_equity, equity)
                max_drawdown_ratio = max(max_drawdown_ratio, _drawdown_ratio(equity, peak_equity))
                position = None
                exited_this_candle = True
            else:
                context = _context_for(candles, index, spec.lookback_candle_limit)
                result = strategy.evaluate(context)
                if _is_opposite_signal(position.direction, result.signal.direction):
                    trade = _close_trade(
                        position=position,
                        candle=candle,
                        exit_price=candle.close_price,
                        exit_reason="opposite_signal",
                        fee_rate=fee_rate,
                        slippage_rate=Decimal("0"),
                    )
                    trades.append(trade)
                    equity += trade.net_pnl
                    peak_equity = max(peak_equity, equity)
                    max_drawdown_ratio = max(max_drawdown_ratio, _drawdown_ratio(equity, peak_equity))
                    position = None
                    exited_this_candle = True

        if position is not None or exited_this_candle:
            continue

        context = _context_for(candles, index, spec.lookback_candle_limit)
        result = strategy.evaluate(context)
        if result.signal.direction is SignalDirection.WAIT:
            continue

        entry_price = _entry_price(
            candle.close_price,
            direction=result.signal.direction,
            slippage_rate=Decimal("0"),
        )
        sizing_decision = sizing.decide(
            decision=TradeDecision(
                action=_entry_action(result.signal.direction),
                signal=result.signal,
            ),
            exposure_limit=_backtest_exposure_limit(equity),
        )
        notional = equity * sizing_decision.equity_ratio * sizing_decision.leverage
        levels = tpsl.calculate(context, result.signal.direction)
        position = _OpenPosition(
            direction=result.signal.direction,
            entry_price=entry_price,
            quantity=notional / entry_price,
            entry_time=candle.closed_at,
            levels=levels,
        )

    if position is not None:
        final_candle = candles[-1]
        trade = _close_trade(
            position=position,
            candle=final_candle,
            exit_price=final_candle.close_price,
            exit_reason="end_of_data",
            fee_rate=fee_rate,
            slippage_rate=Decimal("0"),
        )
        trades.append(trade)
        equity += trade.net_pnl
        peak_equity = max(peak_equity, equity)
        max_drawdown_ratio = max(max_drawdown_ratio, _drawdown_ratio(equity, peak_equity))

    return {
        "trades": tuple(trades),
        "performance": _performance(
            initial_equity=initial_equity,
            final_equity=equity,
            trades=tuple(trades),
            max_drawdown_ratio=max_drawdown_ratio,
        ),
    }


def _context_for(candles, index: int, candle_limit: int) -> StrategyContext:
    start = max(0, index + 1 - candle_limit)
    market = _FastMarketView(candles, start, index + 1)
    return StrategyContext(
        market=market,
        indicators=IndicatorSet(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            measured_at=candles[index].closed_at,
            values=(),
        ),
        metadata={},
    )


class _FastMarketView:
    def __init__(self, candles, start: int, end: int) -> None:
        self.candles = _CandleWindow(candles, start, end)

    @property
    def symbol(self):
        return SYMBOL

    @property
    def timeframe(self):
        return TIMEFRAME

    @property
    def latest_candle(self):
        return self.candles[-1]


class _CandleWindow:
    def __init__(self, candles, start: int, end: int) -> None:
        self._candles = candles
        self._start = start
        self._end = end

    def __len__(self) -> int:
        return self._end - self._start

    def __getitem__(self, item):
        length = len(self)
        if isinstance(item, slice):
            start, stop, step = item.indices(length)
            return tuple(self._candles[self._start + index] for index in range(start, stop, step))
        index = item + length if item < 0 else item
        if index < 0 or index >= length:
            raise IndexError(item)
        return self._candles[self._start + index]


def gross_trade_metrics(trades: Sequence[BacktestTrade]) -> dict[str, Decimal]:
    if not trades:
        return {
            "gross_win_rate": Decimal("0"),
            "average_gross_trade_return": Decimal("0"),
            "gross_pnl": Decimal("0"),
            "fee_paid": Decimal("0"),
        }
    returns = []
    wins = 0
    gross_pnl = Decimal("0")
    fee_paid = Decimal("0")
    for trade in trades:
        notional = trade.entry_price * trade.quantity
        gross_pnl += trade.gross_pnl
        fee_paid += trade.fee_paid
        if trade.gross_pnl > Decimal("0"):
            wins += 1
        if notional > Decimal("0"):
            returns.append(trade.gross_pnl / notional)
    return {
        "gross_win_rate": Decimal(wins) / Decimal(len(trades)),
        "average_gross_trade_return": sum(returns, Decimal("0")) / Decimal(len(returns)) if returns else Decimal("0"),
        "gross_pnl": gross_pnl,
        "fee_paid": fee_paid,
    }


def combine_result(train_result: Mapping[str, object], test_result: Mapping[str, object]) -> dict[str, object]:
    return {
        "combo_id": train_result["combo_id"],
        "train_period": {"start_at": TRAIN_START.isoformat(), "end_at": TRAIN_END.isoformat()},
        "test_period": {"start_at": TEST_START.isoformat(), "end_at": TEST_END.isoformat()},
        "strategy_params": train_result["strategy_params"],
        "tpsl_params": train_result["tpsl_params"],
        "position_sizing_params": train_result["position_sizing_params"],
        **_prefix_result("train", train_result),
        **_prefix_result("test", test_result),
    }


def filter_targets(
    results: Sequence[Mapping[str, object]],
    *,
    min_win_rate: Decimal = Decimal("0.80"),
    min_average_gross_trade_return: Decimal = Decimal("0.006"),
    min_trades: int = 1,
) -> list[Mapping[str, object]]:
    filtered = [
        result
        for result in results
        if Decimal(str(_metric(result, "win_rate"))) >= min_win_rate
        and Decimal(str(_metric(result, "average_gross_trade_return"))) >= min_average_gross_trade_return
        and int(_metric(result, "trade_count")) >= min_trades
    ]
    return sorted(
        filtered,
        key=lambda result: (
            Decimal(str(result.get("test_return_ratio", "0"))),
            Decimal(str(result.get("test_win_rate", "0"))),
            Decimal(str(result.get("test_average_gross_trade_return", "0"))),
        ),
        reverse=True,
    )


def _metric(result: Mapping[str, object], key: str) -> object:
    train_key = f"train_{key}"
    if train_key in result:
        return result[train_key]
    return result[key]


def rank_train_results(results: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return sorted(
        results,
        key=lambda result: (
            Decimal(str(result["win_rate"])) >= Decimal("0.80"),
            Decimal(str(result["average_gross_trade_return"])) >= Decimal("0.006"),
            Decimal(str(result["return_ratio"])),
            Decimal(str(result["average_gross_trade_return"])),
            Decimal(str(result["win_rate"])),
        ),
        reverse=True,
    )


def _prefix_result(prefix: str, result: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "trade_count",
        "win_rate",
        "return_ratio",
        "net_pnl",
        "max_drawdown_ratio",
        "average_net_trade_return",
        "gross_win_rate",
        "average_gross_trade_return",
        "gross_pnl",
        "fee_paid",
    )
    return {f"{prefix}_{key}": result[key] for key in keys}


def _candle_limit_for_combo(combo: Combo) -> int:
    values = [
        int(combo.strategy_params.get("lookback", 0)),
        int(combo.strategy_params.get("compression_period", 0)),
        int(combo.strategy_params.get("direction_filter_period", 0)),
        int(combo.strategy_params.get("sweep_period", 0)),
        int(combo.strategy_params.get("trend_period", 0)),
        int(combo.strategy_params.get("pullback_period", 0)),
        int(combo.strategy_params.get("trigger_period", 0)),
        int(combo.tpsl_params.get("lookback", 0)),
    ]
    return max(values) + 3


def _directional_result(name: str, direction: SignalDirection, confidence: Decimal) -> StrategyResult:
    return StrategyResult(
        name=name,
        signal=Signal(direction=direction, confidence=confidence),
    )


def _read_cache(path: Path) -> MarketSnapshot:
    return MarketSnapshot(
        tuple(candle_from_record(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    )


def _acquire_cache_lock() -> bool:
    try:
        descriptor = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    return True


def _average(values: Iterable[Decimal]) -> Decimal:
    values = tuple(values)
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _range_ratio(candles) -> Decimal:
    low = min(candle.low_price for candle in candles)
    high = max(candle.high_price for candle in candles)
    return _range_ratio_from_bounds(low, high)


def _range_ratio_from_bounds(low: Decimal, high: Decimal) -> Decimal:
    if low <= Decimal("0"):
        return Decimal("0")
    return (high - low) / low


class RollingRange:
    def __init__(self, period: int) -> None:
        self._period = period
        self._index = 0
        self._last_opened_at = None
        self._highs = deque()
        self._lows = deque()

    def range(self, candles) -> tuple[Decimal | None, Decimal | None]:
        latest = candles[-1]
        if self._last_opened_at == latest.opened_at:
            return self._current_range()
        if self._last_opened_at is not None and latest.opened_at < self._last_opened_at:
            self.__init__(self._period)
        self._append(candles[-2])
        self._last_opened_at = latest.opened_at
        return self._current_range()

    def _append(self, candle) -> None:
        index = self._index
        self._index += 1
        while self._highs and self._highs[-1][1] <= candle.high_price:
            self._highs.pop()
        self._highs.append((index, candle.high_price))
        while self._lows and self._lows[-1][1] >= candle.low_price:
            self._lows.pop()
        self._lows.append((index, candle.low_price))
        earliest = self._index - self._period
        while self._highs and self._highs[0][0] < earliest:
            self._highs.popleft()
        while self._lows and self._lows[0][0] < earliest:
            self._lows.popleft()

    def _current_range(self) -> tuple[Decimal | None, Decimal | None]:
        if self._index < self._period or not self._highs or not self._lows:
            return None, None
        return self._lows[0][1], self._highs[0][1]


class RollingAverage:
    def __init__(self, period: int) -> None:
        self._period = period
        self._values = deque()
        self._total = Decimal("0")
        self._last_opened_at = None

    def average(self, candle) -> Decimal:
        if self._last_opened_at == candle.opened_at:
            return self._current_average()
        self._last_opened_at = candle.opened_at
        self._values.append(candle.volume)
        self._total += candle.volume
        while len(self._values) > self._period:
            self._total -= self._values.popleft()
        return self._current_average()

    def _current_average(self) -> Decimal:
        if len(self._values) < self._period:
            return Decimal("0")
        return self._total / Decimal(len(self._values))


def _clamp(value: Decimal, minimum: Decimal, maximum: Decimal) -> Decimal:
    return max(minimum, min(value, maximum))


def _average_net_trade_return(trades: Sequence[BacktestTrade]) -> Decimal:
    returns = []
    for trade in trades:
        notional = trade.entry_price * trade.quantity
        if notional > Decimal("0"):
            returns.append(trade.net_pnl / notional)
    return sum(returns, Decimal("0")) / Decimal(len(returns)) if returns else Decimal("0")


def append_result_to(path: Path, result: Mapping[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")


def unique_combos(combos: Iterable[Combo]) -> list[Combo]:
    seen = set()
    unique = []
    for combo in combos:
        if combo.combo_id in seen:
            continue
        seen.add(combo.combo_id)
        unique.append(combo)
    return unique


def stringify_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {key: str(value) for key, value in values.items()}


if __name__ == "__main__":
    main()
