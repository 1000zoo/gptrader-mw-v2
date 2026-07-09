from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from src.application.usecases.research.dto import (
    BacktestPerformance,
    BacktestStrategyCommand,
    BacktestTrade,
)
from src.domain.indicator import IndicatorSet
from src.domain.market import Candle, MarketSnapshot
from src.domain.risk import FixedPositionSizingStrategy, PositionSizingStrategy
from src.domain.signal import SignalDirection
from src.domain.signal.trade_decision import TradeDecision, TradeDecisionAction
from src.domain.strategy import Strategy, StrategyContext, StrategyResult
from src.domain.strategy.take_profit_stop_loss import (
    TakeProfitStopLossLevels,
    TakeProfitStopLossStrategy,
)


BacktestIndicatorFactory = Callable[[MarketSnapshot], IndicatorSet]


@dataclass
class _OpenPosition:
    direction: SignalDirection
    entry_price: Decimal
    quantity: Decimal
    entry_time: object
    levels: TakeProfitStopLossLevels | None


@dataclass(frozen=True)
class BacktestSimulation:
    strategy_result: StrategyResult
    context: StrategyContext
    trades: tuple[BacktestTrade, ...]
    performance: BacktestPerformance


def simulate_backtest(
    *,
    command: BacktestStrategyCommand,
    market: MarketSnapshot,
    strategy: Strategy,
    indicator_factory: BacktestIndicatorFactory,
    take_profit_stop_loss_strategy: TakeProfitStopLossStrategy | None = None,
    position_sizing_strategy: PositionSizingStrategy | None = None,
) -> BacktestSimulation:
    equity = command.initial_equity
    peak_equity = equity
    max_drawdown_ratio = Decimal("0")
    trades: list[BacktestTrade] = []
    position: _OpenPosition | None = None
    latest_result: StrategyResult | None = None
    latest_context: StrategyContext | None = None

    for index, candle in enumerate(market.candles):
        exited_this_candle = False
        if position is not None and index > 0:
            exit_price, exit_reason = _exit_for_candle(position, candle)
            if exit_price is not None:
                trade = _close_trade(
                    position=position,
                    candle=candle,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    fee_rate=command.fee_rate,
                    slippage_rate=command.slippage_rate,
                )
                trades.append(trade)
                equity += trade.net_pnl
                peak_equity = max(peak_equity, equity)
                max_drawdown_ratio = max(
                    max_drawdown_ratio,
                    _drawdown_ratio(equity, peak_equity),
                )
                position = None
                exited_this_candle = True
            else:
                snapshot = _rolling_snapshot(market, index, command.candle_limit)
                indicators = indicator_factory(snapshot)
                context = StrategyContext(
                    market=snapshot,
                    indicators=indicators,
                    metadata=command.metadata,
                )
                try:
                    result = strategy.evaluate(context)
                except KeyError:
                    result = None
                if result is not None:
                    latest_result = result
                    latest_context = context
                    if _is_opposite_signal(position.direction, result.signal.direction):
                        trade = _close_trade(
                            position=position,
                            candle=candle,
                            exit_price=candle.close_price,
                            exit_reason="opposite_signal",
                            fee_rate=command.fee_rate,
                            slippage_rate=command.slippage_rate,
                        )
                        trades.append(trade)
                        equity += trade.net_pnl
                        peak_equity = max(peak_equity, equity)
                        max_drawdown_ratio = max(
                            max_drawdown_ratio,
                            _drawdown_ratio(equity, peak_equity),
                        )
                        position = None
                        exited_this_candle = True

        if position is not None or exited_this_candle:
            continue

        snapshot = _rolling_snapshot(market, index, command.candle_limit)
        indicators = indicator_factory(snapshot)
        context = StrategyContext(
            market=snapshot,
            indicators=indicators,
            metadata=command.metadata,
        )
        try:
            result = strategy.evaluate(context)
        except KeyError:
            continue
        latest_result = result
        latest_context = context

        if result.signal.direction is SignalDirection.WAIT:
            continue

        entry_price = _entry_price(
            candle.close_price,
            direction=result.signal.direction,
            slippage_rate=command.slippage_rate,
        )
        sizing_strategy = position_sizing_strategy or FixedPositionSizingStrategy(
            equity_ratio=command.risk_ratio,
            leverage=command.leverage,
        )
        sizing_decision = sizing_strategy.decide(
            decision=TradeDecision(
                action=_entry_action(result.signal.direction),
                signal=result.signal,
            ),
            exposure_limit=_backtest_exposure_limit(equity),
        )
        notional = (
            equity
            * sizing_decision.equity_ratio
            * sizing_decision.leverage
        )
        quantity = notional / entry_price
        levels = None
        if take_profit_stop_loss_strategy is not None:
            try:
                levels = take_profit_stop_loss_strategy.calculate(
                    context,
                    result.signal.direction,
                )
            except ValueError:
                continue
        else:
            levels = _levels_from_signal_metadata(
                result,
                context,
                result.signal.direction,
            )
        position = _OpenPosition(
            direction=result.signal.direction,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=candle.closed_at,
            levels=levels,
        )

    if latest_result is None or latest_context is None:
        snapshot = _rolling_snapshot(
            market,
            len(market.candles) - 1,
            command.candle_limit,
        )
        indicators = indicator_factory(snapshot)
        latest_context = StrategyContext(
            market=snapshot,
            indicators=indicators,
            metadata=command.metadata,
        )
        latest_result = strategy.evaluate(latest_context)

    if position is not None:
        final_candle = market.latest_candle
        trade = _close_trade(
            position=position,
            candle=final_candle,
            exit_price=final_candle.close_price,
            exit_reason="end_of_data",
            fee_rate=command.fee_rate,
            slippage_rate=command.slippage_rate,
        )
        trades.append(trade)
        equity += trade.net_pnl
        peak_equity = max(peak_equity, equity)
        max_drawdown_ratio = max(
            max_drawdown_ratio,
            _drawdown_ratio(equity, peak_equity),
        )

    return BacktestSimulation(
        strategy_result=latest_result,
        context=latest_context,
        trades=tuple(trades),
        performance=_performance(
            initial_equity=command.initial_equity,
            final_equity=equity,
            trades=tuple(trades),
            max_drawdown_ratio=max_drawdown_ratio,
        ),
    )


