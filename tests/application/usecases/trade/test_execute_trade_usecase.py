from decimal import Decimal

from src.application.usecases.trade import (
    ExecuteTradeCommand,
    ExecuteTradeUseCase,
    TradeExecutionStatus,
)
from src.domain.execution import OrderResult
from src.domain.market_feature import MarketFeatureSet
from src.domain.ports import SignalLogEntry
from src.domain.risk import ExposureLimit, RiskCheck, RiskDecisionReason
from src.domain.signal import Signal, SignalDirection
from src.domain.signal_generator import GeneratedSignal
from src.domain.strategy import StrategyContext
from src.domain.strategy.take_profit_stop_loss import TakeProfitStopLossLevels
from tests.domain.strategy.test_strategy_context import make_indicators, make_market


class FakeMarketData:
    def __init__(self, market):
        self.market = market
        self.requests = []

    def load_snapshot(self, symbol, timeframe, limit):
        self.requests.append((symbol, timeframe, limit))
        return self.market


class FakeSignalGenerator:
    def __init__(self, generated_signal):
        self.generated_signal = generated_signal
        self.contexts = []

    def generate(self, context: StrategyContext) -> GeneratedSignal:
        self.contexts.append(context)
        return self.generated_signal


class FakeSignalLogRepository:
    def __init__(self):
        self.entries = []

    def append_signal(self, entry: SignalLogEntry) -> None:
        self.entries.append(entry)


class FakeOrderExecution:
    def __init__(self):
        self.requests = []
        self.protective_requests = []

    def submit_order(self, request):
        self.requests.append(request)
        return OrderResult.accepted(request.client_order_id, "exchange-1")

    def submit_take_profit_stop_loss_orders(
        self,
        symbol,
        position_direction,
        take_profit,
        stop_loss,
        client_order_id_prefix,
    ):
        self.protective_requests.append(
            (symbol, position_direction, take_profit, stop_loss, client_order_id_prefix)
        )
        return (
            OrderResult.accepted(f"{client_order_id_prefix}-tp", "tp-1"),
            OrderResult.accepted(f"{client_order_id_prefix}-sl", "sl-1"),
        )


class RecordingMarketFeatureProvider:
    def __init__(self, result):
        self.result = result
        self.requests = []

    def load_features(self, symbol, timeframe, as_of):
        self.requests.append((symbol, timeframe, as_of))
        return self.result


class FalseyMarketFeatureProvider(RecordingMarketFeatureProvider):
    def __bool__(self):
        return False


class RejectingRiskPolicy:
    def __init__(self):
        self.requests = []

    def check_entry(self, decision, exposure_limit, requested_notional):
        self.requests.append((decision, exposure_limit, requested_notional))
        return RiskCheck(
            allowed=False,
            reason=RiskDecisionReason.TOTAL_EXPOSURE_EXCEEDED,
        )


class FakeTakeProfitStopLossStrategy:
    def __init__(self):
        self.requests = []

    def calculate(self, context, direction):
        self.requests.append((context, direction))
        return TakeProfitStopLossLevels(
            strategy_name="fake-tpsl",
            entry_price=context.market.latest_candle.close_price,
            take_profit=Decimal("120"),
            stop_loss=Decimal("95"),
        )


class FixedPositionSizingStrategy:
    def __init__(self, equity_ratio: Decimal, leverage: Decimal) -> None:
        self.equity_ratio = equity_ratio
        self.leverage = leverage
        self.requests = []

    def decide(self, decision, exposure_limit):
        self.requests.append((decision, exposure_limit))
        from src.domain.risk import PositionSizingDecision

        return PositionSizingDecision(
            equity_ratio=self.equity_ratio,
            leverage=self.leverage,
        )


def _exposure_limit() -> ExposureLimit:
    return ExposureLimit(
        equity=Decimal("1000"),
        current_total_exposure=Decimal("100"),
        current_symbol_exposure=Decimal("50"),
        max_total_exposure_ratio=Decimal("1"),
        max_symbol_exposure_ratio=Decimal("0.8"),
    )


def _exhausted_exposure_limit() -> ExposureLimit:
    return ExposureLimit(
        equity=Decimal("1000"),
        current_total_exposure=Decimal("1000"),
        current_symbol_exposure=Decimal("800"),
        max_total_exposure_ratio=Decimal("1"),
        max_symbol_exposure_ratio=Decimal("0.8"),
    )


