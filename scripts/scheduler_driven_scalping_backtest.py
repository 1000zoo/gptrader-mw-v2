from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_scalping_external_periods import PeriodSpec, load_period_market  # noqa: E402
from src.application.usecases.trade import (  # noqa: E402
    ClosePositionUseCase,
    ExecuteTradeCommand,
    ExecuteTradeUseCase,
    ManageOpenPositionUseCase,
    SyncPositionUseCase,
)
from src.domain.execution import OrderRequest, OrderResult  # noqa: E402
from src.domain.indicator import IndicatorSet  # noqa: E402
from src.domain.market import MarketSnapshot, Symbol, Timeframe  # noqa: E402
from src.domain.ports import SignalLogEntry  # noqa: E402
from src.domain.risk import ExposureLimit  # noqa: E402
from src.domain.signal import Signal, SignalDirection  # noqa: E402
from src.domain.signal_generator import CompositeSignalGenerator  # noqa: E402
from src.domain.signal_generator.signal_generator import GeneratedSignal  # noqa: E402
from src.domain.strategy.implementations.regime_router_scalper_strategy import (  # noqa: E402
    RegimeRouterScalperStrategy,
)
from src.interfaces.scheduler import TradeScheduler  # noqa: E402
from src.observability.logging import configure_runtime_logging  # noqa: E402


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")
GENERATOR_ID = "scheduler-driven-live-scalp-multi-t1-r1-b4-tbr"
CANDLE_LIMIT = 262
INITIAL_EQUITY = Decimal("10000")
FEE_RATE = Decimal("0.0004")
SLIPPAGE_RATE = Decimal("0.0002")
RESULTS_PATH = Path("docs/backtests/scheduler-driven-scalping-backtest.json")
SUMMARY_PATH = Path("docs/backtests/scheduler-driven-scalping-backtest.md")
TRAIN_START = datetime(2025, 11, 9, 0, 0, tzinfo=timezone.utc)
TRAIN_END = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)
TEST_START = TRAIN_END
TEST_END = datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SchedulerBacktestCandidate:
    candidate_id: str
    strategy_params: dict[str, object]
    take_profit_ratio: Decimal
    stop_loss_ratio: Decimal
    equity_ratio: Decimal
    leverage: Decimal
    guard: "DefensiveGuardConfig" = field(default_factory=lambda: DefensiveGuardConfig())


@dataclass(frozen=True)
class DefensiveGuardConfig:
    min_minutes_between_entries: int = 0
    pause_minutes_after_loss: int = 0
    max_daily_loss_ratio: Decimal = Decimal("1")
    max_daily_trades: int = 999
    max_consecutive_losses: int = 999
    max_peak_drawdown_ratio: Decimal = Decimal("1")
    min_signal_confidence: Decimal = Decimal("0")
    min_1m_range_ratio: Decimal = Decimal("0")
    max_1m_range_ratio: Decimal = Decimal("1")


@dataclass
class BacktestPosition:
    direction: SignalDirection
    entry_price: Decimal
    quantity: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    opened_index: int
    entry_fee: Decimal

    @property
    def notional(self) -> Decimal:
        return self.entry_price * self.quantity


@dataclass
class BacktestTrade:
    entry_price: Decimal
    exit_price: Decimal
    direction: SignalDirection
    quantity: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    fee_paid: Decimal
    exit_reason: str
    holding_bars: int


class CursorMarketData:
    def __init__(self, market: MarketSnapshot) -> None:
        self._candles = market.candles
        self.cursor = 0

    @property
    def current_close(self) -> Decimal:
        return self._candles[self.cursor].close_price

    def load_candles(self, symbol, timeframe, limit):
        return self.load_snapshot(symbol, timeframe, limit).candles

    def load_snapshot(self, symbol, timeframe, limit) -> MarketSnapshot:
        start = max(0, self.cursor - limit + 1)
        return MarketSnapshot(self._candles[start : self.cursor + 1])


class InMemorySignalLogRepository:
    def __init__(self) -> None:
        self.entries: list[SignalLogEntry] = []

    def append_signal(self, entry: SignalLogEntry) -> None:
        self.entries.append(entry)

    def list_signals_for_generator(self, generator_id: str) -> tuple[SignalLogEntry, ...]:
        return tuple(entry for entry in self.entries if entry.generator_id == generator_id)


