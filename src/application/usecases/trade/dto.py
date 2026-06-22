from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from src.domain.execution import ExecutionReport, OrderResult
from src.domain.indicator import IndicatorSet
from src.domain.market import Symbol, Timeframe
from src.domain.position import Position
from src.domain.risk import ExposureLimit, RiskCheck
from src.domain.signal_generator import GeneratedSignal
from src.domain.strategy import TakeProfitStopLossLevels


class TradeExecutionStatus(Enum):
    ORDER_SUBMITTED = "order_submitted"
    SKIPPED = "skipped"
    RISK_REJECTED = "risk_rejected"


@dataclass(frozen=True)
class ExecuteTradeCommand:
    symbol: Symbol
    timeframe: Timeframe
    candle_limit: int
    indicators: IndicatorSet
    exposure_limit: ExposureLimit
    base_risk_ratio: Decimal
    leverage: Decimal
    client_order_id_prefix: str
    signal_id: str
    generator_id: str

    def __post_init__(self) -> None:
        if self.candle_limit <= 0:
            raise ValueError("candle_limit must be positive")
        if self.base_risk_ratio <= Decimal("0"):
            raise ValueError("base_risk_ratio must be positive")
        if self.leverage <= Decimal("0"):
            raise ValueError("leverage must be positive")
        if not self.client_order_id_prefix.strip():
            raise ValueError("client_order_id_prefix is required")
        if not self.signal_id.strip():
            raise ValueError("signal_id is required")
        if not self.generator_id.strip():
            raise ValueError("generator_id is required")


@dataclass(frozen=True)
class ExecuteTradeResult:
    status: TradeExecutionStatus
    generated_signal: GeneratedSignal
    risk_check: RiskCheck | None = None
    order_result: OrderResult | None = None
    take_profit_stop_loss: TakeProfitStopLossLevels | None = None
    protective_order_results: tuple[OrderResult, OrderResult] | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ClosePositionCommand:
    position: Position
    client_order_id_prefix: str

    def __post_init__(self) -> None:
        if not self.client_order_id_prefix.strip():
            raise ValueError("client_order_id_prefix is required")


@dataclass(frozen=True)
class ClosePositionResult:
    status: TradeExecutionStatus
    order_result: OrderResult | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ManageOpenPositionCommand:
    position: Position
    timeframe: Timeframe
    candle_limit: int
    indicators: IndicatorSet
    client_order_id_prefix: str
    signal_id: str
    generator_id: str

    def __post_init__(self) -> None:
        if self.candle_limit <= 0:
            raise ValueError("candle_limit must be positive")
        if self.position.symbol != self.indicators.symbol:
            raise ValueError("position and indicators symbol must match")
        if self.timeframe != self.indicators.timeframe:
            raise ValueError("timeframe and indicators timeframe must match")
        if not self.client_order_id_prefix.strip():
            raise ValueError("client_order_id_prefix is required")
        if not self.signal_id.strip():
            raise ValueError("signal_id is required")
        if not self.generator_id.strip():
            raise ValueError("generator_id is required")


@dataclass(frozen=True)
class ManageOpenPositionResult:
    status: TradeExecutionStatus
    generated_signal: GeneratedSignal | None = None
    close_result: ClosePositionResult | None = None
    reason: str | None = None


@dataclass(frozen=True)
class SyncPositionCommand:
    position: Position
    since: datetime
    until: datetime

    def __post_init__(self) -> None:
        if self.until < self.since:
            raise ValueError("until must be greater than or equal to since")


@dataclass(frozen=True)
class SyncPositionResult:
    position: Position
    applied_reports: tuple[ExecutionReport, ...]