def test_execute_trade_command_stores_trade_execution_inputs():
    market = make_market()
    indicators = make_indicators(market)

    command = ExecuteTradeCommand(
        symbol=market.symbol,
        timeframe=market.timeframe,
        candle_limit=120,
        indicators=indicators,
        exposure_limit=_exposure_limit(),
        base_risk_ratio=Decimal("0.1"),
        leverage=Decimal("3"),
        client_order_id_prefix="live-btc",
        signal_id="signal-1",
        generator_id="generator-1",
    )

    assert command.symbol == market.symbol
    assert command.timeframe == market.timeframe
    assert command.candle_limit == 120
    assert command.indicators == indicators
    assert command.exposure_limit == _exposure_limit()
    assert command.base_risk_ratio == Decimal("0.1")
    assert command.leverage == Decimal("3")
    assert command.client_order_id_prefix == "live-btc"
    assert command.signal_id == "signal-1"
    assert command.generator_id == "generator-1"


def test_execute_trade_usecase_submits_market_order_for_entry_signal():
    market = make_market()
    indicators = make_indicators(market)
    generated_signal = GeneratedSignal(
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.5")),
    )
    market_data = FakeMarketData(market)
    signal_generator = FakeSignalGenerator(generated_signal)
    signal_log_repository = FakeSignalLogRepository()
    order_execution = FakeOrderExecution()
    usecase = ExecuteTradeUseCase(
        market_data=market_data,
        signal_generator=signal_generator,
        signal_log_repository=signal_log_repository,
        order_execution=order_execution,
    )

    result = usecase.execute(
        ExecuteTradeCommand(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=indicators,
            exposure_limit=_exposure_limit(),
            base_risk_ratio=Decimal("0.1"),
            leverage=Decimal("3"),
            client_order_id_prefix="live-btc",
            signal_id="signal-1",
            generator_id="generator-1",
        )
    )

    assert result.status is TradeExecutionStatus.ORDER_SUBMITTED
    assert result.generated_signal == generated_signal
    assert result.order_result == OrderResult.accepted("live-btc-signal-1", "exchange-1")
    assert market_data.requests == [(market.symbol, market.timeframe, 120)]
    assert signal_generator.contexts[0].market == market
    assert signal_generator.contexts[0].indicators == indicators
    assert signal_log_repository.entries == [
        SignalLogEntry(
            signal_id="signal-1",
            generator_id="generator-1",
            generated_signal=generated_signal,
        )
    ]
    assert len(order_execution.requests) == 1
    order_request = order_execution.requests[0]
    assert order_request.client_order_id == "live-btc-signal-1"
    assert order_request.symbol == market.symbol
    assert order_request.side is SignalDirection.LONG
    assert order_request.quantity == Decimal("300.0") / market.latest_candle.close_price
    assert order_request.reduce_only is False


def test_execute_trade_usecase_uses_position_sizing_strategy_for_order_size():
    market = make_market()
    indicators = make_indicators(market)
    generated_signal = GeneratedSignal(
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.5")),
    )
    sizing_strategy = FixedPositionSizingStrategy(
        equity_ratio=Decimal("0.25"),
        leverage=Decimal("4"),
    )
    risk_policy = RejectingRiskPolicy()
    order_execution = FakeOrderExecution()
    usecase = ExecuteTradeUseCase(
        market_data=FakeMarketData(market),
        signal_generator=FakeSignalGenerator(generated_signal),
        signal_log_repository=FakeSignalLogRepository(),
        order_execution=order_execution,
        risk_policy=risk_policy,
        position_sizing_strategy=sizing_strategy,
    )

    result = usecase.execute(
        ExecuteTradeCommand(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=indicators,
            exposure_limit=_exposure_limit(),
            base_risk_ratio=Decimal("0.1"),
            leverage=Decimal("3"),
            client_order_id_prefix="live-btc",
            signal_id="signal-1",
            generator_id="generator-1",
        )
    )

    assert result.status is TradeExecutionStatus.RISK_REJECTED
    assert sizing_strategy.requests[0][1] == _exposure_limit()
    assert risk_policy.requests[0][2] == Decimal("1000.00")
    assert order_execution.requests == []