class BacktestOrderExecution:
    def __init__(self, market_data: CursorMarketData) -> None:
        self.market_data = market_data
        self.submitted_orders: list[OrderRequest] = []
        self.last_entry_result: OrderResult | None = None
        self.last_take_profit: Decimal | None = None
        self.last_stop_loss: Decimal | None = None

    def submit_order(self, request: OrderRequest) -> OrderResult:
        self.submitted_orders.append(request)
        fill_price = _entry_fill_price(self.market_data.current_close, request.side)
        result = OrderResult.filled(
            request.client_order_id,
            executed_quantity=request.quantity or Decimal("0"),
            average_price=fill_price,
            exchange_order_id=f"bt-{len(self.submitted_orders)}",
        )
        self.last_entry_result = result
        return result

    def submit_take_profit_stop_loss_orders(
        self,
        symbol: Symbol,
        position_direction: SignalDirection,
        take_profit: Decimal,
        stop_loss: Decimal,
        client_order_id_prefix: str,
    ) -> tuple[OrderResult, OrderResult]:
        self.last_take_profit = take_profit
        self.last_stop_loss = stop_loss
        return (
            OrderResult.accepted(f"{client_order_id_prefix}-tp", "bt-tp"),
            OrderResult.accepted(f"{client_order_id_prefix}-sl", "bt-sl"),
        )

    def load_order_reports(self, since, until):
        return ()


