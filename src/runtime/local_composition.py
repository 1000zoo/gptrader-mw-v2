from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote, urlparse

from fastapi import FastAPI

from src.application.usecases.trade import (
    ClosePositionUseCase,
    ExecuteTradeCommand,
    ExecuteTradeResult,
    ExecuteTradeUseCase,
    ManageOpenPositionUseCase,
    SyncPositionUseCase,
)
from src.application.usecases.strategy_lifecycle import (
    RunStrategyBacktestCycleCommand,
    RunStrategyBacktestCycleResult,
    RunStrategyBacktestCycleUseCase,
    RunStrategyLifecycleUseCase,
)
from src.domain.execution import OrderRequest, OrderResult
from src.domain.lifecycle import (
    SignalGeneratorDefinition,
    StrategyDefinition,
    StrategyEvaluation,
)
from src.domain.market import Candle, MarketSnapshot
from src.domain.risk import ExposureLimit
from src.domain.signal import SignalDirection
from src.domain.signal_generator import CompositeSignalGenerator
from src.infrastructure.persistence import (
    SqliteRuntimeStateRepository,
    SqliteSignalLogRepository,
)
from src.interfaces.api import create_app
from src.interfaces.api.trade_controller import create_trade_router
from src.interfaces.scheduler import StrategyLifecycleScheduler, TradeScheduler
from src.domain.strategy.implementations import (
    AtrTakeProfitStopLossStrategy,
    create_default_strategy_catalog,
)
from src.runtime.config import RuntimeMode, RuntimeSettings
from src.runtime.local_data import (
    build_local_indicator_set,
    evaluate_local_example_strategy,
    parse_symbol,
    parse_timeframe,
)
from src.observability.logging import ensure_runtime_logging_configured, runtime_logger
from src.runtime.status import RuntimeDependency, RuntimeStatus