def _exit_for_candle(
    position: _OpenPosition,
    candle: Candle,
) -> tuple[Decimal | None, str | None]:
    if position.levels is None:
        return None, None

    if position.direction is SignalDirection.LONG:
        if candle.low_price <= position.levels.stop_loss:
            return position.levels.stop_loss, "stop_loss"
        if candle.high_price >= position.levels.take_profit:
            return position.levels.take_profit, "take_profit"
        return None, None

    if candle.high_price >= position.levels.stop_loss:
        return position.levels.stop_loss, "stop_loss"
    if candle.low_price <= position.levels.take_profit:
        return position.levels.take_profit, "take_profit"
    return None, None


def _rolling_snapshot(
    market: MarketSnapshot,
    index: int,
    candle_limit: int,
) -> MarketSnapshot:
    start = max(0, index + 1 - candle_limit)
    return MarketSnapshot(candles=market.candles[start : index + 1])


def _is_opposite_signal(
    position_direction: SignalDirection,
    signal_direction: SignalDirection,
) -> bool:
    return (
        position_direction is SignalDirection.LONG
        and signal_direction is SignalDirection.SHORT
    ) or (
        position_direction is SignalDirection.SHORT
        and signal_direction is SignalDirection.LONG
    )


def _entry_price(
    price: Decimal,
    *,
    direction: SignalDirection,
    slippage_rate: Decimal,
) -> Decimal:
    if direction is SignalDirection.LONG:
        return price * (Decimal("1") + slippage_rate)
    return price * (Decimal("1") - slippage_rate)