def main() -> None:
    configure_runtime_logging(level="ERROR")
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025/11/9")
    parser.add_argument("--end", default="2026/7/8")
    parser.add_argument("--mode", choices=("single", "search"), default="search")
    parser.add_argument("--train-test", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--candidate-id", action="append", default=[])
    args = parser.parse_args()

    period = PeriodSpec("BTCUSDT", f"scheduler-driven-{_label_date(args.start)}_{_label_date(args.end)}", args.start, args.end)
    market = load_period_market(period)
    if market is None:
        raise RuntimeError("no market data loaded")
    candidates = build_scheduler_candidates()
    if args.candidate_id:
        selected_ids = set(args.candidate_id)
        candidates = tuple(candidate for candidate in candidates if candidate.candidate_id in selected_ids)
    if args.train_test:
        payload = run_train_test_search(market, candidates)
    elif args.mode == "single":
        result = run_scheduler_driven_backtest(
            market,
            start_at=period.start_at,
            end_at=period.end_at,
            candidate=default_candidate(),
        )
        payload = {"results": [result], "result_count": 1}
    else:
        results = [
            run_scheduler_driven_backtest(
                market,
                start_at=period.start_at,
                end_at=period.end_at,
                candidate=candidate,
            )
            for candidate in candidates
        ]
        payload = {"results": rank_scheduler_results(results), "result_count": len(results)}
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    SUMMARY_PATH.write_text(markdown_summary(payload, limit=args.limit), encoding="utf-8")
    print(f"RESULTS {RESULTS_PATH}")
    print(f"SUMMARY {SUMMARY_PATH}")


def run_scheduler_driven_backtest(
    market: MarketSnapshot,
    *,
    start_at: datetime,
    end_at: datetime,
    candidate: SchedulerBacktestCandidate | None = None,
) -> dict[str, object]:
    candidate = candidate or default_candidate()
    selected = MarketSnapshot(tuple(candle for candle in market.candles if start_at <= candle.opened_at < end_at))
    market_data = CursorMarketData(selected)
    signal_log = InMemorySignalLogRepository()
    order_execution = BacktestOrderExecution(market_data)
    strategy = RegimeRouterScalperStrategy(**candidate.strategy_params)
    signal_generator = GuardedSignalGenerator(
        inner=CompositeSignalGenerator((strategy,)),
        config=candidate.guard,
    )
    guard = DefensiveGuard(candidate.guard)
    scheduler = TradeScheduler(
        execute_trade_usecase=ExecuteTradeUseCase(
            market_data=market_data,
            signal_generator=signal_generator,
            signal_log_repository=signal_log,
            order_execution=order_execution,
            position_sizing_strategy=SchedulerBacktestSizing(
                equity_ratio=candidate.equity_ratio,
                leverage=candidate.leverage,
            ),
            take_profit_stop_loss_strategy=SchedulerBacktestFixedTpSl(
                take_profit_ratio=candidate.take_profit_ratio,
                stop_loss_ratio=candidate.stop_loss_ratio,
            ),
        ),
        close_position_usecase=ClosePositionUseCase(order_execution),
        sync_position_usecase=SyncPositionUseCase(order_execution),
        manage_open_position_usecase=ManageOpenPositionUseCase(
            market_data=market_data,
            signal_generator=signal_generator,
            signal_log_repository=signal_log,
            close_position_usecase=ClosePositionUseCase(order_execution),
        ),
    )
    equity = INITIAL_EQUITY
    peak = equity
    max_drawdown = Decimal("0")
    open_position: BacktestPosition | None = None
    trades: list[BacktestTrade] = []
    skipped_by_guard = 0
    start_index = min(CANDLE_LIMIT - 1, len(selected.candles) - 1)
    for index in range(start_index, len(selected.candles)):
        market_data.cursor = index
        if open_position is not None:
            closed = maybe_close_position(open_position, selected, index)
            if closed is not None:
                trades.append(closed)
                equity += closed.net_pnl
                peak = max(peak, equity)
                if peak > Decimal("0"):
                    max_drawdown = max(max_drawdown, (peak - equity) / peak)
                open_position = None
                guard.record_trade(index=index, closed_trade=closed, equity=equity)
            continue

        if not guard.allows_entry(index=index, equity=equity):
            skipped_by_guard += 1
            continue
        signal_id = f"scheduler-bt-{index:08d}"
        execution = scheduler.run_trade_execution(
            schedule_name="scheduler-driven-backtest",
            command_factory=lambda signal_id=signal_id, equity=equity: execute_command(signal_id, selected, index, equity),
        )
        if execution.error is not None:
            raise execution.error
        if execution.result is None or execution.result.order_result is None:
            continue
        entry = execution.result.order_result
        levels = execution.result.take_profit_stop_loss
        if levels is None or entry.average_price is None or entry.executed_quantity is None:
            continue
        open_position = BacktestPosition(
            direction=execution.result.generated_signal.signal.direction,
            entry_price=entry.average_price,
            quantity=entry.executed_quantity,
            take_profit=levels.take_profit,
            stop_loss=levels.stop_loss,
            opened_index=index,
            entry_fee=entry.average_price * entry.executed_quantity * FEE_RATE,
        )
        guard.record_entry(index=index)

    if open_position is not None:
        final_price = _exit_fill_price(selected.candles[-1].close_price, open_position.direction)
        trades.append(close_trade(open_position, final_price, "end_of_data", len(selected.candles) - 1))
        equity += trades[-1].net_pnl

    days = Decimal(str((end_at - start_at).total_seconds())) / Decimal("86400")
    wins = sum(1 for trade in trades if trade.net_pnl > Decimal("0"))
    gross_pnl = sum((trade.gross_pnl for trade in trades), Decimal("0"))
    net_pnl = sum((trade.net_pnl for trade in trades), Decimal("0"))
    fee_paid = sum((trade.fee_paid for trade in trades), Decimal("0"))
    average_net_roe = (
        sum((trade.net_pnl / (trade.entry_price * trade.quantity / Decimal("6.08")) for trade in trades), Decimal("0"))
        / Decimal(len(trades))
        if trades
        else Decimal("0")
    )
    return {
        "engine": "scheduler_driven",
        "candidate_id": candidate.candidate_id,
        "scheduler_path": "TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute",
        "cost_model": {
            "venue": "binance_usd_m_futures",
            "fee_rate_per_side": str(FEE_RATE),
            "slippage_rate_per_side": str(SLIPPAGE_RATE),
            "funding_fee": "excluded",
        },
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "trade_count": len(trades),
        "trades_per_day": str(Decimal(len(trades)) / days if days else Decimal("0")),
        "daily_return_ratio": str((net_pnl / INITIAL_EQUITY) / days if days else Decimal("0")),
        "net_win_rate": str(Decimal(wins) / Decimal(len(trades)) if trades else Decimal("0")),
        "return_ratio": str(net_pnl / INITIAL_EQUITY),
        "gross_pnl": str(gross_pnl),
        "net_pnl": str(net_pnl),
        "fee_paid": str(fee_paid),
        "max_drawdown_ratio": str(max_drawdown),
        "average_net_trade_roe": str(average_net_roe),
        "signal_count": len(signal_log.entries),
        "skipped_by_guard": skipped_by_guard,
        "candidate": candidate_payload(candidate),
    }


def run_train_test_search(
    market: MarketSnapshot,
    candidates: tuple[SchedulerBacktestCandidate, ...],
) -> dict[str, object]:
    rows = []
    for candidate in candidates:
        train = run_scheduler_driven_backtest(
            market,
            start_at=TRAIN_START,
            end_at=TRAIN_END,
            candidate=candidate,
        )
        test = run_scheduler_driven_backtest(
            market,
            start_at=TEST_START,
            end_at=TEST_END,
            candidate=candidate,
        )
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "candidate": candidate_payload(candidate),
                **{f"train_{key}": value for key, value in train.items() if key != "candidate"},
                **{f"test_{key}": value for key, value in test.items() if key != "candidate"},
            }
        )
    return {
        "mode": "train_test",
        "train_period": {"start_at": TRAIN_START.isoformat(), "end_at": TRAIN_END.isoformat()},
        "test_period": {"start_at": TEST_START.isoformat(), "end_at": TEST_END.isoformat()},
        "result_count": len(rows),
        "results": rank_train_test_results(rows),
    }