def test_execute_trade_usecase_calculates_take_profit_stop_loss_for_entry_signal():
    market = make_market()
    indicators = make_indicators(market)
    generated_signal = GeneratedSignal(
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.5")),
    )
    tpsl_strategy = FakeTakeProfitStopLossStrategy()
    order_execution = FakeOrderExecution()
    usecase = ExecuteTradeUseCase(
        market_data=FakeMarketData(market),
        signal_generator=FakeSignalGenerator(generated_signal),
        signal_log_repository=FakeSignalLogRepository(),
        order_execution=order_execution,
        take_profit_stop_loss_strategy=tpsl_strategy,
    )

    result = usecase.execute(
        ExecuteTradeCommand(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=indicators,
            exposure_limit=_exposure_limit(),
            base_risk_ratio=Decimal("0.1"),
            leverage=Decimal("3"),
            client_order_id_prefix="live-btc",
            signal_id="signal-1",
            generator_id="generator-1",
        )
    )

    assert result.take_profit_stop_loss == TakeProfitStopLossLevels(
        strategy_name="fake-tpsl",
        entry_price=market.latest_candle.close_price,
        take_profit=Decimal("120"),
        stop_loss=Decimal("95"),
    )
    assert tpsl_strategy.requests[0][0].market == market
    assert tpsl_strategy.requests[0][0].indicators == indicators
    assert tpsl_strategy.requests[0][1] is SignalDirection.LONG
    assert result.protective_order_results == (
        OrderResult.accepted("live-btc-signal-1-tp", "tp-1"),
        OrderResult.accepted("live-btc-signal-1-sl", "sl-1"),
    )
    assert order_execution.protective_requests == [
        (
            market.symbol,
            SignalDirection.LONG,
            Decimal("120"),
            Decimal("95"),
            "live-btc-signal-1",
        )
    ]


def test_execute_trade_usecase_skips_order_for_wait_signal():
    market = make_market()
    generated_signal = GeneratedSignal(signal=Signal.wait())
    order_execution = FakeOrderExecution()
    signal_log_repository = FakeSignalLogRepository()
    usecase = ExecuteTradeUseCase(
        market_data=FakeMarketData(market),
        signal_generator=FakeSignalGenerator(generated_signal),
        signal_log_repository=signal_log_repository,
        order_execution=order_execution,
    )

    result = usecase.execute(
        ExecuteTradeCommand(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=make_indicators(market),
            exposure_limit=_exposure_limit(),
            base_risk_ratio=Decimal("0.1"),
            leverage=Decimal("3"),
            client_order_id_prefix="live-btc",
            signal_id="signal-1",
            generator_id="generator-1",
        )
    )

    assert result.status is TradeExecutionStatus.SKIPPED
    assert result.generated_signal == generated_signal
    assert result.reason == "non_entry_decision"
    assert result.order_result is None
    assert order_execution.requests == []
    assert len(signal_log_repository.entries) == 1


def test_execute_trade_usecase_skips_order_when_risk_policy_rejects_entry():
    market = make_market()
    generated_signal = GeneratedSignal(
        signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("0.5")),
    )
    order_execution = FakeOrderExecution()
    risk_policy = RejectingRiskPolicy()
    usecase = ExecuteTradeUseCase(
        market_data=FakeMarketData(market),
        signal_generator=FakeSignalGenerator(generated_signal),
        signal_log_repository=FakeSignalLogRepository(),
        order_execution=order_execution,
        risk_policy=risk_policy,
    )

    result = usecase.execute(
        ExecuteTradeCommand(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=make_indicators(market),
            exposure_limit=_exposure_limit(),
            base_risk_ratio=Decimal("0.1"),
            leverage=Decimal("3"),
            client_order_id_prefix="live-btc",
            signal_id="signal-1",
            generator_id="generator-1",
        )
    )

    assert result.status is TradeExecutionStatus.RISK_REJECTED
    assert result.risk_check == RiskCheck(
        allowed=False,
        reason=RiskDecisionReason.TOTAL_EXPOSURE_EXCEEDED,
    )
    assert result.reason == "total_exposure_exceeded"
    assert result.order_result is None
    assert order_execution.requests == []
    assert risk_policy.requests[0][2] == Decimal("300.0")


