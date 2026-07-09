from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.usecases.strategy_lifecycle import (
    RunStrategyBacktestCycleCommand,
    RunStrategyBacktestCycleUseCase,
)
from src.domain.indicator import IndicatorSet
from src.domain.lifecycle import SignalGeneratorDefinition, StrategyDefinition, StrategyEvaluation
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.ports import MarketDataPort
from src.domain.risk import FixedPositionSizingStrategy
from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import StaticStrategyCatalog, StrategyContext, StrategySpec
from src.domain.strategy.strategy_result import StrategyResult
from src.domain.strategy.implementations import ChartPatternStrategy
from src.domain.strategy.implementations.atr_take_profit_stop_loss import (
    AtrTakeProfitStopLossStrategy,
)
from src.domain.strategy.take_profit_stop_loss import TakeProfitStopLossLevels
from src.infrastructure.exchange.binance.market_data import BinanceMarketDataAdapter
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.observability.logging import configure_runtime_logging


START_AT = datetime(2026, 1, 9, 0, 0, tzinfo=timezone.utc)
END_AT = datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)
SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")
CACHE_PATH = Path(".agents/backtest-cache/btcusdt-1m-20260109-20260709.jsonl")
LOCK_PATH = Path(".agents/backtest-cache/btcusdt-1m-20260109-20260709.lock")
RESULTS_PATH = Path("docs/backtests/chart-pattern-combo-search.jsonl")


@dataclass(frozen=True)
class Combo:
    combo_id: str
    strategy_factory: Callable[..., object]
    strategy_params: Mapping[str, object]
    tpsl_factory: Callable[[], object]
    tpsl_params: Mapping[str, object]
    position_sizing_factory: Callable[[], object] = lambda: FixedPositionSizingStrategy(
        equity_ratio=Decimal("0.01"),
        leverage=Decimal("1"),
    )
    position_sizing_params: Mapping[str, object] = None

    def __post_init__(self) -> None:
        if self.position_sizing_params is None:
            object.__setattr__(
                self,
                "position_sizing_params",
                {
                    "kind": "fixed",
                    "equity_ratio": Decimal("0.01"),
                    "leverage": Decimal("1"),
                },
            )


class CachedMarketData(MarketDataPort):
    def __init__(self, market: MarketSnapshot) -> None:
        self._market = market

    def load_candles(self, symbol, timeframe, limit):
        return self._market.candles[-limit:]

    def load_snapshot(self, symbol, timeframe, limit):
        return MarketSnapshot(self.load_candles(symbol, timeframe, limit))

    def load_candles_between(self, symbol, timeframe, start_at, end_at):
        return tuple(
            candle
            for candle in self._market.candles
            if start_at <= candle.opened_at < end_at
        )


class InMemoryStrategyRepository:
    def __init__(self) -> None:
        self.strategy_definitions: dict[str, StrategyDefinition] = {}
        self.signal_generator_definitions: dict[str, SignalGeneratorDefinition] = {}
        self.evaluations: list[StrategyEvaluation] = []

    def save_strategy_definition(self, definition: StrategyDefinition) -> None:
        self.strategy_definitions[definition.strategy_id] = definition

    def load_strategy_definition(self, strategy_id: str):
        return self.strategy_definitions.get(strategy_id)

    def save_signal_generator_definition(
        self,
        definition: SignalGeneratorDefinition,
    ) -> None:
        self.signal_generator_definitions[definition.generator_id] = definition

    def load_signal_generator_definition(self, generator_id: str):
        return self.signal_generator_definitions.get(generator_id)

    def save_strategy_evaluation(self, evaluation: StrategyEvaluation) -> None:
        self.evaluations.append(evaluation)

    def list_strategy_evaluations(self, target_id: str):
        return tuple(
            evaluation
            for evaluation in self.evaluations
            if evaluation.target_id == target_id
        )