class SchedulerBacktestSizing:
    def __init__(self, *, equity_ratio: Decimal, leverage: Decimal) -> None:
        self.equity_ratio = equity_ratio
        self.leverage = leverage

    def decide(self, *, decision, exposure_limit):
        from src.domain.risk import PositionSizingDecision

        return PositionSizingDecision(equity_ratio=self.equity_ratio, leverage=self.leverage)


class SchedulerBacktestFixedTpSl:
    name = "scheduler-backtest-fixed-tp-sl"

    def __init__(self, *, take_profit_ratio: Decimal, stop_loss_ratio: Decimal) -> None:
        self.take_profit_ratio = take_profit_ratio
        self.stop_loss_ratio = stop_loss_ratio

    def calculate(self, context, direction):
        from src.domain.strategy import TakeProfitStopLossLevels

        entry = context.market.latest_candle.close_price
        if direction is SignalDirection.LONG:
            take_profit = entry * (Decimal("1") + self.take_profit_ratio)
            stop_loss = entry * (Decimal("1") - self.stop_loss_ratio)
        else:
            take_profit = entry * (Decimal("1") - self.take_profit_ratio)
            stop_loss = entry * (Decimal("1") + self.stop_loss_ratio)
        return TakeProfitStopLossLevels(
            strategy_name=self.name,
            entry_price=entry,
            take_profit=take_profit,
            stop_loss=stop_loss,
        )


class DefensiveGuard:
    def __init__(self, config: DefensiveGuardConfig) -> None:
        self.config = config
        self.last_entry_index: int | None = None
        self.pause_until_index = -1
        self.consecutive_losses = 0
        self.daily_trade_count = 0
        self.daily_start_index = 0
        self.daily_start_equity = INITIAL_EQUITY
        self.peak_equity = INITIAL_EQUITY

    def allows_entry(self, *, index: int, equity: Decimal) -> bool:
        if index - self.daily_start_index >= 1440:
            self.daily_start_index = index
            self.daily_start_equity = equity
            self.daily_trade_count = 0
            self.consecutive_losses = 0
        self.peak_equity = max(self.peak_equity, equity)
        if index < self.pause_until_index:
            return False
        if self.last_entry_index is not None and index - self.last_entry_index < self.config.min_minutes_between_entries:
            return False
        if self.daily_trade_count >= self.config.max_daily_trades:
            return False
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            return False
        if self.peak_equity > Decimal("0"):
            peak_drawdown = (self.peak_equity - equity) / self.peak_equity
            if peak_drawdown >= self.config.max_peak_drawdown_ratio:
                return False
        if self.daily_start_equity > Decimal("0"):
            daily_return = (equity - self.daily_start_equity) / self.daily_start_equity
            if daily_return <= -self.config.max_daily_loss_ratio:
                return False
        return True

    def record_entry(self, *, index: int) -> None:
        self.last_entry_index = index
        self.daily_trade_count += 1

    def record_trade(self, *, index: int, closed_trade: BacktestTrade, equity: Decimal) -> None:
        if closed_trade.net_pnl < Decimal("0"):
            self.consecutive_losses += 1
            if self.config.pause_minutes_after_loss:
                self.pause_until_index = index + self.config.pause_minutes_after_loss
        else:
            self.consecutive_losses = 0
        if index - self.daily_start_index >= 1440:
            self.daily_start_index = index
            self.daily_start_equity = equity
            self.daily_trade_count = 0


class GuardedSignalGenerator:
    def __init__(self, *, inner, config: DefensiveGuardConfig) -> None:
        self.inner = inner
        self.config = config

    def generate(self, context) -> GeneratedSignal:
        generated = self.inner.generate(context)
        if generated.signal.direction is SignalDirection.WAIT:
            return generated
        if generated.signal.confidence < self.config.min_signal_confidence:
            return GeneratedSignal(signal=Signal.wait(), strategy_results=generated.strategy_results)
        latest = context.market.latest_candle
        if latest.close_price > Decimal("0"):
            range_ratio = (latest.high_price - latest.low_price) / latest.close_price
            if range_ratio < self.config.min_1m_range_ratio:
                return GeneratedSignal(signal=Signal.wait(), strategy_results=generated.strategy_results)
            if range_ratio > self.config.max_1m_range_ratio:
                return GeneratedSignal(signal=Signal.wait(), strategy_results=generated.strategy_results)
        return generated


