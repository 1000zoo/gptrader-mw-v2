from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_combo_search import (  # noqa: E402
    Combo,
    append_result,
    load_or_fetch_market,
    load_seen_combo_ids,
    make_tpsl,
    run_combo,
    target_met,
)
from src.domain.signal import Signal, SignalDirection  # noqa: E402
from src.domain.strategy import StrategyContext  # noqa: E402
from src.domain.strategy.strategy_result import StrategyResult  # noqa: E402
from src.observability.logging import configure_runtime_logging  # noqa: E402


TARGET_WIN_RATE = Decimal("0.60")
TARGET_AVERAGE_TRADE_RETURN = Decimal("0.005")


@dataclass
class RangeEdgeReversionStrategy:
    name: str = "range-edge-reversion"
    range_period: int = 720
    lower_band: Decimal = Decimal("0.08")
    upper_band: Decimal = Decimal("0.92")
    min_range_width: Decimal = Decimal("0.018")
    reclaim_return: Decimal = Decimal("0.001")
    _window: object = field(default=None, init=False, repr=False)

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        if len(candles) < self.range_period + 2:
            return StrategyResult(name=self.name, signal=Signal.wait())

        latest = candles[-1]
        previous = candles[-2]
        range_low, range_high = self._range(candles)
        if range_low is None or range_high is None:
            return StrategyResult(name=self.name, signal=Signal.wait())
        if range_low <= Decimal("0") or range_high <= range_low:
            return StrategyResult(name=self.name, signal=Signal.wait())

        width_ratio = (range_high - range_low) / range_low
        if width_ratio < self.min_range_width:
            return StrategyResult(name=self.name, signal=Signal.wait())

        range_position = (latest.close_price - range_low) / (range_high - range_low)
        reclaimed_up = latest.close_price >= previous.close_price * (
            Decimal("1") + self.reclaim_return
        )
        reclaimed_down = latest.close_price <= previous.close_price * (
            Decimal("1") - self.reclaim_return
        )

        if range_position <= self.lower_band and reclaimed_up:
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
            )
        if range_position >= self.upper_band and reclaimed_down:
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())

    def _range(self, candles) -> tuple[Decimal | None, Decimal | None]:
        if self._window is None:
            self._window = RollingRange(self.range_period)
        return self._window.range(candles)


@dataclass
class MeanDistanceReversionStrategy:
    name: str = "mean-distance-reversion"
    range_period: int = 1440
    min_distance_from_mid: Decimal = Decimal("0.012")
    min_reversal_return: Decimal = Decimal("0.0015")
    max_range_position_long: Decimal = Decimal("0.25")
    min_range_position_short: Decimal = Decimal("0.75")
    _window: object = field(default=None, init=False, repr=False)

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        if len(candles) < self.range_period + 2:
            return StrategyResult(name=self.name, signal=Signal.wait())

        latest = candles[-1]
        previous = candles[-2]
        range_low, range_high = self._range(candles)
        if range_low is None or range_high is None:
            return StrategyResult(name=self.name, signal=Signal.wait())
        if range_high <= range_low:
            return StrategyResult(name=self.name, signal=Signal.wait())

        mid = (range_high + range_low) / Decimal("2")
        if mid <= Decimal("0"):
            return StrategyResult(name=self.name, signal=Signal.wait())

        distance = (latest.close_price - mid) / mid
        range_position = (latest.close_price - range_low) / (range_high - range_low)
        reversal = (latest.close_price - previous.close_price) / previous.close_price

        if (
            distance <= -self.min_distance_from_mid
            and range_position <= self.max_range_position_long
            and reversal >= self.min_reversal_return
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
            )
        if (
            distance >= self.min_distance_from_mid
            and range_position >= self.min_range_position_short
            and reversal <= -self.min_reversal_return
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())

    def _range(self, candles) -> tuple[Decimal | None, Decimal | None]:
        if self._window is None:
            self._window = RollingRange(self.range_period)
        return self._window.range(candles)