def _exit_with_slippage(
    price: Decimal,
    *,
    direction: SignalDirection,
    slippage_rate: Decimal,
) -> Decimal:
    if direction is SignalDirection.LONG:
        return price * (Decimal("1") - slippage_rate)
    return price * (Decimal("1") + slippage_rate)


def _close_trade(
    *,
    position: _OpenPosition,
    candle: Candle,
    exit_price: Decimal,
    exit_reason: str | None,
    fee_rate: Decimal,
    slippage_rate: Decimal,
) -> BacktestTrade:
    filled_exit_price = _exit_with_slippage(
        exit_price,
        direction=position.direction,
        slippage_rate=slippage_rate,
    )
    if position.direction is SignalDirection.LONG:
        gross_pnl = (filled_exit_price - position.entry_price) * position.quantity
    else:
        gross_pnl = (position.entry_price - filled_exit_price) * position.quantity

    fee_paid = (
        (position.entry_price * position.quantity)
        + (filled_exit_price * position.quantity)
    ) * fee_rate
    net_pnl = gross_pnl - fee_paid
    return BacktestTrade(
        direction=position.direction,
        entry_price=position.entry_price,
        exit_price=filled_exit_price,
        quantity=position.quantity,
        gross_pnl=gross_pnl,
        fee_paid=fee_paid,
        net_pnl=net_pnl,
        entry_time=position.entry_time,
        exit_time=candle.closed_at,
        exit_reason=exit_reason or "unknown",
    )


def _levels_from_signal_metadata(
    result: StrategyResult,
    context: StrategyContext,
    direction: SignalDirection,
) -> TakeProfitStopLossLevels | None:
    take_profit = _decimal_metadata(result.signal.metadata.get("take_profit"))
    stop_loss = _decimal_metadata(result.signal.metadata.get("stop_loss"))
    entry_price = _decimal_metadata(result.signal.metadata.get("entry_price"))
    if take_profit is None or stop_loss is None:
        return None
    return TakeProfitStopLossLevels(
        strategy_name=f"{result.name}-metadata",
        entry_price=entry_price or context.market.latest_candle.close_price,
        take_profit=take_profit,
        stop_loss=stop_loss,
    )


def _entry_action(direction: SignalDirection) -> TradeDecisionAction:
    if direction is SignalDirection.LONG:
        return TradeDecisionAction.ENTER_LONG
    if direction is SignalDirection.SHORT:
        return TradeDecisionAction.ENTER_SHORT
    return TradeDecisionAction.HOLD


def _backtest_exposure_limit(equity: Decimal):
    from src.domain.risk import ExposureLimit

    return ExposureLimit(
        equity=equity,
        current_total_exposure=Decimal("0"),
        current_symbol_exposure=Decimal("0"),
        max_total_exposure_ratio=Decimal("1000000"),
        max_symbol_exposure_ratio=Decimal("1000000"),
    )


def _decimal_metadata(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _performance(
    *,
    initial_equity: Decimal,
    final_equity: Decimal,
    trades: tuple[BacktestTrade, ...],
    max_drawdown_ratio: Decimal,
) -> BacktestPerformance:
    net_pnl = final_equity - initial_equity
    winning_trade_count = sum(1 for trade in trades if trade.net_pnl > Decimal("0"))
    losing_trade_count = sum(1 for trade in trades if trade.net_pnl < Decimal("0"))
    trade_count = len(trades)
    win_rate = (
        Decimal(winning_trade_count) / Decimal(trade_count)
        if trade_count
        else Decimal("0")
    )
    return BacktestPerformance(
        initial_equity=initial_equity,
        final_equity=final_equity,
        net_pnl=net_pnl,
        return_ratio=net_pnl / initial_equity,
        max_drawdown_ratio=max_drawdown_ratio,
        trade_count=trade_count,
        winning_trade_count=winning_trade_count,
        losing_trade_count=losing_trade_count,
        win_rate=win_rate,
    )


def _drawdown_ratio(equity: Decimal, peak_equity: Decimal) -> Decimal:
    if peak_equity <= Decimal("0"):
        return Decimal("0")
    return (peak_equity - equity) / peak_equity