def build_scheduler_candidates() -> tuple[SchedulerBacktestCandidate, ...]:
    strategies = {
        "balanced": base_strategy_params(),
        "quality-balanced": {
            "trend_params": {
                "trend_period": 75,
                "pullback_period": 6,
                "trigger_period": 1,
                "min_trend_return": Decimal("0.0028"),
                "min_pullback": Decimal("0.0008"),
                "min_trigger_return": Decimal("0.00025"),
                "min_range_ratio": Decimal("0.0010"),
            },
            "range_params": {
                "range_period": 60,
                "edge_ratio": Decimal("0.16"),
                "min_reversal_body_ratio": Decimal("0.18"),
                "min_range_ratio": Decimal("0.0018"),
            },
            "burst_params": {
                "breakout_period": 14,
                "impulse_period": 1,
                "volume_period": 24,
                "min_impulse_return": Decimal("0.0010"),
                "min_volume_ratio": Decimal("1.10"),
                "breakout_buffer": Decimal("0.0003"),
                "mode": "fade",
            },
            "router_order": ("trend", "burst", "range"),
            "max_abs_trend_for_range": Decimal("0.0065"),
            "range_regime_period": 300,
            "trend_regime_period": 300,
        },
        "range-first": {
            "trend_params": {
                "trend_period": 90,
                "pullback_period": 7,
                "trigger_period": 2,
                "min_trend_return": Decimal("0.0035"),
                "min_pullback": Decimal("0.0010"),
                "min_trigger_return": Decimal("0.00035"),
                "min_range_ratio": Decimal("0.0012"),
            },
            "range_params": {
                "range_period": 75,
                "edge_ratio": Decimal("0.14"),
                "min_reversal_body_ratio": Decimal("0.22"),
                "min_range_ratio": Decimal("0.0025"),
            },
            "burst_params": {
                "breakout_period": 18,
                "impulse_period": 2,
                "volume_period": 30,
                "min_impulse_return": Decimal("0.0015"),
                "min_volume_ratio": Decimal("1.20"),
                "breakout_buffer": Decimal("0.0004"),
                "mode": "fade",
            },
            "router_order": ("range", "trend", "burst"),
            "max_abs_trend_for_range": Decimal("0.0045"),
            "range_regime_period": 360,
            "trend_regime_period": 360,
        },
        "burst-exhaustion": {
            "trend_params": {
                "trend_period": 80,
                "pullback_period": 6,
                "trigger_period": 2,
                "min_trend_return": Decimal("0.0032"),
                "min_pullback": Decimal("0.0009"),
                "min_trigger_return": Decimal("0.00030"),
                "min_range_ratio": Decimal("0.0010"),
            },
            "range_params": {
                "range_period": 50,
                "edge_ratio": Decimal("0.15"),
                "min_reversal_body_ratio": Decimal("0.20"),
                "min_range_ratio": Decimal("0.0020"),
            },
            "burst_params": {
                "breakout_period": 18,
                "impulse_period": 2,
                "volume_period": 30,
                "min_impulse_return": Decimal("0.0018"),
                "min_volume_ratio": Decimal("1.25"),
                "breakout_buffer": Decimal("0.0008"),
                "mode": "fade",
            },
            "router_order": ("burst", "trend", "range"),
            "max_abs_trend_for_range": Decimal("0.0050"),
            "range_regime_period": 300,
            "trend_regime_period": 300,
        },
        "ultra-selective": {
            "trend_params": {
                "trend_period": 120,
                "pullback_period": 8,
                "trigger_period": 2,
                "min_trend_return": Decimal("0.0045"),
                "min_pullback": Decimal("0.0012"),
                "min_trigger_return": Decimal("0.00050"),
                "min_range_ratio": Decimal("0.0015"),
            },
            "range_params": {
                "range_period": 90,
                "edge_ratio": Decimal("0.12"),
                "min_reversal_body_ratio": Decimal("0.25"),
                "min_range_ratio": Decimal("0.0030"),
            },
            "burst_params": {
                "breakout_period": 24,
                "impulse_period": 2,
                "volume_period": 36,
                "min_impulse_return": Decimal("0.0025"),
                "min_volume_ratio": Decimal("1.35"),
                "breakout_buffer": Decimal("0.0010"),
                "mode": "fade",
            },
            "router_order": ("trend", "burst", "range"),
            "max_abs_trend_for_range": Decimal("0.0040"),
            "range_regime_period": 420,
            "trend_regime_period": 420,
        },
        "selective-trend": _merged_strategy_params(
            trend={"min_trend_return": Decimal("0.003"), "min_pullback": Decimal("0.0008")},
            burst={"min_volume_ratio": Decimal("1.2")},
            max_abs_trend_for_range=Decimal("0.006"),
        ),
        "liquid-burst": _merged_strategy_params(
            trend={"min_range_ratio": Decimal("0.0012")},
            burst={"min_impulse_return": Decimal("0.0010"), "min_volume_ratio": Decimal("1.3")},
            range_params={"min_reversal_body_ratio": Decimal("0.18")},
        ),
        "range-strict": _merged_strategy_params(
            range_params={"edge_ratio": Decimal("0.14"), "min_range_ratio": Decimal("0.0020")},
            max_abs_trend_for_range=Decimal("0.005"),
        ),
    }
    exit_sizing_profiles = (
        ("p1-tp0075-sl0050-e0040-l4", Decimal("0.0075"), Decimal("0.0050"), Decimal("0.040"), Decimal("4")),
        ("p2-tp0060-sl0045-e0035-l3", Decimal("0.0060"), Decimal("0.0045"), Decimal("0.035"), Decimal("3")),
        ("p3-tp0090-sl0060-e0045-l4", Decimal("0.0090"), Decimal("0.0060"), Decimal("0.045"), Decimal("4")),
        ("p4-tp0105-sl0070-e0050-l5", Decimal("0.0105"), Decimal("0.0070"), Decimal("0.050"), Decimal("5")),
    )
    guards = (
        ("guard-a", DefensiveGuardConfig(
            min_minutes_between_entries=60,
            pause_minutes_after_loss=90,
            max_daily_loss_ratio=Decimal("0.006"),
            max_daily_trades=12,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.08"),
            min_signal_confidence=Decimal("0.68"),
            min_1m_range_ratio=Decimal("0.0006"),
            max_1m_range_ratio=Decimal("0.0060"),
        )),
        ("guard-b", DefensiveGuardConfig(
            min_minutes_between_entries=90,
            pause_minutes_after_loss=180,
            max_daily_loss_ratio=Decimal("0.004"),
            max_daily_trades=8,
            max_consecutive_losses=1,
            max_peak_drawdown_ratio=Decimal("0.05"),
            min_signal_confidence=Decimal("0.70"),
            min_1m_range_ratio=Decimal("0.0008"),
            max_1m_range_ratio=Decimal("0.0040"),
        )),
        ("guard-c", DefensiveGuardConfig(
            min_minutes_between_entries=20,
            pause_minutes_after_loss=45,
            max_daily_loss_ratio=Decimal("0.006"),
            max_daily_trades=15,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.08"),
            min_signal_confidence=Decimal("0.64"),
            min_1m_range_ratio=Decimal("0.0004"),
            max_1m_range_ratio=Decimal("0.0075"),
        )),
        ("guard-d", DefensiveGuardConfig(
            min_minutes_between_entries=30,
            pause_minutes_after_loss=60,
            max_daily_loss_ratio=Decimal("0.005"),
            max_daily_trades=12,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.06"),
            min_signal_confidence=Decimal("0.64"),
            min_1m_range_ratio=Decimal("0.0005"),
            max_1m_range_ratio=Decimal("0.0065"),
        )),
        ("guard-e", DefensiveGuardConfig(
            min_minutes_between_entries=10,
            pause_minutes_after_loss=30,
            max_daily_loss_ratio=Decimal("0.006"),
            max_daily_trades=15,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.08"),
            min_signal_confidence=Decimal("0.64"),
            min_1m_range_ratio=Decimal("0.0003"),
            max_1m_range_ratio=Decimal("0.0080"),
        )),
    )
    candidates = []
    for strategy_name, strategy_params in strategies.items():
        for profile_name, tp, sl, equity_ratio, leverage in exit_sizing_profiles:
            for guard_name, guard in guards:
                candidates.append(
                    SchedulerBacktestCandidate(
                        candidate_id=f"{strategy_name}-{profile_name}-{guard_name}",
                        strategy_params=strategy_params,
                        take_profit_ratio=tp,
                        stop_loss_ratio=sl,
                        equity_ratio=equity_ratio,
                        leverage=leverage,
                        guard=guard,
                    )
                )
    return tuple(candidates)