@dataclass
class ExhaustionSnapbackRangeStrategy:
    name: str = "exhaustion-snapback-range"
    move_period: int = 120
    range_period: int = 1440
    extreme_return: Decimal = Decimal("0.012")
    reclaim_return: Decimal = Decimal("0.0015")
    max_range_position_long: Decimal = Decimal("0.30")
    min_range_position_short: Decimal = Decimal("0.70")
    _window: object = field(default=None, init=False, repr=False)

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        required = max(self.move_period, self.range_period) + 2
        if len(candles) < required:
            return StrategyResult(name=self.name, signal=Signal.wait())

        latest = candles[-1]
        previous = candles[-2]
        move_base = candles[-self.move_period - 1].close_price
        if move_base <= Decimal("0") or previous.close_price <= Decimal("0"):
            return StrategyResult(name=self.name, signal=Signal.wait())

        range_low, range_high = self._range(candles)
        if range_low is None or range_high is None or range_high <= range_low:
            return StrategyResult(name=self.name, signal=Signal.wait())

        move_return = (latest.close_price - move_base) / move_base
        snapback = (latest.close_price - previous.close_price) / previous.close_price
        range_position = (latest.close_price - range_low) / (range_high - range_low)

        if (
            move_return <= -self.extreme_return
            and snapback >= self.reclaim_return
            and range_position <= self.max_range_position_long
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("1")),
            )
        if (
            move_return >= self.extreme_return
            and snapback <= -self.reclaim_return
            and range_position >= self.min_range_position_short
        ):
            return StrategyResult(
                name=self.name,
                signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("1")),
            )
        return StrategyResult(name=self.name, signal=Signal.wait())

    def _range(self, candles) -> tuple[Decimal | None, Decimal | None]:
        if self._window is None:
            self._window = RollingRange(self.range_period)
        return self._window.range(candles)


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

        previous = candles[-2]
        self._append(previous)
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
    seen = load_seen_combo_ids()
    candidates = [combo for combo in build_agent_range_combos() if combo.combo_id not in seen]
    if args.limit > 0:
        candidates = candidates[: args.limit]

    best: dict[str, object] | None = None
    target_found = False
    for combo in candidates:
        result = run_combo(market, combo)
        append_result(result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if best is None or _score(result) > _score(best):
            best = result
        if target_met(
            result,
            min_win_rate=args.min_win_rate,
            min_average_trade_return=args.min_average_trade_return,
            min_trade_count=args.min_trade_count,
        ):
            print(f"TARGET_FOUND {combo.combo_id}")
            target_found = True
            break

    if best is not None:
        print(
            json.dumps(
                {"best_combo_id": best["combo_id"], "target_found": target_found},
                ensure_ascii=False,
                sort_keys=True,
            )
        )


def build_agent_range_combos() -> list[Combo]:
    return [
        *build_combos(
            "agent-range-wide",
            RangeEdgeReversionStrategy,
            strategy_grid=[
                {
                    "range_period": 360,
                    "lower_band": Decimal("0.06"),
                    "upper_band": Decimal("0.94"),
                    "min_range_width": Decimal("0.012"),
                    "reclaim_return": Decimal("0.0008"),
                },
                {
                    "range_period": 720,
                    "lower_band": Decimal("0.04"),
                    "upper_band": Decimal("0.96"),
                    "min_range_width": Decimal("0.020"),
                    "reclaim_return": Decimal("0.0012"),
                },
            ],
            tpsl_grid=[
                ("fixed", {"stop_loss_ratio": Decimal("0.03"), "reward_risk_ratio": Decimal("0.2")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.04"), "reward_risk_ratio": Decimal("0.15")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.05"), "reward_risk_ratio": Decimal("0.12")}),
            ],
        ),
        *build_combos(
            "agent-range-wide2",
            RangeEdgeReversionStrategy,
            strategy_grid=[
                {
                    "range_period": 360,
                    "lower_band": Decimal("0.06"),
                    "upper_band": Decimal("0.94"),
                    "min_range_width": Decimal("0.012"),
                    "reclaim_return": Decimal("0.0008"),
                },
            ],
            tpsl_grid=[
                ("fixed", {"stop_loss_ratio": Decimal("0.08"), "reward_risk_ratio": Decimal("0.15")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.10"), "reward_risk_ratio": Decimal("0.15")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.10"), "reward_risk_ratio": Decimal("0.2")}),
            ],
        ),
        *build_combos(
            "agent-range-wide3",
            RangeEdgeReversionStrategy,
            strategy_grid=[
                {
                    "range_period": 360,
                    "lower_band": Decimal("0.06"),
                    "upper_band": Decimal("0.94"),
                    "min_range_width": Decimal("0.012"),
                    "reclaim_return": Decimal("0.0008"),
                },
            ],
            tpsl_grid=[
                ("fixed", {"stop_loss_ratio": Decimal("0.12"), "reward_risk_ratio": Decimal("0.15")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.15"), "reward_risk_ratio": Decimal("0.10")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.15"), "reward_risk_ratio": Decimal("0.12")}),
            ],
        ),
        *build_combos(
            "agent-range-wide4",
            RangeEdgeReversionStrategy,
            strategy_grid=[
                {
                    "range_period": 300,
                    "lower_band": Decimal("0.06"),
                    "upper_band": Decimal("0.94"),
                    "min_range_width": Decimal("0.010"),
                    "reclaim_return": Decimal("0.0007"),
                },
                {
                    "range_period": 360,
                    "lower_band": Decimal("0.055"),
                    "upper_band": Decimal("0.945"),
                    "min_range_width": Decimal("0.010"),
                    "reclaim_return": Decimal("0.0007"),
                },
                {
                    "range_period": 420,
                    "lower_band": Decimal("0.06"),
                    "upper_band": Decimal("0.94"),
                    "min_range_width": Decimal("0.012"),
                    "reclaim_return": Decimal("0.0008"),
                },
            ],
            tpsl_grid=[
                ("fixed", {"stop_loss_ratio": Decimal("0.09"), "reward_risk_ratio": Decimal("0.15")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.10"), "reward_risk_ratio": Decimal("0.14")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.10"), "reward_risk_ratio": Decimal("0.15")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.11"), "reward_risk_ratio": Decimal("0.13")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.11"), "reward_risk_ratio": Decimal("0.15")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.12"), "reward_risk_ratio": Decimal("0.12")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.12"), "reward_risk_ratio": Decimal("0.14")}),
            ],
        ),
        *build_combos(
            "agent-range-snap",
            ExhaustionSnapbackRangeStrategy,
            strategy_grid=[
                {
                    "move_period": 60,
                    "range_period": 720,
                    "extreme_return": Decimal("0.006"),
                    "reclaim_return": Decimal("0.001"),
                    "max_range_position_long": Decimal("0.30"),
                    "min_range_position_short": Decimal("0.70"),
                },
                {
                    "move_period": 120,
                    "range_period": 1440,
                    "extreme_return": Decimal("0.012"),
                    "reclaim_return": Decimal("0.0015"),
                    "max_range_position_long": Decimal("0.25"),
                    "min_range_position_short": Decimal("0.75"),
                },
                {
                    "move_period": 240,
                    "range_period": 2880,
                    "extreme_return": Decimal("0.020"),
                    "reclaim_return": Decimal("0.002"),
                    "max_range_position_long": Decimal("0.22"),
                    "min_range_position_short": Decimal("0.78"),
                },
            ],
            tpsl_grid=[
                ("fixed", {"stop_loss_ratio": Decimal("0.0075"), "reward_risk_ratio": Decimal("1.5")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.01"), "reward_risk_ratio": Decimal("1.5")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("2")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.0075"), "reward_risk_ratio": Decimal("2")}),
            ],
        ),
        *build_combos(
            "agent-range-edge",
            RangeEdgeReversionStrategy,
            strategy_grid=[
                {
                    "range_period": 360,
                    "lower_band": Decimal("0.06"),
                    "upper_band": Decimal("0.94"),
                    "min_range_width": Decimal("0.012"),
                    "reclaim_return": Decimal("0.0008"),
                },
                {
                    "range_period": 720,
                    "lower_band": Decimal("0.08"),
                    "upper_band": Decimal("0.92"),
                    "min_range_width": Decimal("0.018"),
                    "reclaim_return": Decimal("0.001"),
                },
                {
                    "range_period": 1440,
                    "lower_band": Decimal("0.10"),
                    "upper_band": Decimal("0.90"),
                    "min_range_width": Decimal("0.025"),
                    "reclaim_return": Decimal("0.0012"),
                },
                {
                    "range_period": 2880,
                    "lower_band": Decimal("0.12"),
                    "upper_band": Decimal("0.88"),
                    "min_range_width": Decimal("0.035"),
                    "reclaim_return": Decimal("0.0015"),
                },
            ],
            tpsl_grid=[
                ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("1")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.0075"), "reward_risk_ratio": Decimal("1")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.01"), "reward_risk_ratio": Decimal("1")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("2")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.0075"), "reward_risk_ratio": Decimal("2")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("3")}),
            ],
        ),
        *build_combos(
            "agent-range-mean",
            MeanDistanceReversionStrategy,
            strategy_grid=[
                {
                    "range_period": 720,
                    "min_distance_from_mid": Decimal("0.006"),
                    "min_reversal_return": Decimal("0.0008"),
                    "max_range_position_long": Decimal("0.22"),
                    "min_range_position_short": Decimal("0.78"),
                },
                {
                    "range_period": 1440,
                    "min_distance_from_mid": Decimal("0.010"),
                    "min_reversal_return": Decimal("0.001"),
                    "max_range_position_long": Decimal("0.20"),
                    "min_range_position_short": Decimal("0.80"),
                },
                {
                    "range_period": 2880,
                    "min_distance_from_mid": Decimal("0.014"),
                    "min_reversal_return": Decimal("0.0012"),
                    "max_range_position_long": Decimal("0.18"),
                    "min_range_position_short": Decimal("0.82"),
                },
                {
                    "range_period": 4320,
                    "min_distance_from_mid": Decimal("0.020"),
                    "min_reversal_return": Decimal("0.0015"),
                    "max_range_position_long": Decimal("0.15"),
                    "min_range_position_short": Decimal("0.85"),
                },
            ],
            tpsl_grid=[
                ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("1")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.0075"), "reward_risk_ratio": Decimal("1")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.01"), "reward_risk_ratio": Decimal("1")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("2")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.0075"), "reward_risk_ratio": Decimal("2")}),
                ("fixed", {"stop_loss_ratio": Decimal("0.005"), "reward_risk_ratio": Decimal("3")}),
            ],
        ),
    ]


def build_combos(
    prefix: str,
    strategy_factory: object,
    *,
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


def _score(result: Mapping[str, object]) -> tuple[Decimal, Decimal, int]:
    return (
        Decimal(str(result["average_trade_return"])),
        Decimal(str(result["win_rate"])),
        int(result["trade_count"]),
    )


if __name__ == "__main__":
    main()
