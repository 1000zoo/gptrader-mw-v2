from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from src.domain.indicator import IndicatorSet
from src.domain.lifecycle import StrategyEvaluation
from src.domain.market import Symbol, Timeframe
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
class BacktestStrategyResult:
    target_id: str
    strategy_result: StrategyResult
    context: StrategyContext


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
