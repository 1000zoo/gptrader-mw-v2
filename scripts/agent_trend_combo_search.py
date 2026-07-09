from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_combo_search import (
    END_AT,
    RESULTS_PATH,
    START_AT,
    SYMBOL,
    TIMEFRAME,
    CachedMarketData,
    Combo,
    InMemoryStrategyRepository,
    append_result,
    empty_indicators,
    load_or_fetch_market,
    load_seen_combo_ids,
    make_tpsl,
    target_met,
    stringify_mapping,
)
from src.application.usecases.strategy_lifecycle import (
    RunStrategyBacktestCycleCommand,
    RunStrategyBacktestCycleUseCase,
)
from src.domain.lifecycle import StrategyEvaluation
from src.domain.market import Candle, MarketSnapshot
from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import StaticStrategyCatalog, StrategyContext, StrategySpec
from src.domain.strategy.strategy_result import StrategyResult
from src.observability.logging import configure_runtime_logging


TARGET_WIN_RATE = Decimal("0.60")
TARGET_AVERAGE_TRADE_RETURN = Decimal("0.005")
_GLOBAL_CANDLES: tuple[Candle, ...] = ()
_FEATURE_CACHE: dict[tuple[object, ...], dict[object, dict[str, Decimal]]] = {}


@dataclass(frozen=True)
class HtfDonchianTrendStrategy:
    name: str = "htf-donchian-trend"
    trend_period: int = 4320
    confirm_period: int = 1440
    breakout_period: int = 720
    min_trend_return: Decimal = Decimal("0.03")
    min_confirm_return: Decimal = Decimal("0.008")
    breakout_buffer: Decimal = Decimal("0.001")
    signal_interval: int = 360
    long_enabled: bool = True
    short_enabled: bool = True

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        latest = context.market.latest_candle
        feature = _features_for(
            (
                self.name,
                self.trend_period,
                self.confirm_period,
                self.breakout_period,
                self.signal_interval,
            ),
            self.signal_interval,
            {
                "trend_return": self.trend_period,
                "confirm_return": self.confirm_period,
                "resistance": self.breakout_period,
                "support": self.breakout_period,
            },
        ).get(latest.opened_at)
        if feature is None:
            return StrategyResult(name=self.name, signal=Signal.wait())

        if (
            self.long_enabled
            and feature["trend_return"] >= self.min_trend_return
            and feature["confirm_return"] >= self.min_confirm_return
            and latest.close_price
            > feature["resistance"] * (Decimal("1") + self.breakout_buffer)
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
            )
        if (
            self.short_enabled
            and feature["trend_return"] <= -self.min_trend_return
            and feature["confirm_return"] <= -self.min_confirm_return
            and latest.close_price
            < feature["support"] * (Decimal("1") - self.breakout_buffer)
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())


@dataclass(frozen=True)
class HtfPullbackContinuationStrategy:
    name: str = "htf-pullback-continuation"
    trend_period: int = 10080
    confirm_period: int = 2880
    pullback_period: int = 720
    reclaim_period: int = 120
    min_trend_return: Decimal = Decimal("0.06")
    min_confirm_return: Decimal = Decimal("0.012")
    min_pullback: Decimal = Decimal("0.012")
    reclaim_buffer: Decimal = Decimal("0.001")
    signal_interval: int = 360
    long_enabled: bool = True
    short_enabled: bool = True

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        latest = context.market.latest_candle
        feature = _features_for(
            (
                self.name,
                self.trend_period,
                self.confirm_period,
                self.pullback_period,
                self.reclaim_period,
                self.signal_interval,
            ),
            self.signal_interval,
            {
                "trend_return": self.trend_period,
                "confirm_return": self.confirm_period,
                "recent_high": self.pullback_period,
                "recent_low": self.pullback_period,
                "reclaim_high": self.reclaim_period,
                "reclaim_low": self.reclaim_period,
                "previous_close": 1,
            },
        ).get(latest.opened_at)
        if feature is None:
            return StrategyResult(name=self.name, signal=Signal.wait())

        if self.long_enabled and feature["trend_return"] >= self.min_trend_return:
            pullback = (
                feature["recent_high"] - feature["previous_close"]
            ) / feature["recent_high"]
            if (
                feature["confirm_return"] >= self.min_confirm_return
                and pullback >= self.min_pullback
                and latest.close_price
                > feature["reclaim_high"] * (Decimal("1") + self.reclaim_buffer)
            ):
                return StrategyResult(
                    name=self.name,
                    signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
                )

        if self.short_enabled and feature["trend_return"] <= -self.min_trend_return:
            pullback = (
                feature["previous_close"] - feature["recent_low"]
            ) / feature["previous_close"]
            if (
                feature["confirm_return"] <= -self.min_confirm_return
                and pullback >= self.min_pullback
                and latest.close_price
                < feature["reclaim_low"] * (Decimal("1") - self.reclaim_buffer)
            ):
                return StrategyResult(
                    name=self.name,
                    signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
                )

        return StrategyResult(name=self.name, signal=Signal.wait())