def test_execute_trade_usecase_rejects_entry_when_exposure_is_exhausted():
    market = make_market()
    generated_signal = GeneratedSignal(
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.5")),
    )
    order_execution = FakeOrderExecution()
    usecase = ExecuteTradeUseCase(
        market_data=FakeMarketData(market),
        signal_generator=FakeSignalGenerator(generated_signal),
        signal_log_repository=FakeSignalLogRepository(),
        order_execution=order_execution,
    )

    result = usecase.execute(
        ExecuteTradeCommand(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=make_indicators(market),
            exposure_limit=_exhausted_exposure_limit(),
            base_risk_ratio=Decimal("0.1"),
            leverage=Decimal("3"),
            client_order_id_prefix="live-btc",
            signal_id="signal-1",
            generator_id="generator-1",
        )
    )

    assert result.status is TradeExecutionStatus.RISK_REJECTED
    assert result.reason == "total_exposure_exceeded"
    assert order_execution.requests == []


def test_execute_trade_usecase_uses_latest_closed_candle_as_feature_cutoff():
    market = make_market()
    features = MarketFeatureSet(
        market.symbol,
        market.timeframe,
        market.latest_candle.closed_at,
        (),
    )
    provider = RecordingMarketFeatureProvider(features)
    signal_generator = FakeSignalGenerator(GeneratedSignal(signal=Signal.wait()))
    usecase = ExecuteTradeUseCase(
        market_data=FakeMarketData(market),
        signal_generator=signal_generator,
        signal_log_repository=FakeSignalLogRepository(),
        order_execution=FakeOrderExecution(),
        market_feature_provider=provider,
    )

    usecase.execute(
        ExecuteTradeCommand(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=make_indicators(market),
            exposure_limit=_exposure_limit(),
            base_risk_ratio=Decimal("0.1"),
            leverage=Decimal("3"),
            client_order_id_prefix="live-btc",
            signal_id="signal-1",
            generator_id="generator-1",
        )
    )

    assert provider.requests == [
        (market.symbol, market.timeframe, market.latest_candle.closed_at)
    ]
    assert signal_generator.contexts[0].market_features is features


def test_execute_trade_usecase_defaults_to_aligned_empty_market_features():
    market = make_market()
    signal_generator = FakeSignalGenerator(GeneratedSignal(signal=Signal.wait()))
    usecase = ExecuteTradeUseCase(
        market_data=FakeMarketData(market),
        signal_generator=signal_generator,
        signal_log_repository=FakeSignalLogRepository(),
        order_execution=FakeOrderExecution(),
    )

    usecase.execute(
        ExecuteTradeCommand(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=make_indicators(market),
            exposure_limit=_exposure_limit(),
            base_risk_ratio=Decimal("0.1"),
            leverage=Decimal("3"),
            client_order_id_prefix="live-btc",
            signal_id="signal-1",
            generator_id="generator-1",
        )
    )

    features = signal_generator.contexts[0].market_features
    assert features == MarketFeatureSet(
        market.symbol,
        market.timeframe,
        market.latest_candle.closed_at,
        (),
    )


def test_execute_trade_usecase_preserves_explicit_falsey_feature_provider():
    market = make_market()
    features = MarketFeatureSet(
        market.symbol,
        market.timeframe,
        market.latest_candle.closed_at,
        (),
        ("explicit",),
    )
    provider = FalseyMarketFeatureProvider(features)
    signal_generator = FakeSignalGenerator(GeneratedSignal(signal=Signal.wait()))
    usecase = ExecuteTradeUseCase(
        market_data=FakeMarketData(market),
        signal_generator=signal_generator,
        signal_log_repository=FakeSignalLogRepository(),
        order_execution=FakeOrderExecution(),
        market_feature_provider=provider,
    )

    usecase.execute(
        ExecuteTradeCommand(
            symbol=market.symbol,
            timeframe=market.timeframe,
            candle_limit=120,
            indicators=make_indicators(market),
            exposure_limit=_exposure_limit(),
            base_risk_ratio=Decimal("0.1"),
            leverage=Decimal("3"),
            client_order_id_prefix="live-btc",
            signal_id="signal-1",
            generator_id="generator-1",
        )
    )

    assert signal_generator.contexts[0].market_features is features