class LocalRuntime:
    def __init__(self, settings: RuntimeSettings | None = None) -> None:
        ensure_runtime_logging_configured()
        self.settings = settings or RuntimeSettings()
        self.status = _runtime_status(self.settings)
        database_path = _sqlite_path_from_url(self.settings.database_url)
        runtime_logger.info(
            "runtime creation started",
            mode=self.settings.mode.value,
            symbol=self.settings.symbol,
            timeframe=self.settings.timeframe,
            database_url=self.settings.database_url,
        )
        self._runtime_repository = SqliteRuntimeStateRepository(database_path)
        signal_log_repository = SqliteSignalLogRepository(database_path)
        self._strategy_repository = _InMemoryStrategyRepository()
        strategy_catalog = create_default_strategy_catalog()
        market_data = _LocalCatalogMarketData()
        dry_run_order_execution = _DryRunOrderExecution(
            runtime_repository=self._runtime_repository
        )
        self._strategy_scheduler = StrategyLifecycleScheduler(
            run_strategy_lifecycle_usecase=RunStrategyLifecycleUseCase(
                self._strategy_repository
            ),
            run_strategy_backtest_cycle_usecase=RunStrategyBacktestCycleUseCase(
                strategy_repository=self._strategy_repository,
                market_data=market_data,
                strategy_catalog=strategy_catalog,
            ),
        )
        self._trade_scheduler = TradeScheduler(
            execute_trade_usecase=ExecuteTradeUseCase(
                market_data=market_data,
                signal_generator=CompositeSignalGenerator(
                    strategies=(
                        strategy_catalog.create_strategy(
                            next(
                                spec
                                for spec in strategy_catalog.list_specs()
                                if spec.strategy_id == "latest-close-moving-average"
                            )
                        ),
                    )
                ),
                signal_log_repository=signal_log_repository,
                order_execution=dry_run_order_execution,
                take_profit_stop_loss_strategy=AtrTakeProfitStopLossStrategy(
                    atr_period=3
                ),
            ),
            close_position_usecase=ClosePositionUseCase(dry_run_order_execution),
            sync_position_usecase=SyncPositionUseCase(dry_run_order_execution),
            manage_open_position_usecase=ManageOpenPositionUseCase(
                market_data=market_data,
                signal_generator=CompositeSignalGenerator(
                    strategies=(
                        strategy_catalog.create_strategy(
                            next(
                                spec
                                for spec in strategy_catalog.list_specs()
                                if spec.strategy_id == "latest-close-moving-average"
                            )
                        ),
                    )
                ),
                signal_log_repository=signal_log_repository,
                close_position_usecase=ClosePositionUseCase(dry_run_order_execution),
            ),
        )
        self._last_strategy_backtest_cycle_result: (
            RunStrategyBacktestCycleResult | None
        ) = None
        self._last_trade_execution_result: ExecuteTradeResult | None = None
        runtime_logger.info(
            "runtime created",
            mode=self.settings.mode.value,
            symbol=self.settings.symbol,
            timeframe=self.settings.timeframe,
        )

    def health_details(self) -> dict[str, object]:
        return self.status.as_health_details()

    def readiness_details(self) -> dict[str, object]:
        details = self.status.as_health_details()
        details["ready_for"] = self.settings.mode.value
        details["example_strategy"] = evaluate_local_example_strategy(
            self.settings
        ).signal.direction.value
        return details

    def status_details(self) -> dict[str, object]:
        details = self.readiness_details()
        details["runtime"] = self.settings.mode.value
        details["trade_controls"] = (
            "enabled" if self.settings.mode is RuntimeMode.DRY_RUN else "disabled"
        )
        details["live_order_path"] = "disabled"
        if self._last_strategy_backtest_cycle_result is not None:
            details["strategy_backtest_cycle"] = {
                "succeeded_count": (
                    self._last_strategy_backtest_cycle_result.succeeded_count
                ),
                "failed_count": self._last_strategy_backtest_cycle_result.failed_count,
            }
        if self._last_trade_execution_result is not None:
            details["last_trade_execution"] = {
                "status": self._last_trade_execution_result.status.value,
                "order_status": (
                    None
                    if self._last_trade_execution_result.order_result is None
                    else self._last_trade_execution_result.order_result.status.value
                ),
            }
        return details

    def run_strategy_backtest_cycle(
        self,
        cycle_id: str,
    ) -> RunStrategyBacktestCycleResult:
        runtime_logger.info(
            "strategy backtest cycle started",
            cycle_id=cycle_id,
            mode=self.settings.mode.value,
        )
        execution = self._strategy_scheduler.run_backtest_cycle(
            schedule_name="local-strategy-backtest-cycle",
            command_factory=lambda: RunStrategyBacktestCycleCommand(cycle_id=cycle_id),
        )
        if execution.error is not None:
            runtime_logger.error(
                "strategy backtest cycle failed",
                cycle_id=cycle_id,
                error=str(execution.error),
            )
            raise execution.error
        if execution.result is None:
            error = RuntimeError("strategy backtest cycle did not return a result")
            runtime_logger.error("strategy backtest cycle failed", error=str(error))
            raise error
        self._last_strategy_backtest_cycle_result = execution.result
        runtime_logger.info(
            "strategy backtest cycle succeeded",
            cycle_id=cycle_id,
            succeeded_count=execution.result.succeeded_count,
            failed_count=execution.result.failed_count,
        )
        return execution.result

    def run_trade_execution_once(self, signal_id: str) -> ExecuteTradeResult:
        runtime_logger.info(
            "dry-run trade execution started",
            signal_id=signal_id,
            mode=self.settings.mode.value,
            symbol=self.settings.symbol,
            timeframe=self.settings.timeframe,
        )
        execution = self._trade_scheduler.run_trade_execution(
            schedule_name=f"{self.settings.symbol}-{self.settings.timeframe}-dry-run",
            command_factory=lambda: self._execute_trade_command(signal_id),
        )
        self._runtime_repository.append_runtime_record(
            record_type="scheduler_run",
            record_id=signal_id,
            payload={
                "schedule_name": execution.schedule_name,
                "succeeded": execution.succeeded,
                "error": None if execution.error is None else str(execution.error),
            },
        )
        if execution.error is not None:
            runtime_logger.error(
                "dry-run trade execution failed",
                signal_id=signal_id,
                error=str(execution.error),
            )
            raise execution.error
        if execution.result is None:
            error = RuntimeError("dry-run trade execution did not return a result")
            runtime_logger.error("dry-run trade execution failed", error=str(error))
            raise error
        self._last_trade_execution_result = execution.result
        runtime_logger.info(
            "dry-run trade execution succeeded",
            signal_id=signal_id,
            status=execution.result.status.value,
            order_status=(
                None
                if execution.result.order_result is None
                else execution.result.order_result.status.value
            ),
        )
        return execution.result

    def create_app(self) -> FastAPI:
        return create_app(
            health_provider=self.health_details,
            readiness_provider=self.readiness_details,
            status_provider=self.status_details,
            trade_router=(
                create_trade_router(
                    execute_trade_usecase=_RuntimeExecuteTradeBoundary(self),
                    execute_trade_command_factory=_trade_payload_to_signal_id,
                )
                if self.settings.mode is RuntimeMode.DRY_RUN
                else None
            ),
        )

    def _execute_trade_command(self, signal_id: str) -> ExecuteTradeCommand:
        signal_id = signal_id.strip()
        if not signal_id:
            runtime_logger.error("execute trade command rejected", error="signal_id is required")
            raise ValueError("signal_id is required")
        symbol = parse_symbol(self.settings.symbol)
        timeframe = parse_timeframe(self.settings.timeframe)
        market = _LocalCatalogMarketData().load_snapshot(
            symbol=symbol,
            timeframe=timeframe,
            limit=self.settings.candle_limit,
        )
        return ExecuteTradeCommand(
            symbol=symbol,
            timeframe=timeframe,
            candle_limit=self.settings.candle_limit,
            indicators=build_local_indicator_set(market),
            exposure_limit=ExposureLimit(
                equity=Decimal("10000"),
                current_total_exposure=Decimal("0"),
                current_symbol_exposure=Decimal("0"),
                max_total_exposure_ratio=Decimal("1"),
                max_symbol_exposure_ratio=Decimal("1"),
            ),
            base_risk_ratio=Decimal("0.01"),
            leverage=Decimal("1"),
            client_order_id_prefix=self.settings.client_order_id_prefix,
            signal_id=signal_id,
            generator_id=self.settings.generator_id,
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


class _DryRunOrderExecution:
    def __init__(self, runtime_repository: SqliteRuntimeStateRepository) -> None:
        self._runtime_repository = runtime_repository

    def submit_order(self, request: OrderRequest) -> OrderResult:
        runtime_logger.info(
            "dry-run order recording started",
            client_order_id=request.client_order_id,
            symbol=request.symbol.pair,
            side=request.side.value,
            quantity=str(request.quantity),
            reduce_only=request.reduce_only,
        )
        self._runtime_repository.append_runtime_record(
            record_type="dry_run_order",
            record_id=request.client_order_id,
            payload={
                "client_order_id": request.client_order_id,
                "symbol": request.symbol.pair,
                "side": request.side.value,
                "order_type": request.order_type.value,
                "quantity": str(request.quantity),
                "reduce_only": request.reduce_only,
            },
        )
        result = OrderResult.accepted(
            client_order_id=request.client_order_id,
            exchange_order_id=f"dry-run-{request.client_order_id}",
        )
        runtime_logger.info(
            "dry-run order recorded",
            client_order_id=request.client_order_id,
            order_status=result.status.value,
        )
        return result

    def load_execution_reports(self, symbol, since, until):
        return ()

    def submit_take_profit_stop_loss_orders(
        self,
        symbol,
        position_direction,
        take_profit,
        stop_loss,
        client_order_id_prefix,
    ):
        close_side = (
            SignalDirection.SHORT
            if position_direction is SignalDirection.LONG
            else SignalDirection.LONG
        )
        take_profit_request = OrderRequest.take_profit_market(
            client_order_id=f"{client_order_id_prefix}-tp",
            symbol=symbol,
            side=close_side,
            stop_price=take_profit,
        )
        stop_loss_request = OrderRequest.stop_market(
            client_order_id=f"{client_order_id_prefix}-sl",
            symbol=symbol,
            side=close_side,
            stop_price=stop_loss,
        )
        return (
            self.submit_order(take_profit_request),
            self.submit_order(stop_loss_request),
        )


class _RuntimeExecuteTradeBoundary:
    def __init__(self, runtime: LocalRuntime) -> None:
        self._runtime = runtime

    def execute(self, signal_id: str) -> ExecuteTradeResult:
        return self._runtime.run_trade_execution_once(signal_id)


def _trade_payload_to_signal_id(payload: Mapping[str, object]) -> str:
    signal_id = payload.get("signal_id", "")
    return str(signal_id)


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


def _runtime_status(settings: RuntimeSettings) -> RuntimeStatus:
    if settings.mode is RuntimeMode.DRY_RUN:
        return RuntimeStatus(
            settings=settings,
            started_at=datetime.now(timezone.utc),
            dependencies=(
                RuntimeDependency(
                    "exchange",
                    "dry-run",
                    "orders are recorded locally and not submitted",
                ),
                RuntimeDependency("persistence", "sqlite", settings.database_url),
                RuntimeDependency("scheduler", "ready", "manual trigger available"),
                RuntimeDependency("websocket", "not_started", "listener not attached"),
            ),
        )
    return RuntimeStatus.local(settings)


def _sqlite_path_from_url(database_url: str) -> str:
    if database_url.startswith("sqlite:///"):
        parsed = urlparse(database_url)
        path = unquote(parsed.path)
        if parsed.netloc:
            path = f"//{parsed.netloc}{path}"
        if len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        elif path.startswith("/./") or path.startswith("/../"):
            path = path[1:]
        _ensure_parent_directory(path)
        return path
    if database_url.startswith("sqlite://"):
        raise ValueError("sqlite database URL must use sqlite:///path")
    _ensure_parent_directory(database_url)
    return str(Path(database_url))


def _ensure_parent_directory(database_path: str) -> None:
    parent = Path(database_path).parent
    if str(parent) not in {"", "."}:
        parent.mkdir(parents=True, exist_ok=True)
