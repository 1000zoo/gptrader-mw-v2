from src.application.usecases.trade.dto import (
    ExecuteTradeCommand,
    ExecuteTradeResult,
    TradeExecutionStatus,
)
from src.domain.execution import OrderRequest
from src.domain.market_feature import MARKET_FEATURES_METADATA_KEY
from src.domain.ports import (
    MarketDataPort,
    MarketFeatureProviderPort,
    OrderExecutionPort,
    SignalLogEntry,
    SignalLogRepositoryPort,
)
from src.domain.risk import FixedPositionSizingStrategy, PositionSize, PositionSizingStrategy, RiskPolicy
from src.domain.signal import Signal, SignalDirection, TradeDecision, TradeDecisionAction
from src.domain.signal_generator import SignalGenerator
from src.domain.strategy import StrategyContext, TakeProfitStopLossStrategy
from src.infrastructure.market_feature import EmptyMarketFeatureProvider
from src.observability.logging import runtime_logger


class ExecuteTradeUseCase:
    def __init__(
        self,
        market_data: MarketDataPort,
        signal_generator: SignalGenerator,
        signal_log_repository: SignalLogRepositoryPort,
        order_execution: OrderExecutionPort,
        risk_policy: RiskPolicy | None = None,
        take_profit_stop_loss_strategy: TakeProfitStopLossStrategy | None = None,
        position_sizing_strategy: PositionSizingStrategy | None = None,
        market_feature_provider: MarketFeatureProviderPort | None = None,
    ) -> None:
        self._market_data = market_data
        self._signal_generator = signal_generator
        self._signal_log_repository = signal_log_repository
        self._order_execution = order_execution
        self._risk_policy = risk_policy or RiskPolicy()
        self._take_profit_stop_loss_strategy = take_profit_stop_loss_strategy
        self._position_sizing_strategy = position_sizing_strategy
        self._market_feature_provider = (
            market_feature_provider
            if market_feature_provider is not None
            else EmptyMarketFeatureProvider()
        )

    def execute(self, command: ExecuteTradeCommand) -> ExecuteTradeResult:
        runtime_logger.info(
            "trade execution usecase started",
            signal_id=command.signal_id,
            generator_id=command.generator_id,
            symbol=command.symbol.pair,
            timeframe=str(command.timeframe),
            candle_limit=command.candle_limit,
        )
        market = self._market_data.load_snapshot(
            symbol=command.symbol,
            timeframe=command.timeframe,
            limit=command.candle_limit,
        )
        entry_price = market.latest_candle.close_price
        runtime_logger.info(
            "market snapshot loaded",
            signal_id=command.signal_id,
            symbol=command.symbol.pair,
            candle_count=len(market.candles),
            entry_price=str(entry_price),
            latest_closed_at=market.latest_candle.closed_at.isoformat(),
        )
        market_features = self._market_feature_provider.load_features(
            symbol=market.symbol,
            timeframe=market.timeframe,
            as_of=market.latest_candle.closed_at,
        )
        context = StrategyContext(
            market=market,
            indicators=command.indicators,
            metadata={MARKET_FEATURES_METADATA_KEY: market_features},
        )
        generated_signal = self._signal_generator.generate(context)
        runtime_logger.info(
            "strategy signal generated",
            signal_id=command.signal_id,
            generator_id=command.generator_id,
            signal_direction=generated_signal.signal.direction.value,
            signal_confidence=str(generated_signal.signal.confidence),
            strategy_results=_strategy_result_payloads(generated_signal.strategy_results),
        )
        self._signal_log_repository.append_signal(
            SignalLogEntry(
                signal_id=command.signal_id,
                generator_id=command.generator_id,
                generated_signal=generated_signal,
            )
        )
        runtime_logger.info(
            "signal persisted",
            signal_id=command.signal_id,
            generator_id=command.generator_id,
        )

        decision = self._decision_from_signal(generated_signal.signal)
        runtime_logger.info(
            "trade decision derived",
            signal_id=command.signal_id,
            position_direction=decision.action.value,
            signal_direction=generated_signal.signal.direction.value,
            signal_confidence=str(generated_signal.signal.confidence),
        )
        if decision.action not in {
            TradeDecisionAction.ENTER_LONG,
            TradeDecisionAction.ENTER_SHORT,
        }:
            runtime_logger.info(
                "trade execution skipped",
                signal_id=command.signal_id,
                reason="non_entry_decision",
                position_direction=decision.action.value,
            )
            return ExecuteTradeResult(
                status=TradeExecutionStatus.SKIPPED,
                generated_signal=generated_signal,
                reason="non_entry_decision",
            )

        sizing_strategy = self._position_sizing_strategy or FixedPositionSizingStrategy(
            equity_ratio=command.base_risk_ratio,
            leverage=command.leverage,
        )
        sizing_decision = sizing_strategy.decide(
            decision=decision,
            exposure_limit=command.exposure_limit,
        )
        requested_notional = (
            command.exposure_limit.equity
            * sizing_decision.equity_ratio
            * sizing_decision.leverage
        )
        capped_notional = min(
            requested_notional,
            command.exposure_limit.remaining_total_exposure,
            command.exposure_limit.remaining_symbol_exposure,
        )
        position_size = PositionSize(
            notional=capped_notional,
            quantity=capped_notional / entry_price,
        )
        runtime_logger.info(
            "trade entry sizing calculated",
            signal_id=command.signal_id,
            position_direction=decision.action.value,
            entry_price=str(entry_price),
            requested_notional=str(requested_notional),
            position_notional=str(position_size.notional),
            position_quantity=str(position_size.quantity),
            equity=str(command.exposure_limit.equity),
            base_risk_ratio=str(sizing_decision.equity_ratio),
            leverage=str(sizing_decision.leverage),
            max_total_exposure=str(command.exposure_limit.max_total_exposure),
            max_symbol_exposure=str(command.exposure_limit.max_symbol_exposure),
        )
        risk_check = self._risk_policy.check_entry(
            decision=decision,
            exposure_limit=command.exposure_limit,
            requested_notional=requested_notional,
        )
        runtime_logger.info(
            "trade risk checked",
            signal_id=command.signal_id,
            allowed=risk_check.allowed,
            reason=risk_check.reason.value,
            checked_notional=str(requested_notional),
        )
        if not risk_check.allowed:
            runtime_logger.warning(
                "trade execution risk rejected",
                signal_id=command.signal_id,
                reason=risk_check.reason.value,
                requested_notional=str(requested_notional),
                position_notional=str(position_size.notional),
            )
            return ExecuteTradeResult(
                status=TradeExecutionStatus.RISK_REJECTED,
                generated_signal=generated_signal,
                risk_check=risk_check,
                reason=risk_check.reason.value,
            )

        take_profit_stop_loss = None
        if self._take_profit_stop_loss_strategy is not None:
            take_profit_stop_loss = self._take_profit_stop_loss_strategy.calculate(
                context,
                generated_signal.signal.direction,
            )
            runtime_logger.info(
                "trade take profit stop loss calculated",
                signal_id=command.signal_id,
                strategy=take_profit_stop_loss.strategy_name,
                entry_price=str(take_profit_stop_loss.entry_price),
                take_profit=str(take_profit_stop_loss.take_profit),
                stop_loss=str(take_profit_stop_loss.stop_loss),
            )

        client_order_id = self._client_order_id(command)
        runtime_logger.info(
            "trade order request prepared",
            signal_id=command.signal_id,
            client_order_id=client_order_id,
            symbol=command.symbol.pair,
            side=generated_signal.signal.direction.value,
            order_type="market",
            quantity=str(position_size.quantity),
            entry_price=str(entry_price),
            position_notional=str(position_size.notional),
        )
        order_result = self._order_execution.submit_order(
            OrderRequest.market(
                client_order_id=client_order_id,
                symbol=command.symbol,
                side=generated_signal.signal.direction,
                quantity=position_size.quantity,
            )
        )
        protective_order_results = None
        if take_profit_stop_loss is not None:
            protective_order_results = (
                self._order_execution.submit_take_profit_stop_loss_orders(
                    symbol=command.symbol,
                    position_direction=generated_signal.signal.direction,
                    take_profit=take_profit_stop_loss.take_profit,
                    stop_loss=take_profit_stop_loss.stop_loss,
                    client_order_id_prefix=client_order_id,
                )
            )
            runtime_logger.info(
                "trade protective orders submitted",
                signal_id=command.signal_id,
                client_order_id=client_order_id,
                take_profit_order_status=protective_order_results[0].status.value,
                stop_loss_order_status=protective_order_results[1].status.value,
            )
        runtime_logger.info(
            "trade order result received",
            signal_id=command.signal_id,
            client_order_id=client_order_id,
            order_status=order_result.status.value,
            exchange_order_id=order_result.exchange_order_id,
        )

        return ExecuteTradeResult(
            status=TradeExecutionStatus.ORDER_SUBMITTED,
            generated_signal=generated_signal,
            risk_check=risk_check,
            order_result=order_result,
            take_profit_stop_loss=take_profit_stop_loss,
            protective_order_results=protective_order_results,
        )

    def _decision_from_signal(self, signal: Signal) -> TradeDecision:
        if signal.direction is SignalDirection.LONG:
            action = TradeDecisionAction.ENTER_LONG
        elif signal.direction is SignalDirection.SHORT:
            action = TradeDecisionAction.ENTER_SHORT
        else:
            action = TradeDecisionAction.HOLD

        return TradeDecision(action=action, signal=signal)

    def _client_order_id(self, command: ExecuteTradeCommand) -> str:
        return f"{command.client_order_id_prefix}-{command.signal_id}"


def _strategy_result_payloads(strategy_results) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "strategy": result.name,
            "direction": result.signal.direction.value,
            "confidence": str(result.signal.confidence),
            "reason_codes": tuple(reason.code for reason in result.signal.reasons),
            "metadata": dict(result.metadata),
        }
        for result in strategy_results
    )
