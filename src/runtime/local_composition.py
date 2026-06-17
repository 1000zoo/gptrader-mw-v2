from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import FastAPI

from src.application.usecases.strategy_lifecycle import (
    RunStrategyBacktestCycleCommand,
    RunStrategyBacktestCycleResult,
    RunStrategyBacktestCycleUseCase,
    RunStrategyLifecycleUseCase,
)
from src.domain.lifecycle import (
    SignalGeneratorDefinition,
    StrategyDefinition,
    StrategyEvaluation,
)
from src.domain.market import Candle, MarketSnapshot
from src.interfaces.api import create_app
from src.interfaces.scheduler import StrategyLifecycleScheduler
from src.domain.strategy.implementations import create_default_strategy_catalog
from src.runtime.config import RuntimeSettings
from src.runtime.local_data import evaluate_local_example_strategy
from src.runtime.status import RuntimeStatus


class LocalRuntime:
    def __init__(self, settings: RuntimeSettings | None = None) -> None:
        self.settings = settings or RuntimeSettings()
        self.status = RuntimeStatus.local(self.settings)
        self._strategy_repository = _InMemoryStrategyRepository()
        strategy_catalog = create_default_strategy_catalog()
        self._strategy_scheduler = StrategyLifecycleScheduler(
            run_strategy_lifecycle_usecase=RunStrategyLifecycleUseCase(
                self._strategy_repository
            ),
            run_strategy_backtest_cycle_usecase=RunStrategyBacktestCycleUseCase(
                strategy_repository=self._strategy_repository,
                market_data=_LocalCatalogMarketData(),
                strategy_catalog=strategy_catalog,
            ),
        )
        self._last_strategy_backtest_cycle_result: (
            RunStrategyBacktestCycleResult | None
        ) = None

    def health_details(self) -> dict[str, object]:
        return self.status.as_health_details()

    def readiness_details(self) -> dict[str, object]:
        details = self.status.as_health_details()
        details["ready_for"] = "local"
        details["example_strategy"] = evaluate_local_example_strategy(
            self.settings
        ).signal.direction.value
        return details

    def status_details(self) -> dict[str, object]:
        details = self.readiness_details()
        details["runtime"] = "local"
        details["trade_controls"] = "disabled"
        details["live_order_path"] = "disabled"
        if self._last_strategy_backtest_cycle_result is not None:
            details["strategy_backtest_cycle"] = {
                "succeeded_count": (
                    self._last_strategy_backtest_cycle_result.succeeded_count
                ),
                "failed_count": self._last_strategy_backtest_cycle_result.failed_count,
            }
        return details

    def run_strategy_backtest_cycle(
        self,
        cycle_id: str,
    ) -> RunStrategyBacktestCycleResult:
        execution = self._strategy_scheduler.run_backtest_cycle(
            schedule_name="local-strategy-backtest-cycle",
            command_factory=lambda: RunStrategyBacktestCycleCommand(cycle_id=cycle_id),
        )
        if execution.error is not None:
            raise execution.error
        if execution.result is None:
            raise RuntimeError("strategy backtest cycle did not return a result")
        self._last_strategy_backtest_cycle_result = execution.result
        return execution.result

    def create_app(self) -> FastAPI:
        return create_app(
            health_provider=self.health_details,
            readiness_provider=self.readiness_details,
            status_provider=self.status_details,
        )


def create_local_runtime(settings: RuntimeSettings | None = None) -> LocalRuntime:
    return LocalRuntime(settings)


def create_local_app(settings: RuntimeSettings | None = None) -> FastAPI:
    return create_local_runtime(settings).create_app()


class _LocalCatalogMarketData:
    def load_candles(self, symbol, timeframe, limit):
        return self.load_snapshot(symbol, timeframe, limit).candles

    def load_snapshot(self, symbol, timeframe, limit) -> MarketSnapshot:
        closed_at = datetime(2026, 1, 1, 0, 4, tzinfo=timezone.utc)
        interval = timedelta(seconds=timeframe.duration_seconds)
        closes = (Decimal("100"), Decimal("101"), Decimal("103"), Decimal("104"))
        candles = []
        for index, close_price in enumerate(closes):
            candle_closed_at = closed_at - interval * (len(closes) - index - 1)
            candles.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    opened_at=candle_closed_at - interval,
                    closed_at=candle_closed_at,
                    open_price=close_price - Decimal("1"),
                    high_price=close_price + Decimal("1"),
                    low_price=close_price - Decimal("2"),
                    close_price=close_price,
                    volume=Decimal("10") + Decimal(index),
                )
            )
        return MarketSnapshot(tuple(candles))


class _InMemoryStrategyRepository:
    def __init__(self) -> None:
        self._strategy_definitions: dict[str, StrategyDefinition] = {}
        self._signal_generator_definitions: dict[str, SignalGeneratorDefinition] = {}
        self._evaluations: list[StrategyEvaluation] = []

    def save_strategy_definition(self, definition: StrategyDefinition) -> None:
        self._strategy_definitions[definition.strategy_id] = definition

    def load_strategy_definition(self, strategy_id: str) -> StrategyDefinition | None:
        return self._strategy_definitions.get(strategy_id)

    def save_signal_generator_definition(
        self,
        definition: SignalGeneratorDefinition,
    ) -> None:
        self._signal_generator_definitions[definition.generator_id] = definition

    def load_signal_generator_definition(
        self,
        generator_id: str,
    ) -> SignalGeneratorDefinition | None:
        return self._signal_generator_definitions.get(generator_id)

    def save_strategy_evaluation(self, evaluation: StrategyEvaluation) -> None:
        self._evaluations.append(evaluation)

    def list_strategy_evaluations(
        self,
        target_id: str,
    ) -> tuple[StrategyEvaluation, ...]:
        return tuple(
            evaluation
            for evaluation in self._evaluations
            if evaluation.target_id == target_id
        )
