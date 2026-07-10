from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
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
from src.domain.signal import SignalDirection  # noqa: E402
from src.domain.signal_generator import CompositeSignalGenerator  # noqa: E402
from src.domain.strategy.implementations.regime_router_scalper_strategy import (  # noqa: E402
    RegimeRouterScalperStrategy,
)
from src.interfaces.scheduler import TradeScheduler  # noqa: E402


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")
GENERATOR_ID = "scheduler-driven-live-scalp-multi-t1-r1-b4-tbr"
CANDLE_LIMIT = 262
INITIAL_EQUITY = Decimal("10000")
FEE_RATE = Decimal("0.0004")
SLIPPAGE_RATE = Decimal("0.0002")
RESULTS_PATH = Path("docs/backtests/scheduler-driven-scalping-backtest.json")
SUMMARY_PATH = Path("docs/backtests/scheduler-driven-scalping-backtest.md")


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025/11/9")
    parser.add_argument("--end", default="2026/7/8")
    args = parser.parse_args()

    period = PeriodSpec("BTCUSDT", "scheduler-driven", args.start, args.end)
    market = load_period_market(period)
    if market is None:
        raise RuntimeError("no market data loaded")
    result = run_scheduler_driven_backtest(market, start_at=period.start_at, end_at=period.end_at)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    SUMMARY_PATH.write_text(markdown_summary(result), encoding="utf-8")
    print(f"RESULTS {RESULTS_PATH}")
    print(f"SUMMARY {SUMMARY_PATH}")


def run_scheduler_driven_backtest(
    market: MarketSnapshot,
    *,
    start_at: datetime,
    end_at: datetime,
) -> dict[str, object]:
    selected = MarketSnapshot(tuple(candle for candle in market.candles if start_at <= candle.opened_at < end_at))
    market_data = CursorMarketData(selected)
    signal_log = InMemorySignalLogRepository()
    order_execution = BacktestOrderExecution(market_data)
    scheduler = TradeScheduler(
        execute_trade_usecase=ExecuteTradeUseCase(
            market_data=market_data,
            signal_generator=CompositeSignalGenerator((selected_strategy(),)),
            signal_log_repository=signal_log,
            order_execution=order_execution,
            position_sizing_strategy=SchedulerBacktestSizing(),
            take_profit_stop_loss_strategy=SchedulerBacktestFixedTpSl(),
        ),
        close_position_usecase=ClosePositionUseCase(order_execution),
        sync_position_usecase=SyncPositionUseCase(order_execution),
        manage_open_position_usecase=ManageOpenPositionUseCase(
            market_data=market_data,
            signal_generator=CompositeSignalGenerator((selected_strategy(),)),
            signal_log_repository=signal_log,
            close_position_usecase=ClosePositionUseCase(order_execution),
        ),
    )
    equity = INITIAL_EQUITY
    peak = equity
    max_drawdown = Decimal("0")
    open_position: BacktestPosition | None = None
    trades: list[BacktestTrade] = []
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
        "net_win_rate": str(Decimal(wins) / Decimal(len(trades)) if trades else Decimal("0")),
        "return_ratio": str(net_pnl / INITIAL_EQUITY),
        "gross_pnl": str(gross_pnl),
        "net_pnl": str(net_pnl),
        "fee_paid": str(fee_paid),
        "max_drawdown_ratio": str(max_drawdown),
        "average_net_trade_roe": str(average_net_roe),
        "signal_count": len(signal_log.entries),
    }


class SchedulerBacktestSizing:
    def decide(self, *, decision, exposure_limit):
        from src.domain.risk import PositionSizingDecision

        return PositionSizingDecision(equity_ratio=Decimal("0.088"), leverage=Decimal("6.08"))


class SchedulerBacktestFixedTpSl:
    name = "scheduler-backtest-fixed-tp-sl"

    def calculate(self, context, direction):
        from src.domain.strategy import TakeProfitStopLossLevels

        entry = context.market.latest_candle.close_price
        if direction is SignalDirection.LONG:
            take_profit = entry * Decimal("1.012")
            stop_loss = entry * Decimal("0.990")
        else:
            take_profit = entry * Decimal("0.988")
            stop_loss = entry * Decimal("1.010")
        return TakeProfitStopLossLevels(
            strategy_name=self.name,
            entry_price=entry,
            take_profit=take_profit,
            stop_loss=stop_loss,
        )


def selected_strategy() -> RegimeRouterScalperStrategy:
    return RegimeRouterScalperStrategy(
        trend_params={
            "trend_period": 60,
            "pullback_period": 5,
            "trigger_period": 1,
            "min_trend_return": Decimal("0.002"),
            "min_pullback": Decimal("0.0006"),
            "min_trigger_return": Decimal("0.0002"),
            "min_range_ratio": Decimal("0.0008"),
        },
        range_params={
            "range_period": 45,
            "edge_ratio": Decimal("0.18"),
            "min_reversal_body_ratio": Decimal("0.15"),
            "min_range_ratio": Decimal("0.0015"),
        },
        burst_params={
            "breakout_period": 12,
            "impulse_period": 1,
            "volume_period": 20,
            "min_impulse_return": Decimal("0.0008"),
            "min_volume_ratio": Decimal("1.0"),
            "breakout_buffer": Decimal("0.0000"),
            "mode": "fade",
        },
        router_order=("trend", "burst", "range"),
        max_abs_trend_for_range=Decimal("0.008"),
        range_regime_period=240,
        trend_regime_period=240,
    )


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


def markdown_summary(result: dict[str, object]) -> str:
    return "\n".join(
        [
            "# Scheduler Driven Scalping Backtest",
            "",
            f"Engine: {result['engine']}",
            f"Scheduler path: {result['scheduler_path']}",
            "",
            "| Return | MDD | Trades | Trades/day | Avg net ROE | Net win |",
            "|---:|---:|---:|---:|---:|---:|",
            "| {return_ratio} | {max_drawdown_ratio} | {trade_count} | {trades_per_day} | {average_net_trade_roe} | {net_win_rate} |".format(
                **result
            ),
            "",
        ]
    )


if __name__ == "__main__":
    main()
