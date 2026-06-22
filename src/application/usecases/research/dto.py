from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from src.domain.indicator import IndicatorSet
from src.domain.lifecycle import StrategyEvaluation
from src.domain.market import Symbol, Timeframe
from src.domain.signal import SignalDirection
from src.domain.signal_generator import GeneratedSignal
from src.domain.strategy import StrategyContext, StrategyResult


class ResearchRunMode(Enum):
    BACKTEST = "backtest"
    DRY_RUN = "dry_run"


@dataclass(frozen=True)
class BacktestStrategyCommand:
    target_id: str
    symbol: Symbol
    timeframe: Timeframe
    candle_limit: int
    indicators: IndicatorSet
    start_at: datetime | None = None
    end_at: datetime | None = None
    initial_equity: Decimal = Decimal("10000")
    risk_ratio: Decimal = Decimal("0.01")
    leverage: Decimal = Decimal("1")
    fee_rate: Decimal = Decimal("0")
    slippage_rate: Decimal = Decimal("0")
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        target_id = self.target_id.strip()
        if not target_id:
            raise ValueError("target_id is required")
        if self.candle_limit <= 0:
            raise ValueError("candle_limit must be positive")
        if (self.start_at is None) != (self.end_at is None):
            raise ValueError("start_at and end_at must be provided together")
        if (
            self.start_at is not None
            and self.end_at is not None
            and self.end_at <= self.start_at
        ):
            raise ValueError("end_at must be after start_at")
        if self.initial_equity <= Decimal("0"):
            raise ValueError("initial_equity must be positive")
        if self.risk_ratio <= Decimal("0"):
            raise ValueError("risk_ratio must be positive")
        if self.leverage <= Decimal("0"):
            raise ValueError("leverage must be positive")
        if self.fee_rate < Decimal("0"):
            raise ValueError("fee_rate must be greater than or equal to zero")
        if self.slippage_rate < Decimal("0"):
            raise ValueError("slippage_rate must be greater than or equal to zero")

        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class BacktestTrade:
    direction: SignalDirection
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    fee_paid: Decimal
    net_pnl: Decimal
    entry_time: object
    exit_time: object
    exit_reason: str


@dataclass(frozen=True)
class BacktestPerformance:
    initial_equity: Decimal
    final_equity: Decimal
    net_pnl: Decimal
    return_ratio: Decimal
    max_drawdown_ratio: Decimal
    trade_count: int
    winning_trade_count: int
    losing_trade_count: int
    win_rate: Decimal


@dataclass(frozen=True)
class BacktestStrategyResult:
    target_id: str
    strategy_result: StrategyResult
    context: StrategyContext
    trades: tuple[BacktestTrade, ...] = ()
    performance: BacktestPerformance | None = None


@dataclass(frozen=True)
class DryRunStrategyCommand:
    target_id: str
    symbol: Symbol
    timeframe: Timeframe
    candle_limit: int
    indicators: IndicatorSet
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        target_id = self.target_id.strip()
        if not target_id:
            raise ValueError("target_id is required")
        if self.candle_limit <= 0:
            raise ValueError("candle_limit must be positive")

        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class DryRunStrategyResult:
    target_id: str
    generated_signal: GeneratedSignal
    context: StrategyContext


@dataclass(frozen=True)
class EvaluateStrategyCommand:
    evaluation_id: str
    target_id: str
    mode: ResearchRunMode
    metrics: Mapping[str, Decimal] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        evaluation_id = self.evaluation_id.strip()
        target_id = self.target_id.strip()
        if not evaluation_id:
            raise ValueError("evaluation_id is required")
        if not target_id:
            raise ValueError("target_id is required")

        object.__setattr__(self, "evaluation_id", evaluation_id)
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class EvaluateStrategyResult:
    evaluation: StrategyEvaluation
