from src.application.usecases.trade.dto import (
    ExecuteTradeCommand,
    ExecuteTradeResult,
    TradeExecutionStatus,
)
from src.domain.execution import OrderRequest
from src.domain.ports import (
    MarketDataPort,
    OrderExecutionPort,
    SignalLogEntry,
    SignalLogRepositoryPort,
)
from src.domain.risk import PositionSizer, RiskPolicy
from src.domain.signal import Signal, SignalDirection, TradeDecision, TradeDecisionAction
from src.domain.signal_generator import SignalGenerator
from src.domain.strategy import StrategyContext


class ExecuteTradeUseCase:
    def __init__(
        self,
        market_data: MarketDataPort,
        signal_generator: SignalGenerator,
        signal_log_repository: SignalLogRepositoryPort,
        order_execution: OrderExecutionPort,
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self._market_data = market_data
        self._signal_generator = signal_generator
        self._signal_log_repository = signal_log_repository
        self._order_execution = order_execution
        self._risk_policy = risk_policy or RiskPolicy()

    def execute(self, command: ExecuteTradeCommand) -> ExecuteTradeResult:
        market = self._market_data.load_snapshot(
            symbol=command.symbol,
            timeframe=command.timeframe,
            limit=command.candle_limit,
        )
        context = StrategyContext(market=market, indicators=command.indicators)
        generated_signal = self._signal_generator.generate(context)
        self._signal_log_repository.append_signal(
            SignalLogEntry(
                signal_id=command.signal_id,
                generator_id=command.generator_id,
                generated_signal=generated_signal,
            )
        )

        decision = self._decision_from_signal(generated_signal.signal)
        if decision.action not in {
            TradeDecisionAction.ENTER_LONG,
            TradeDecisionAction.ENTER_SHORT,
        }:
            return ExecuteTradeResult(
                status=TradeExecutionStatus.SKIPPED,
                generated_signal=generated_signal,
                reason="non_entry_decision",
            )

        sizer = PositionSizer(
            base_risk_ratio=command.base_risk_ratio,
            leverage=command.leverage,
        )
        position_size = sizer.size(
            decision=decision,
            exposure_limit=command.exposure_limit,
            entry_price=market.latest_candle.close_price,
        )
        risk_check = self._risk_policy.check_entry(
            decision=decision,
            exposure_limit=command.exposure_limit,
            requested_notional=position_size.notional,
        )
        if not risk_check.allowed:
            return ExecuteTradeResult(
                status=TradeExecutionStatus.RISK_REJECTED,
                generated_signal=generated_signal,
                risk_check=risk_check,
                reason=risk_check.reason.value,
            )

        order_result = self._order_execution.submit_order(
            OrderRequest.market(
                client_order_id=self._client_order_id(command),
                symbol=command.symbol,
                side=generated_signal.signal.direction,
                quantity=position_size.quantity,
            )
        )

        return ExecuteTradeResult(
            status=TradeExecutionStatus.ORDER_SUBMITTED,
            generated_signal=generated_signal,
            risk_check=risk_check,
            order_result=order_result,
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