def default_candidate() -> SchedulerBacktestCandidate:
    return SchedulerBacktestCandidate(
        candidate_id="balanced-tp012-sl010-balanced-guard-a",
        strategy_params=base_strategy_params(),
        take_profit_ratio=Decimal("0.012"),
        stop_loss_ratio=Decimal("0.010"),
        equity_ratio=Decimal("0.050"),
        leverage=Decimal("4"),
        guard=DefensiveGuardConfig(
            min_minutes_between_entries=60,
            pause_minutes_after_loss=90,
            max_daily_loss_ratio=Decimal("0.006"),
            max_daily_trades=12,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.08"),
            min_signal_confidence=Decimal("0.68"),
            min_1m_range_ratio=Decimal("0.0006"),
            max_1m_range_ratio=Decimal("0.0060"),
        ),
    )


def selected_strategy() -> RegimeRouterScalperStrategy:
    return RegimeRouterScalperStrategy(**base_strategy_params())


def base_strategy_params() -> dict[str, object]:
    return {
        "trend_params": {
            "trend_period": 60,
            "pullback_period": 5,
            "trigger_period": 1,
            "min_trend_return": Decimal("0.002"),
            "min_pullback": Decimal("0.0006"),
            "min_trigger_return": Decimal("0.0002"),
            "min_range_ratio": Decimal("0.0008"),
        },
        "range_params": {
            "range_period": 45,
            "edge_ratio": Decimal("0.18"),
            "min_reversal_body_ratio": Decimal("0.15"),
            "min_range_ratio": Decimal("0.0015"),
        },
        "burst_params": {
            "breakout_period": 12,
            "impulse_period": 1,
            "volume_period": 20,
            "min_impulse_return": Decimal("0.0008"),
            "min_volume_ratio": Decimal("1.0"),
            "breakout_buffer": Decimal("0.0000"),
            "mode": "fade",
        },
        "router_order": ("trend", "burst", "range"),
        "max_abs_trend_for_range": Decimal("0.008"),
        "range_regime_period": 240,
        "trend_regime_period": 240,
    }