@dataclass(frozen=True)
class FixedRatioTakeProfitStopLossStrategy:
    name: str = "fixed-ratio-take-profit-stop-loss"
    stop_loss_ratio: Decimal = Decimal("0.003")
    reward_risk_ratio: Decimal = Decimal("2")

    def calculate(
        self,
        context: StrategyContext,
        direction: SignalDirection,
    ) -> TakeProfitStopLossLevels:
        entry = context.market.latest_candle.close_price
        risk = entry * self.stop_loss_ratio
        if direction is SignalDirection.LONG:
            stop_loss = entry - risk
            take_profit = entry + risk * self.reward_risk_ratio
        else:
            stop_loss = entry + risk
            take_profit = entry - risk * self.reward_risk_ratio
        return TakeProfitStopLossLevels(
            strategy_name=self.name,
            entry_price=entry,
            take_profit=take_profit,
            stop_loss=stop_loss,
            metadata={
                "stop_loss_ratio": str(self.stop_loss_ratio),
                "reward_risk_ratio": str(self.reward_risk_ratio),
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preset",
        choices=(
            "baseline",
            "loose",
            "strict",
            "scalp",
            "momentum",
            "selective",
            "swing",
            "reversal",
            "all",
        ),
        default="all",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-win-rate", type=Decimal, default=Decimal("0.60"))
    parser.add_argument("--min-average-trade-return", type=Decimal, default=Decimal("0.005"))
    parser.add_argument("--min-trade-count", type=int, default=100)
    args = parser.parse_args()

    configure_runtime_logging(level="ERROR")
    market = load_or_fetch_market()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen = load_seen_combo_ids()

    candidates = [
        combo
        for combo in combos_for_preset(args.preset)
        if combo.combo_id not in seen
    ]
    if args.limit > 0:
        candidates = candidates[: args.limit]

    for combo in candidates:
        result = run_combo(market, combo)
        append_result(result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if target_met(
            result,
            min_win_rate=args.min_win_rate,
            min_average_trade_return=args.min_average_trade_return,
            min_trade_count=args.min_trade_count,
        ):
            print(f"TARGET_FOUND {combo.combo_id}")
            break


def load_or_fetch_market() -> MarketSnapshot:
    if CACHE_PATH.exists():
        return MarketSnapshot(tuple(candle_from_record(json.loads(line)) for line in CACHE_PATH.read_text().splitlines() if line.strip()))
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _acquire_cache_lock():
        while not CACHE_PATH.exists():
            time.sleep(5)
        return MarketSnapshot(tuple(candle_from_record(json.loads(line)) for line in CACHE_PATH.read_text().splitlines() if line.strip()))
    try:
        if CACHE_PATH.exists():
            return MarketSnapshot(tuple(candle_from_record(json.loads(line)) for line in CACHE_PATH.read_text().splitlines() if line.strip()))
        config = BinanceConfig.default()
        config = BinanceConfig(
            api_key=config.api_key,
            api_secret=config.api_secret,
            base_url=config.base_url,
            timeout=config.timeout,
            recv_window=config.recv_window,
            retry_attempts=5,
            retry_delay=60,
        )
        candles = BinanceMarketDataAdapter(config).load_candles_between(
            symbol=SYMBOL,
            timeframe=TIMEFRAME,
            start_at=START_AT,
            end_at=END_AT,
        )
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


def _acquire_cache_lock() -> bool:
    try:
        descriptor = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    return True


def run_combo(market: MarketSnapshot, combo: Combo) -> dict[str, object]:
    return run_combo_for_period(
        market,
        combo,
        start_at=START_AT,
        end_at=END_AT,
        cycle_id="combo-search-6m",
        metadata={"combo_id": combo.combo_id},
    )


def run_combo_for_period(
    market: MarketSnapshot,
    combo: Combo,
    *,
    start_at: datetime,
    end_at: datetime,
    cycle_id: str,
    metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    repository = InMemoryStrategyRepository()
    catalog = StaticStrategyCatalog(
        entries=(
            (
                StrategySpec(
                    strategy_id=combo.combo_id,
                    name=combo.combo_id,
                    implementation=f"scripts.backtest_combo_search.{combo.strategy_factory.__name__}",
                    version="search",
                    symbol=SYMBOL,
                    timeframe=TIMEFRAME,
                    lookback_candle_limit=_candle_limit_for_combo(combo),
                    parameters=combo.strategy_params,
                    metadata={"family": "chart_pattern_search"},
                ),
                combo.strategy_factory,
            ),
        )
    )
    usecase = RunStrategyBacktestCycleUseCase(
        strategy_repository=repository,
        market_data=CachedMarketData(market),
        strategy_catalog=catalog,
        take_profit_stop_loss_strategy=combo.tpsl_factory(),
        position_sizing_strategy=combo.position_sizing_factory(),
        indicator_factory=empty_indicators,
    )
    result = usecase.execute(
        RunStrategyBacktestCycleCommand(
            cycle_id=cycle_id,
            enabled_strategy_ids=(combo.combo_id,),
            start_at=start_at,
            end_at=end_at,
            metadata=metadata or {"combo_id": combo.combo_id},
        )
    )
    evaluation = repository.evaluations[0] if repository.evaluations else None
    metrics = dict(evaluation.metrics) if evaluation is not None else {}
    trade_count = int(metrics.get("trade_count", Decimal("0")))
    average_trade_return = Decimal(str(metrics.get("average_trade_return", Decimal("0"))))
    return {
        "combo_id": combo.combo_id,
        "succeeded": result.succeeded_count == 1,
        "error": None if result.succeeded_count == 1 else result.items[0].error_message,
        "trade_count": trade_count,
        "win_rate": str(metrics.get("win_rate", Decimal("0"))),
        "return_ratio": str(metrics.get("return_ratio", Decimal("0"))),
        "average_trade_return": str(average_trade_return),
        "net_pnl": str(metrics.get("net_pnl", Decimal("0"))),
        "max_drawdown_ratio": str(metrics.get("max_drawdown_ratio", Decimal("0"))),
        "strategy_params": stringify_mapping(combo.strategy_params),
        "tpsl_params": stringify_mapping(combo.tpsl_params),
        "position_sizing_params": stringify_mapping(combo.position_sizing_params),
    }


def target_met(
    result: Mapping[str, object],
    *,
    min_win_rate: Decimal,
    min_average_trade_return: Decimal,
    min_trade_count: int,
) -> bool:
    return (
        int(result["trade_count"]) >= min_trade_count
        and Decimal(str(result["win_rate"])) >= min_win_rate
        and Decimal(str(result["average_trade_return"])) >= min_average_trade_return
    )


def _candle_limit_for_combo(combo: Combo) -> int:
    values = [
        int(combo.strategy_params.get("lookback", 120)),
        int(combo.strategy_params.get("trend_period", 0)),
        int(combo.strategy_params.get("momentum_period", 0)),
        int(combo.strategy_params.get("move_period", 0)),
        int(combo.strategy_params.get("reclaim_period", 0)),
        int(combo.strategy_params.get("range_period", 0)),
        int(combo.strategy_params.get("pullback_period", 0)),
        int(combo.tpsl_params.get("atr_period", 0)),
    ]
    return max(values) + 2


def empty_indicators(spec: StrategySpec, snapshot: MarketSnapshot) -> IndicatorSet:
    return IndicatorSet(
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        measured_at=snapshot.latest_candle.closed_at,
        values=(),
    )


def combos_for_preset(preset: str) -> list[Combo]:
    groups = {
        "baseline": baseline_combos(),
        "loose": loose_combos(),
        "strict": strict_combos(),
        "scalp": scalp_combos(),
        "momentum": momentum_combos(),
        "selective": selective_combos(),
        "swing": swing_combos(),
        "reversal": reversal_combos(),
    }
    if preset == "all":
        result: list[Combo] = []
        for values in groups.values():
            result.extend(values)
        return result
    return groups[preset]


def baseline_combos() -> list[Combo]:
    return build_combos(
        "baseline",
        strategy_grid=[
            {"lookback": 120, "pivot_window": 3, "price_tolerance": Decimal("0.01"), "breakout_buffer": Decimal("0.003"), "volume_multiplier": Decimal("1.3"), "min_confidence": Decimal("0.6")},
            {"lookback": 180, "pivot_window": 3, "price_tolerance": Decimal("0.012"), "breakout_buffer": Decimal("0.0025"), "volume_multiplier": Decimal("1.2"), "min_confidence": Decimal("0.65")},
        ],
        tpsl_grid=[
            ("atr", {"atr_period": 14, "atr_multiplier": Decimal("1.5"), "reward_risk_ratio": Decimal("2")}),
            ("atr", {"atr_period": 10, "atr_multiplier": Decimal("1.2"), "reward_risk_ratio": Decimal("1.5")}),
        ],
    )


def loose_combos() -> list[Combo]:
    return build_combos(
        "loose",
        strategy_grid=[
            {"lookback": 90, "pivot_window": 2, "price_tolerance": Decimal("0.015"), "breakout_buffer": Decimal("0.0015"), "volume_multiplier": Decimal("1.0"), "min_confidence": Decimal("0.55")},
            {"lookback": 120, "pivot_window": 2, "price_tolerance": Decimal("0.02"), "breakout_buffer": Decimal("0.002"), "volume_multiplier": Decimal("1.1"), "min_confidence": Decimal("0.55")},
            {"lookback": 180, "pivot_window": 2, "price_tolerance": Decimal("0.018"), "breakout_buffer": Decimal("0.001"), "volume_multiplier": Decimal("0.9"), "min_confidence": Decimal("0.5")},
        ],
        tpsl_grid=[
            ("fixed", {"stop_loss_ratio": Decimal("0.0025"), "reward_risk_ratio": Decimal("2")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.0035"), "reward_risk_ratio": Decimal("1.5")}),
            ("atr", {"atr_period": 7, "atr_multiplier": Decimal("1.0"), "reward_risk_ratio": Decimal("2")}),
        ],
    )


def strict_combos() -> list[Combo]:
    return build_combos(
        "strict",
        strategy_grid=[
            {"lookback": 120, "pivot_window": 4, "price_tolerance": Decimal("0.008"), "breakout_buffer": Decimal("0.003"), "volume_multiplier": Decimal("1.4"), "min_confidence": Decimal("0.7")},
            {"lookback": 240, "pivot_window": 4, "price_tolerance": Decimal("0.01"), "breakout_buffer": Decimal("0.004"), "volume_multiplier": Decimal("1.5"), "min_confidence": Decimal("0.75")},
        ],
        tpsl_grid=[
            ("fixed", {"stop_loss_ratio": Decimal("0.004"), "reward_risk_ratio": Decimal("2.5")}),
            ("atr", {"atr_period": 14, "atr_multiplier": Decimal("2"), "reward_risk_ratio": Decimal("2")}),
        ],
    )


def scalp_combos() -> list[Combo]:
    return build_combos(
        "scalp",
        strategy_grid=[
            {"lookback": 60, "pivot_window": 1, "price_tolerance": Decimal("0.012"), "breakout_buffer": Decimal("0.001"), "volume_multiplier": Decimal("0.8"), "min_confidence": Decimal("0.5")},
            {"lookback": 90, "pivot_window": 1, "price_tolerance": Decimal("0.015"), "breakout_buffer": Decimal("0.001"), "volume_multiplier": Decimal("0.9"), "min_confidence": Decimal("0.55")},
        ],
        tpsl_grid=[
            ("fixed", {"stop_loss_ratio": Decimal("0.0015"), "reward_risk_ratio": Decimal("1.5")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.002"), "reward_risk_ratio": Decimal("2")}),
            ("atr", {"atr_period": 5, "atr_multiplier": Decimal("0.8"), "reward_risk_ratio": Decimal("1.5")}),
        ],
    )


@dataclass(frozen=True)
class BreakoutMomentumStrategy:
    name: str = "breakout-momentum"
    lookback: int = 60
    breakout_buffer: Decimal = Decimal("0.001")
    momentum_period: int = 10
    min_momentum: Decimal = Decimal("0.001")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.lookback, self.momentum_period) + 1
        if len(candles) < required:
            return StrategyResult(name=self.name, signal=Signal.wait())
        recent = candles[-self.lookback - 1 : -1]
        latest = candles[-1]
        resistance = max(candle.high_price for candle in recent)
        support = min(candle.low_price for candle in recent)
        past_close = candles[-self.momentum_period - 1].close_price
        momentum = (latest.close_price - past_close) / past_close
        if (
            latest.close_price > resistance * (Decimal("1") + self.breakout_buffer)
            and momentum >= self.min_momentum
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(
                    direction=SignalDirection.LONG,
                    confidence=Decimal("0.8"),
                ),
            )
        if (
            latest.close_price < support * (Decimal("1") - self.breakout_buffer)
            and momentum <= -self.min_momentum
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(
                    direction=SignalDirection.SHORT,
                    confidence=Decimal("0.8"),
                ),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())


@dataclass(frozen=True)
class SelectiveTrendBreakoutStrategy:
    name: str = "selective-trend-breakout"
    lookback: int = 720
    breakout_buffer: Decimal = Decimal("0.002")
    trend_period: int = 1440
    min_trend_return: Decimal = Decimal("0.01")
    cooldown_bars: int = 240

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.lookback, self.trend_period) + 1
        if len(candles) < required:
            return StrategyResult(name=self.name, signal=Signal.wait())
        if not self._cooldown_allows_signal(candles):
            return StrategyResult(name=self.name, signal=Signal.wait())
        recent = candles[-self.lookback - 1 : -1]
        latest = candles[-1]
        resistance = max(candle.high_price for candle in recent)
        support = min(candle.low_price for candle in recent)
        trend_base = candles[-self.trend_period - 1].close_price
        trend_return = (latest.close_price - trend_base) / trend_base
        if (
            trend_return >= self.min_trend_return
            and latest.close_price > resistance * (Decimal("1") + self.breakout_buffer)
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
            )
        if (
            trend_return <= -self.min_trend_return
            and latest.close_price < support * (Decimal("1") - self.breakout_buffer)
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())

    def _cooldown_allows_signal(self, candles: tuple[Candle, ...]) -> bool:
        if len(candles) < self.cooldown_bars + 1:
            return True
        latest = candles[-1]
        previous = candles[-self.cooldown_bars - 1]
        return latest.opened_at > previous.opened_at


@dataclass(frozen=True)
class SwingRetestStrategy:
    name: str = "swing-retest"
    trend_period: int = 4320
    pullback_period: int = 720
    min_trend_return: Decimal = Decimal("0.03")
    pullback_ratio: Decimal = Decimal("0.01")
    reclaim_ratio: Decimal = Decimal("0.003")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.trend_period, self.pullback_period) + 2
        if len(candles) < required:
            return StrategyResult(name=self.name, signal=Signal.wait())
        latest = candles[-1]
        previous = candles[-2]
        trend_base = candles[-self.trend_period - 1].close_price
        trend_return = (latest.close_price - trend_base) / trend_base
        pullback_window = candles[-self.pullback_period - 1 : -1]
        recent_high = max(candle.high_price for candle in pullback_window)
        recent_low = min(candle.low_price for candle in pullback_window)
        if trend_return >= self.min_trend_return:
            pulled_back = recent_high > Decimal("0") and (
                (recent_high - previous.close_price) / recent_high >= self.pullback_ratio
            )
            reclaimed = latest.close_price >= previous.close_price * (
                Decimal("1") + self.reclaim_ratio
            )
            if pulled_back and reclaimed:
                return StrategyResult(
                    name=self.name,
                    signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
                )
        if trend_return <= -self.min_trend_return:
            pulled_back = previous.close_price > Decimal("0") and (
                (previous.close_price - recent_low) / previous.close_price >= self.pullback_ratio
            )
            reclaimed = latest.close_price <= previous.close_price * (
                Decimal("1") - self.reclaim_ratio
            )
            if pulled_back and reclaimed:
                return StrategyResult(
                    name=self.name,
                    signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
                )
        return StrategyResult(name=self.name, signal=Signal.wait())


@dataclass(frozen=True)
class ExhaustionReversalStrategy:
    name: str = "exhaustion-reversal"
    move_period: int = 240
    extreme_return: Decimal = Decimal("0.02")
    reclaim_period: int = 20
    reclaim_return: Decimal = Decimal("0.002")
    range_period: int = 720

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.move_period, self.reclaim_period, self.range_period) + 1
        if len(candles) < required:
            return StrategyResult(name=self.name, signal=Signal.wait())
        latest = candles[-1]
        move_base = candles[-self.move_period - 1].close_price
        move_return = (latest.close_price - move_base) / move_base
        reclaim_base = candles[-self.reclaim_period - 1].close_price
        reclaim = (latest.close_price - reclaim_base) / reclaim_base
        range_window = candles[-self.range_period:]
        range_high = max(candle.high_price for candle in range_window)
        range_low = min(candle.low_price for candle in range_window)
        range_position = (latest.close_price - range_low) / (range_high - range_low)
        if move_return <= -self.extreme_return and reclaim >= self.reclaim_return and range_position <= Decimal("0.35"):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
            )
        if move_return >= self.extreme_return and reclaim <= -self.reclaim_return and range_position >= Decimal("0.65"):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())


def momentum_combos() -> list[Combo]:
    return build_combos(
        "momentum",
        strategy_factory=BreakoutMomentumStrategy,
        strategy_grid=[
            {"lookback": 30, "breakout_buffer": Decimal("0.0005"), "momentum_period": 8, "min_momentum": Decimal("0.0008")},
            {"lookback": 60, "breakout_buffer": Decimal("0.001"), "momentum_period": 12, "min_momentum": Decimal("0.0015")},
            {"lookback": 120, "breakout_buffer": Decimal("0.0015"), "momentum_period": 20, "min_momentum": Decimal("0.002")},
        ],
        tpsl_grid=[
            ("fixed", {"stop_loss_ratio": Decimal("0.003"), "reward_risk_ratio": Decimal("2")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("2")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.006"), "reward_risk_ratio": Decimal("3")}),
            ("atr", {"atr_period": 14, "atr_multiplier": Decimal("2"), "reward_risk_ratio": Decimal("2")}),
        ],
    )


def selective_combos() -> list[Combo]:
    return build_combos(
        "selective",
        strategy_factory=SelectiveTrendBreakoutStrategy,
        strategy_grid=[
            {"lookback": 720, "breakout_buffer": Decimal("0.0015"), "trend_period": 1440, "min_trend_return": Decimal("0.01"), "cooldown_bars": 240},
            {"lookback": 1440, "breakout_buffer": Decimal("0.002"), "trend_period": 2880, "min_trend_return": Decimal("0.015"), "cooldown_bars": 360},
            {"lookback": 2880, "breakout_buffer": Decimal("0.003"), "trend_period": 4320, "min_trend_return": Decimal("0.02"), "cooldown_bars": 720},
        ],
        tpsl_grid=[
            ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("2")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.0075"), "reward_risk_ratio": Decimal("2")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.01"), "reward_risk_ratio": Decimal("2")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.01"), "reward_risk_ratio": Decimal("3")}),
            ("atr", {"atr_period": 60, "atr_multiplier": Decimal("3"), "reward_risk_ratio": Decimal("2")}),
        ],
    )


def swing_combos() -> list[Combo]:
    return build_combos(
        "swing",
        strategy_factory=SwingRetestStrategy,
        strategy_grid=[
            {"trend_period": 4320, "pullback_period": 720, "min_trend_return": Decimal("0.03"), "pullback_ratio": Decimal("0.01"), "reclaim_ratio": Decimal("0.002")},
            {"trend_period": 10080, "pullback_period": 1440, "min_trend_return": Decimal("0.05"), "pullback_ratio": Decimal("0.015"), "reclaim_ratio": Decimal("0.0025")},
            {"trend_period": 20160, "pullback_period": 2880, "min_trend_return": Decimal("0.08"), "pullback_ratio": Decimal("0.02"), "reclaim_ratio": Decimal("0.003")},
        ],
        tpsl_grid=[
            ("fixed", {"stop_loss_ratio": Decimal("0.0025"), "reward_risk_ratio": Decimal("4")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.003"), "reward_risk_ratio": Decimal("4")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("3")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.0075"), "reward_risk_ratio": Decimal("3")}),
        ],
    )


def reversal_combos() -> list[Combo]:
    return build_combos(
        "reversal2",
        strategy_factory=ExhaustionReversalStrategy,
        strategy_grid=[
            {"move_period": 120, "extreme_return": Decimal("0.012"), "reclaim_period": 10, "reclaim_return": Decimal("0.0015"), "range_period": 360},
            {"move_period": 240, "extreme_return": Decimal("0.02"), "reclaim_period": 20, "reclaim_return": Decimal("0.002"), "range_period": 720},
            {"move_period": 480, "extreme_return": Decimal("0.03"), "reclaim_period": 30, "reclaim_return": Decimal("0.003"), "range_period": 1440},
        ],
        tpsl_grid=[
            ("fixed", {"stop_loss_ratio": Decimal("0.0025"), "reward_risk_ratio": Decimal("4")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.003"), "reward_risk_ratio": Decimal("4")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.004"), "reward_risk_ratio": Decimal("3")}),
            ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("3")}),
        ],
    )


