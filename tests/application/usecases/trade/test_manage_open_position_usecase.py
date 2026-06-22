from decimal import Decimal

from src.application.usecases.trade import (
    ClosePositionResult,
    ManageOpenPositionCommand,
    ManageOpenPositionUseCase,
    TradeExecutionStatus,
)
from src.domain.execution import OrderResult
from src.domain.ports import SignalLogEntry
from src.domain.position import Position
from src.domain.signal import Signal, SignalDirection
from src.domain.signal_generator import GeneratedSignal
from src.domain.strategy import StrategyContext
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


class FakeClosePositionUseCase:
    def __init__(self):
        self.commands = []

    def close(self, command):
        self.commands.append(command)
        return ClosePositionResult(
            status=TradeExecutionStatus.ORDER_SUBMITTED,
            order_result=OrderResult.accepted("close-btc", "exchange-close-1"),
        )


def _command(position: Position, market, indicators) -> ManageOpenPositionCommand:
    return ManageOpenPositionCommand(
        position=position,
        timeframe=market.timeframe,
        candle_limit=120,
        indicators=indicators,
        client_order_id_prefix="close-btc",
        signal_id="exit-signal-1",
        generator_id="generator-1",
    )


def test_manage_open_position_closes_long_on_opposite_short_signal():
    market = make_market()
    indicators = make_indicators(market)
    position = Position.open(
        symbol=market.symbol,
        direction=SignalDirection.LONG,
        quantity=Decimal("0.5"),
        average_entry_price=Decimal("100"),
    )
    close_usecase = FakeClosePositionUseCase()
    signal = GeneratedSignal(
        signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("0.8"))
    )
    usecase = ManageOpenPositionUseCase(
        market_data=FakeMarketData(market),
        signal_generator=FakeSignalGenerator(signal),
        signal_log_repository=FakeSignalLogRepository(),
        close_position_usecase=close_usecase,
    )

    result = usecase.manage(_command(position, market, indicators))

    assert result.status is TradeExecutionStatus.ORDER_SUBMITTED
    assert result.reason == "opposite_signal"
    assert result.generated_signal == signal
    assert result.close_result == ClosePositionResult(
        status=TradeExecutionStatus.ORDER_SUBMITTED,
        order_result=OrderResult.accepted("close-btc", "exchange-close-1"),
    )
    assert close_usecase.commands[0].position == position
    assert close_usecase.commands[0].client_order_id_prefix == "close-btc"


def test_manage_open_position_holds_when_signal_matches_position_direction():
    market = make_market()
    indicators = make_indicators(market)
    position = Position.open(
        symbol=market.symbol,
        direction=SignalDirection.SHORT,
        quantity=Decimal("0.5"),
        average_entry_price=Decimal("100"),
    )
    close_usecase = FakeClosePositionUseCase()
    signal = GeneratedSignal(
        signal=Signal(direction=SignalDirection.SHORT, confidence=Decimal("0.8"))
    )
    signal_log_repository = FakeSignalLogRepository()
    usecase = ManageOpenPositionUseCase(
        market_data=FakeMarketData(market),
        signal_generator=FakeSignalGenerator(signal),
        signal_log_repository=signal_log_repository,
        close_position_usecase=close_usecase,
    )

    result = usecase.manage(_command(position, market, indicators))

    assert result.status is TradeExecutionStatus.SKIPPED
    assert result.reason == "position_signal_still_valid"
    assert result.close_result is None
    assert close_usecase.commands == []
    assert signal_log_repository.entries == [
        SignalLogEntry(
            signal_id="exit-signal-1",
            generator_id="generator-1",
            generated_signal=signal,
        )
    ]