def _merged_strategy_params(
    *,
    trend: dict[str, object] | None = None,
    range_params: dict[str, object] | None = None,
    burst: dict[str, object] | None = None,
    max_abs_trend_for_range: Decimal | None = None,
) -> dict[str, object]:
    params = base_strategy_params()
    params["trend_params"] = {**params["trend_params"], **(trend or {})}
    params["range_params"] = {**params["range_params"], **(range_params or {})}
    params["burst_params"] = {**params["burst_params"], **(burst or {})}
    if max_abs_trend_for_range is not None:
        params["max_abs_trend_for_range"] = max_abs_trend_for_range
    return params


def execute_command(signal_id: str, market: MarketSnapshot, index: int, equity: Decimal) -> ExecuteTradeCommand:
    latest = market.candles[index]
    return ExecuteTradeCommand(
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        candle_limit=CANDLE_LIMIT,
        indicators=IndicatorSet(symbol=SYMBOL, timeframe=TIMEFRAME, measured_at=latest.closed_at, values=()),
        exposure_limit=ExposureLimit(
            equity=equity,
            current_total_exposure=Decimal("0"),
            current_symbol_exposure=Decimal("0"),
            max_total_exposure_ratio=Decimal("1"),
            max_symbol_exposure_ratio=Decimal("1"),
        ),
        base_risk_ratio=Decimal("0.02"),
        leverage=Decimal("2"),
        client_order_id_prefix="scheduler-bt",
        signal_id=signal_id,
        generator_id=GENERATOR_ID,
    )


def maybe_close_position(
    position: BacktestPosition,
    market: MarketSnapshot,
    index: int,
) -> BacktestTrade | None:
    candle = market.candles[index]
    if position.direction is SignalDirection.LONG:
        if candle.low_price <= position.stop_loss:
            return close_trade(position, _exit_fill_price(position.stop_loss, position.direction), "stop_loss", index)
        if candle.high_price >= position.take_profit:
            return close_trade(position, _exit_fill_price(position.take_profit, position.direction), "take_profit", index)
    else:
        if candle.high_price >= position.stop_loss:
            return close_trade(position, _exit_fill_price(position.stop_loss, position.direction), "stop_loss", index)
        if candle.low_price <= position.take_profit:
            return close_trade(position, _exit_fill_price(position.take_profit, position.direction), "take_profit", index)
    return None


def close_trade(position: BacktestPosition, exit_price: Decimal, reason: str, index: int) -> BacktestTrade:
    if position.direction is SignalDirection.LONG:
        gross_pnl = (exit_price - position.entry_price) * position.quantity
    else:
        gross_pnl = (position.entry_price - exit_price) * position.quantity
    exit_fee = exit_price * position.quantity * FEE_RATE
    fee_paid = position.entry_fee + exit_fee
    return BacktestTrade(
        entry_price=position.entry_price,
        exit_price=exit_price,
        direction=position.direction,
        quantity=position.quantity,
        gross_pnl=gross_pnl,
        net_pnl=gross_pnl - fee_paid,
        fee_paid=fee_paid,
        exit_reason=reason,
        holding_bars=index - position.opened_index,
    )


def _entry_fill_price(price: Decimal, direction: SignalDirection) -> Decimal:
    if direction is SignalDirection.LONG:
        return price * (Decimal("1") + SLIPPAGE_RATE)
    return price * (Decimal("1") - SLIPPAGE_RATE)


def _exit_fill_price(price: Decimal, direction: SignalDirection) -> Decimal:
    if direction is SignalDirection.LONG:
        return price * (Decimal("1") - SLIPPAGE_RATE)
    return price * (Decimal("1") + SLIPPAGE_RATE)