@dataclass(frozen=True)
class HtfTrendAccelerationStrategy:
    name: str = "htf-trend-acceleration"
    trend_period: int = 20160
    fast_period: int = 1440
    slow_period: int = 4320
    min_trend_return: Decimal = Decimal("0.08")
    min_fast_return: Decimal = Decimal("0.015")
    min_slow_return: Decimal = Decimal("0.03")
    max_extension: Decimal = Decimal("0.10")
    signal_interval: int = 720
    long_enabled: bool = True
    short_enabled: bool = True

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        latest = context.market.latest_candle
        feature = _features_for(
            (
                self.name,
                self.trend_period,
                self.fast_period,
                self.slow_period,
                self.signal_interval,
            ),
            self.signal_interval,
            {
                "trend_return": self.trend_period,
                "fast_return": self.fast_period,
                "slow_return": self.slow_period,
                "slow_high": self.slow_period,
                "slow_low": self.slow_period,
            },
        ).get(latest.opened_at)
        if feature is None:
            return StrategyResult(name=self.name, signal=Signal.wait())
        extension_from_low = (latest.close_price - feature["slow_low"]) / feature["slow_low"]
        extension_from_high = (
            feature["slow_high"] - latest.close_price
        ) / feature["slow_high"]

        if (
            self.long_enabled
            and feature["trend_return"] >= self.min_trend_return
            and feature["fast_return"] >= self.min_fast_return
            and feature["slow_return"] >= self.min_slow_return
            and extension_from_low <= self.max_extension
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
            )
        if (
            self.short_enabled
            and feature["trend_return"] <= -self.min_trend_return
            and feature["fast_return"] <= -self.min_fast_return
            and feature["slow_return"] <= -self.min_slow_return
            and extension_from_high <= self.max_extension
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-win-rate", type=Decimal, default=TARGET_WIN_RATE)
    parser.add_argument(
        "--min-average-trade-return",
        type=Decimal,
        default=TARGET_AVERAGE_TRADE_RETURN,
    )
    parser.add_argument("--min-trade-count", type=int, default=100)
    args = parser.parse_args()

    configure_runtime_logging(level="ERROR")
    market = load_or_fetch_market()
    set_feature_source(market.candles)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen = load_seen_combo_ids()
    candidates = [combo for combo in build_agent_trend_combos() if combo.combo_id not in seen]
    if args.limit > 0:
        candidates = candidates[: args.limit]

    best: dict[str, object] | None = None
    for combo in candidates:
        result = run_combo(market, combo)
        append_result(result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if _is_better(result, best):
            best = result
        if target_met(
            result,
            min_win_rate=args.min_win_rate,
            min_average_trade_return=args.min_average_trade_return,
            min_trade_count=args.min_trade_count,
        ):
            print(f"TARGET_FOUND {combo.combo_id}")
            return
    if best is not None:
        print("BEST " + json.dumps(best, ensure_ascii=False, sort_keys=True))
    print("TARGET_NOT_FOUND")


def run_combo(market: MarketSnapshot, combo: Combo) -> dict[str, object]:
    repository = InMemoryStrategyRepository()
    catalog = StaticStrategyCatalog(
        entries=(
            (
                StrategySpec(
                    strategy_id=combo.combo_id,
                    name=combo.combo_id,
                    implementation=(
                        "scripts.agent_trend_combo_search."
                        f"{combo.strategy_factory.__name__}"
                    ),
                    version="search",
                    symbol=SYMBOL,
                    timeframe=TIMEFRAME,
                    lookback_candle_limit=_candle_limit_for_combo(combo),
                    parameters=combo.strategy_params,
                    metadata={"family": "agent_trend_search"},
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
        indicator_factory=empty_indicators,
    )
    result = usecase.execute(
        RunStrategyBacktestCycleCommand(
            cycle_id="agent-trend-combo-search-6m",
            enabled_strategy_ids=(combo.combo_id,),
            start_at=START_AT,
            end_at=END_AT,
            metadata={"combo_id": combo.combo_id},
        )
    )
    evaluation = repository.evaluations[0] if repository.evaluations else None
    metrics = _metrics(evaluation)
    return {
        "combo_id": combo.combo_id,
        "succeeded": result.succeeded_count == 1,
        "error": None if result.succeeded_count == 1 else result.items[0].error_message,
        "trade_count": int(metrics.get("trade_count", Decimal("0"))),
        "win_rate": str(metrics.get("win_rate", Decimal("0"))),
        "return_ratio": str(metrics.get("return_ratio", Decimal("0"))),
        "average_trade_return": str(
            metrics.get("average_trade_return", Decimal("0"))
        ),
        "net_pnl": str(metrics.get("net_pnl", Decimal("0"))),
        "max_drawdown_ratio": str(metrics.get("max_drawdown_ratio", Decimal("0"))),
        "strategy_params": stringify_mapping(combo.strategy_params),
        "tpsl_params": stringify_mapping(combo.tpsl_params),
    }


def build_agent_trend_combos() -> list[Combo]:
    combos: list[Combo] = []
    combos.extend(
        _build_combos(
            "agent-trend2-donchian",
            strategy_factory=HtfDonchianTrendStrategy,
            strategy_grid=[
                {"trend_period": 4320, "confirm_period": 1440, "breakout_period": 360, "min_trend_return": Decimal("0.025"), "min_confirm_return": Decimal("0.006"), "breakout_buffer": Decimal("0.0005"), "signal_interval": 240, "long_enabled": True, "short_enabled": True},
                {"trend_period": 10080, "confirm_period": 2880, "breakout_period": 720, "min_trend_return": Decimal("0.05"), "min_confirm_return": Decimal("0.012"), "breakout_buffer": Decimal("0.001"), "signal_interval": 360, "long_enabled": True, "short_enabled": True},
                {"trend_period": 20160, "confirm_period": 4320, "breakout_period": 1440, "min_trend_return": Decimal("0.08"), "min_confirm_return": Decimal("0.02"), "breakout_buffer": Decimal("0.0015"), "signal_interval": 720, "long_enabled": True, "short_enabled": True},
                {"trend_period": 10080, "confirm_period": 1440, "breakout_period": 360, "min_trend_return": Decimal("0.04"), "min_confirm_return": Decimal("0.01"), "breakout_buffer": Decimal("0.0005"), "signal_interval": 720, "long_enabled": True, "short_enabled": False},
                {"trend_period": 1440, "confirm_period": 360, "breakout_period": 120, "min_trend_return": Decimal("0.008"), "min_confirm_return": Decimal("0.002"), "breakout_buffer": Decimal("0.0002"), "signal_interval": 120, "long_enabled": False, "short_enabled": True},
                {"trend_period": 2880, "confirm_period": 720, "breakout_period": 180, "min_trend_return": Decimal("0.014"), "min_confirm_return": Decimal("0.003"), "breakout_buffer": Decimal("0.0003"), "signal_interval": 180, "long_enabled": False, "short_enabled": True},
                {"trend_period": 4320, "confirm_period": 720, "breakout_period": 240, "min_trend_return": Decimal("0.02"), "min_confirm_return": Decimal("0.004"), "breakout_buffer": Decimal("0.0003"), "signal_interval": 240, "long_enabled": False, "short_enabled": True},
            ],
            tpsl_grid=_trend_tpsl_grid(),
        )
    )
    combos.extend(
        _build_combos(
            "agent-trend2-pullback",
            strategy_factory=HtfPullbackContinuationStrategy,
            strategy_grid=[
                {"trend_period": 4320, "confirm_period": 1440, "pullback_period": 360, "reclaim_period": 60, "min_trend_return": Decimal("0.025"), "min_confirm_return": Decimal("0.005"), "min_pullback": Decimal("0.006"), "reclaim_buffer": Decimal("0.0005"), "signal_interval": 240, "long_enabled": True, "short_enabled": True},
                {"trend_period": 10080, "confirm_period": 2880, "pullback_period": 720, "reclaim_period": 120, "min_trend_return": Decimal("0.05"), "min_confirm_return": Decimal("0.01"), "min_pullback": Decimal("0.012"), "reclaim_buffer": Decimal("0.001"), "signal_interval": 360, "long_enabled": True, "short_enabled": True},
                {"trend_period": 20160, "confirm_period": 4320, "pullback_period": 1440, "reclaim_period": 240, "min_trend_return": Decimal("0.08"), "min_confirm_return": Decimal("0.018"), "min_pullback": Decimal("0.018"), "reclaim_buffer": Decimal("0.0015"), "signal_interval": 720, "long_enabled": True, "short_enabled": True},
                {"trend_period": 10080, "confirm_period": 1440, "pullback_period": 720, "reclaim_period": 60, "min_trend_return": Decimal("0.04"), "min_confirm_return": Decimal("0.008"), "min_pullback": Decimal("0.01"), "reclaim_buffer": Decimal("0.0005"), "signal_interval": 720, "long_enabled": True, "short_enabled": False},
                {"trend_period": 1440, "confirm_period": 360, "pullback_period": 180, "reclaim_period": 30, "min_trend_return": Decimal("0.008"), "min_confirm_return": Decimal("0.0015"), "min_pullback": Decimal("0.003"), "reclaim_buffer": Decimal("0.0002"), "signal_interval": 120, "long_enabled": False, "short_enabled": True},
                {"trend_period": 2880, "confirm_period": 720, "pullback_period": 240, "reclaim_period": 45, "min_trend_return": Decimal("0.014"), "min_confirm_return": Decimal("0.0025"), "min_pullback": Decimal("0.004"), "reclaim_buffer": Decimal("0.0002"), "signal_interval": 180, "long_enabled": False, "short_enabled": True},
                {"trend_period": 4320, "confirm_period": 720, "pullback_period": 360, "reclaim_period": 60, "min_trend_return": Decimal("0.02"), "min_confirm_return": Decimal("0.003"), "min_pullback": Decimal("0.005"), "reclaim_buffer": Decimal("0.0003"), "signal_interval": 240, "long_enabled": False, "short_enabled": True},
            ],
            tpsl_grid=_trend_tpsl_grid(),
        )
    )
    combos.extend(
        _build_combos(
            "agent-trend2-accel",
            strategy_factory=HtfTrendAccelerationStrategy,
            strategy_grid=[
                {"trend_period": 10080, "fast_period": 720, "slow_period": 2880, "min_trend_return": Decimal("0.04"), "min_fast_return": Decimal("0.008"), "min_slow_return": Decimal("0.018"), "max_extension": Decimal("0.08"), "signal_interval": 360, "long_enabled": True, "short_enabled": True},
                {"trend_period": 20160, "fast_period": 1440, "slow_period": 4320, "min_trend_return": Decimal("0.08"), "min_fast_return": Decimal("0.015"), "min_slow_return": Decimal("0.03"), "max_extension": Decimal("0.10"), "signal_interval": 720, "long_enabled": True, "short_enabled": True},
                {"trend_period": 30240, "fast_period": 2880, "slow_period": 10080, "min_trend_return": Decimal("0.12"), "min_fast_return": Decimal("0.025"), "min_slow_return": Decimal("0.05"), "max_extension": Decimal("0.14"), "signal_interval": 1440, "long_enabled": True, "short_enabled": True},
            ],
            tpsl_grid=_trend_tpsl_grid(),
        )
    )
    return combos


def _trend_tpsl_grid() -> list[tuple[str, Mapping[str, object]]]:
    return [
        ("fixed", {"stop_loss_ratio": Decimal("0.006"), "reward_risk_ratio": Decimal("2.5")}),
        ("fixed", {"stop_loss_ratio": Decimal("0.008"), "reward_risk_ratio": Decimal("2")}),
        ("fixed", {"stop_loss_ratio": Decimal("0.01"), "reward_risk_ratio": Decimal("2")}),
        ("fixed", {"stop_loss_ratio": Decimal("0.012"), "reward_risk_ratio": Decimal("1.75")}),
        ("fixed", {"stop_loss_ratio": Decimal("0.015"), "reward_risk_ratio": Decimal("1.5")}),
        ("atr", {"atr_period": 60, "atr_multiplier": Decimal("4"), "reward_risk_ratio": Decimal("2")}),
        ("atr", {"atr_period": 240, "atr_multiplier": Decimal("3"), "reward_risk_ratio": Decimal("2")}),
    ]


def _build_combos(
    prefix: str,
    *,
    strategy_factory: Callable[..., object],
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
                    strategy_params=dict(strategy_params),
                    tpsl_factory=lambda kind=kind, params=tpsl_params: make_tpsl(
                        kind,
                        params,
                    ),
                    tpsl_params={"kind": kind, **dict(tpsl_params)},
                )
            )
    return combos


def _candle_limit_for_combo(combo: Combo) -> int:
    strategy_period_keys = (
        "trend_period",
        "confirm_period",
        "breakout_period",
        "pullback_period",
        "reclaim_period",
        "fast_period",
        "slow_period",
    )
    strategy_limit = max(
        [int(combo.strategy_params.get(key, 0)) for key in strategy_period_keys],
        default=0,
    )
    return max(10, strategy_limit + 3, int(combo.tpsl_params.get("atr_period", 0)) + 3)


def _metrics(evaluation: StrategyEvaluation | None) -> dict[str, Decimal]:
    if evaluation is None:
        return {}
    return dict(evaluation.metrics)


def _is_better(
    result: Mapping[str, object],
    best: Mapping[str, object] | None,
) -> bool:
    if best is None:
        return True
    result_score = (
        Decimal(str(result["average_trade_return"])),
        Decimal(str(result["win_rate"])),
        Decimal(str(result["return_ratio"])),
    )
    best_score = (
        Decimal(str(best["average_trade_return"])),
        Decimal(str(best["win_rate"])),
        Decimal(str(best["return_ratio"])),
    )
    return result_score > best_score


def _return_since(candles: tuple[Candle, ...], period: int) -> Decimal:
    base = candles[-period - 1].close_price
    return (candles[-1].close_price - base) / base


def set_feature_source(candles: tuple[Candle, ...]) -> None:
    global _GLOBAL_CANDLES
    _GLOBAL_CANDLES = candles
    _FEATURE_CACHE.clear()


def _features_for(
    key: tuple[object, ...],
    signal_interval: int,
    periods: Mapping[str, int],
) -> dict[object, dict[str, Decimal]]:
    cached = _FEATURE_CACHE.get(key)
    if cached is not None:
        return cached
    if not _GLOBAL_CANDLES:
        raise ValueError("feature source is not initialized")
    max_period = max(periods.values())
    features: dict[object, dict[str, Decimal]] = {}
    for index in range(max_period + 1, len(_GLOBAL_CANDLES)):
        latest = _GLOBAL_CANDLES[index]
        if not _interval_gate(latest, signal_interval):
            continue
        values: dict[str, Decimal] = {}
        for name, period in periods.items():
            if name.endswith("_return"):
                base = _GLOBAL_CANDLES[index - period].close_price
                values[name] = (latest.close_price - base) / base
            elif name.endswith("_high") or name in {"resistance", "recent_high"}:
                window = _GLOBAL_CANDLES[index - period : index]
                values[name] = max(candle.high_price for candle in window)
            elif name.endswith("_low") or name in {"support", "recent_low"}:
                window = _GLOBAL_CANDLES[index - period : index]
                values[name] = min(candle.low_price for candle in window)
            elif name == "previous_close":
                values[name] = _GLOBAL_CANDLES[index - 1].close_price
            else:
                raise ValueError(f"unknown feature: {name}")
        features[latest.opened_at] = values
    _FEATURE_CACHE[key] = features
    return features


def _interval_gate(candle: Candle, interval_minutes: int) -> bool:
    if interval_minutes <= 1:
        return True
    minute_of_day = candle.opened_at.hour * 60 + candle.opened_at.minute
    return minute_of_day % interval_minutes == 0


if __name__ == "__main__":
    main()