def build_combos(
    prefix: str,
    *,
    strategy_factory: Callable[..., object] = ChartPatternStrategy,
    strategy_grid: Iterable[Mapping[str, object]],
    tpsl_grid: Iterable[tuple[str, Mapping[str, object]]],
) -> list[Combo]:
    combos: list[Combo] = []
    for strategy_index, strategy_params in enumerate(strategy_grid, start=1):
        for tpsl_index, (kind, tpsl_params) in enumerate(tpsl_grid, start=1):
            combo_id = f"{prefix}-s{strategy_index}-t{tpsl_index}-{kind}"
            combos.append(
                Combo(
                    combo_id=combo_id,
                    strategy_factory=strategy_factory,
                    strategy_params=strategy_params,
                    tpsl_factory=lambda kind=kind, params=tpsl_params: make_tpsl(kind, params),
                    tpsl_params={"kind": kind, **tpsl_params},
                )
            )
    return combos


def make_tpsl(kind: str, params: Mapping[str, object]) -> object:
    if kind == "atr":
        return AtrTakeProfitStopLossStrategy(**params)
    if kind == "fixed":
        return FixedRatioTakeProfitStopLossStrategy(**params)
    raise ValueError(f"unknown tpsl kind: {kind}")


def load_seen_combo_ids() -> set[str]:
    if not RESULTS_PATH.exists():
        return set()
    seen = set()
    for line in RESULTS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        seen.add(str(json.loads(line)["combo_id"]))
    return seen


def append_result(result: Mapping[str, object]) -> None:
    with RESULTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")


def stringify_mapping(values: Mapping[str, object]) -> dict[str, object]:
    return {key: str(value) for key, value in values.items()}


def candle_record(candle: Candle) -> dict[str, object]:
    return {
        "opened_at": candle.opened_at.isoformat(),
        "open": str(candle.open_price),
        "high": str(candle.high_price),
        "low": str(candle.low_price),
        "close": str(candle.close_price),
        "volume": str(candle.volume),
    }


def candle_from_record(record: Mapping[str, object]) -> Candle:
    opened_at = datetime.fromisoformat(str(record["opened_at"]))
    return Candle(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        opened_at=opened_at,
        closed_at=opened_at.replace(second=0, microsecond=0) + TIMEFRAME_DELTA,
        open_price=Decimal(str(record["open"])),
        high_price=Decimal(str(record["high"])),
        low_price=Decimal(str(record["low"])),
        close_price=Decimal(str(record["close"])),
        volume=Decimal(str(record["volume"])),
    )


TIMEFRAME_DELTA = timedelta(seconds=TIMEFRAME.duration_seconds)


if __name__ == "__main__":
    main()