def rank_scheduler_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        results,
        key=lambda result: (
            Decimal(str(result["trades_per_day"])) >= Decimal("5"),
            Decimal(str(result["trades_per_day"])) <= Decimal("15"),
            Decimal(str(result["net_win_rate"])) >= Decimal("0.60"),
            Decimal(str(result["daily_return_ratio"])),
            Decimal(str(result["return_ratio"])),
            -Decimal(str(result["max_drawdown_ratio"])),
        ),
        reverse=True,
    )


def rank_train_test_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        results,
        key=lambda result: (
            Decimal(str(result["test_trades_per_day"])) >= Decimal("5"),
            Decimal(str(result["test_trades_per_day"])) <= Decimal("15"),
            Decimal(str(result["test_net_win_rate"])) >= Decimal("0.60"),
            Decimal(str(result["train_return_ratio"])) > Decimal("0"),
            Decimal(str(result["test_return_ratio"])) > Decimal("0"),
            Decimal(str(result["test_daily_return_ratio"])),
            Decimal(str(result["train_daily_return_ratio"])),
            -Decimal(str(result["test_max_drawdown_ratio"])),
        ),
        reverse=True,
    )


def candidate_payload(candidate: SchedulerBacktestCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "take_profit_ratio": str(candidate.take_profit_ratio),
        "stop_loss_ratio": str(candidate.stop_loss_ratio),
        "equity_ratio": str(candidate.equity_ratio),
        "leverage": str(candidate.leverage),
        "guard": {
            "min_minutes_between_entries": candidate.guard.min_minutes_between_entries,
            "pause_minutes_after_loss": candidate.guard.pause_minutes_after_loss,
            "max_daily_loss_ratio": str(candidate.guard.max_daily_loss_ratio),
            "max_daily_trades": candidate.guard.max_daily_trades,
            "max_consecutive_losses": candidate.guard.max_consecutive_losses,
            "max_peak_drawdown_ratio": str(candidate.guard.max_peak_drawdown_ratio),
            "min_signal_confidence": str(candidate.guard.min_signal_confidence),
            "min_1m_range_ratio": str(candidate.guard.min_1m_range_ratio),
            "max_1m_range_ratio": str(candidate.guard.max_1m_range_ratio),
        },
        "strategy_params": _stringify(candidate.strategy_params),
    }


def _stringify(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _stringify(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_stringify(item) for item in value)
    return value


def _label_date(value: str) -> str:
    return value.replace("/", "-")


def markdown_summary(payload: dict[str, object], *, limit: int = 20) -> str:
    results = payload["results"]
    if payload.get("mode") == "train_test":
        return "\n".join(
            [
                "# Scheduler Driven Scalping Train/Test Search",
                "",
                "Engine: scheduler_driven",
                "Scheduler path: TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute",
                "",
                f"Train: {payload['train_period']['start_at']} ~ {payload['train_period']['end_at']}",
                f"Test: {payload['test_period']['start_at']} ~ {payload['test_period']['end_at']}",
                "",
                "| Rank | Candidate | Train Ret | Test Ret | Test Daily | Test MDD | Test Trades/day | Test Win |",
                "|---:|---|---:|---:|---:|---:|---:|---:|",
                *(
                    "| {rank} | {candidate_id} | {train_return_ratio} | {test_return_ratio} | {test_daily_return_ratio} | {test_max_drawdown_ratio} | {test_trades_per_day} | {test_net_win_rate} |".format(
                        rank=index,
                        **result,
                    )
                    for index, result in enumerate(results[:limit], start=1)
                ),
                "",
            ]
        )
    if len(results) == 1:
        result = results[0]
        return "\n".join(
            [
                "# Scheduler Driven Scalping Backtest",
                "",
                f"Engine: {result['engine']}",
                f"Scheduler path: {result['scheduler_path']}",
                "",
                "| Candidate | Return | Daily | MDD | Trades | Trades/day | Avg net ROE | Net win |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
                "| {candidate_id} | {return_ratio} | {daily_return_ratio} | {max_drawdown_ratio} | {trade_count} | {trades_per_day} | {average_net_trade_roe} | {net_win_rate} |".format(
                    **result
                ),
                "",
            ]
        )
    return "\n".join(
        [
            "# Scheduler Driven Scalping Backtest",
            "",
            "Engine: scheduler_driven",
            "Scheduler path: TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute",
            "",
            "| Rank | Candidate | Return | Daily | MDD | Trades | Trades/day | Avg net ROE | Net win | Guard skips |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            *(
                "| {rank} | {candidate_id} | {return_ratio} | {daily_return_ratio} | {max_drawdown_ratio} | {trade_count} | {trades_per_day} | {average_net_trade_roe} | {net_win_rate} | {skipped_by_guard} |".format(
                    rank=index,
                    **result,
                )
                for index, result in enumerate(results[:limit], start=1)
            ),
            "",
        ]
    )


if __name__ == "__main__":
    main()
