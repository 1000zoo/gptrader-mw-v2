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
from src.application.usecases.regime import SelectStrategyUseCase
from src.domain.regime import (
    CHART_FEATURE_SCHEMA_VERSION,
    SelectionArtifactSnapshot,
)
from src.domain.execution import OrderRequest, OrderResult
from src.domain.lifecycle import (
    SignalGeneratorDefinition,
    StrategyDefinition,
    StrategyEvaluation,
)
from src.domain.market import Candle, MarketSnapshot
from src.domain.risk import (
    ConfidencePositionSizingStrategy,
    ExposureLimit,
    FixedPositionSizingStrategy,
)
from src.domain.signal import SignalDirection
from src.domain.signal_generator import CompositeSignalGenerator
from src.infrastructure.persistence import (
    SqliteRegimeSelectionStateRepository,
    SqliteRuntimeStateRepository,
    SqliteSignalLogRepository,
)
from src.infrastructure.regime import (
    JsonRegimeArtifactRepository,
    mapping_artifact_hash,
    model_artifact_hash,
    model_fingerprint_hash,
    validate_model_mapping_artifact_pair,
)
from src.interfaces.api import create_app
from src.interfaces.api.trade_controller import create_trade_router
from src.interfaces.scheduler import (
    RegimeSelectionScheduler,
    StrategyLifecycleScheduler,
    TradeScheduler,
)
from src.domain.strategy.implementations import (
    AtrTakeProfitStopLossStrategy,
    FixedRatioTakeProfitStopLossStrategy,
    create_default_strategy_catalog,
)
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.market_data import BinanceMarketDataAdapter
from src.infrastructure.exchange.binance.order_execution import BinanceOrderExecutionAdapter
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
        self._regime_selection_scheduler = None
        self._regime_selection_snapshot = None
        self._regime_model_artifact = None
        self._regime_mapping_artifact = None
        if self.settings.regime_selection_enabled:
            self._compose_regime_selection(database_path)
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
        market_data = _market_data_for_mode(self.settings)
        self._market_data = market_data
        take_profit_stop_loss_strategy = _take_profit_stop_loss_strategy(self.settings)
        self._take_profit_stop_loss_strategy = take_profit_stop_loss_strategy
        position_sizing_strategy = _position_sizing_strategy(self.settings)
        self._position_sizing_strategy = position_sizing_strategy
        dry_run_order_execution = _DryRunOrderExecution(
            runtime_repository=self._runtime_repository
        )
        order_execution = _order_execution_for_mode(
            self.settings,
            dry_run_order_execution,
        )
        self._order_execution = order_execution
        active_strategy = strategy_catalog.create_strategy(
            next(
                spec
                for spec in strategy_catalog.list_specs()
                if spec.strategy_id == self.settings.trading_strategy_id
            )
        )
        self._strategy_scheduler = StrategyLifecycleScheduler(
            run_strategy_lifecycle_usecase=RunStrategyLifecycleUseCase(
                self._strategy_repository
            ),
            run_strategy_backtest_cycle_usecase=RunStrategyBacktestCycleUseCase(
                strategy_repository=self._strategy_repository,
                market_data=market_data,
                strategy_catalog=strategy_catalog,
                take_profit_stop_loss_strategy=take_profit_stop_loss_strategy,
                position_sizing_strategy=position_sizing_strategy,
            ),
        )
        self._trade_scheduler = TradeScheduler(
            execute_trade_usecase=ExecuteTradeUseCase(
                market_data=market_data,
                signal_generator=CompositeSignalGenerator(
                    strategies=(active_strategy,)
                ),
                signal_log_repository=signal_log_repository,
                order_execution=order_execution,
                take_profit_stop_loss_strategy=take_profit_stop_loss_strategy,
                position_sizing_strategy=position_sizing_strategy,
            ),
            close_position_usecase=ClosePositionUseCase(order_execution),
            sync_position_usecase=SyncPositionUseCase(order_execution),
            manage_open_position_usecase=ManageOpenPositionUseCase(
                market_data=market_data,
                signal_generator=CompositeSignalGenerator(
                    strategies=(active_strategy,)
                ),
                signal_log_repository=signal_log_repository,
                close_position_usecase=ClosePositionUseCase(order_execution),
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

    @property
    def regime_selection_scheduler(self) -> RegimeSelectionScheduler | None:
        return self._regime_selection_scheduler

    @property
    def regime_selection_snapshot(self) -> SelectionArtifactSnapshot | None:
        return self._regime_selection_snapshot

    @property
    def regime_model_artifact(self):
        return self._regime_model_artifact

    @property
    def regime_mapping_artifact(self):
        return self._regime_mapping_artifact

    def _compose_regime_selection(self, database_path: str) -> None:
        model_path = _regime_artifact_file(
            self.settings.regime_model_artifact_path,
            expected_name="model.json",
            label="regime model artifact path",
        )
        mapping_path = _regime_artifact_file(
            self.settings.regime_mapping_artifact_path,
            expected_name="mapping.json",
            label="regime mapping artifact path",
        )
        model_repository = JsonRegimeArtifactRepository(model_path.parent)
        model = model_repository.load_model(
            expected_symbol=self.settings.symbol,
            expected_schema=CHART_FEATURE_SCHEMA_VERSION,
        )
        model_hash = model_artifact_hash(model)
        fingerprint_hash = model_fingerprint_hash(model)
        mapping_repository = JsonRegimeArtifactRepository(mapping_path.parent)
        mapping = mapping_repository.load_mapping(
            expected_candidate_definition_hash=(
                self.settings.regime_candidate_definition_hash
            ),
            expected_candidate_universe_hash=(
                self.settings.regime_candidate_universe_hash
            ),
            expected_data_provenance_hash=(
                self.settings.regime_data_provenance_hash
            ),
            expected_model_artifact_hash=model_hash,
            expected_model_fingerprint_hash=fingerprint_hash,
        )
        validate_model_mapping_artifact_pair(model, mapping)
        snapshot = SelectionArtifactSnapshot.from_mapping_artifact(
            mapping,
            mapping_artifact_hash=mapping_artifact_hash(mapping),
        )
        selection_repository = SqliteRegimeSelectionStateRepository(database_path)
        self._regime_model_artifact = model
        self._regime_mapping_artifact = mapping
        self._regime_selection_snapshot = snapshot
        self._regime_selection_scheduler = RegimeSelectionScheduler(
            SelectStrategyUseCase(), selection_repository
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
            "enabled"
            if self.settings.mode in {RuntimeMode.DRY_RUN, RuntimeMode.LIVE_ARMED}
            else "disabled"
        )
        details["live_order_path"] = (
            "enabled" if self.settings.mode is RuntimeMode.LIVE_ARMED else "disabled"
        )
        details["active_strategy_id"] = self.settings.trading_strategy_id
        details["take_profit_stop_loss"] = _take_profit_stop_loss_details(
            self.settings
        )
        details["position_sizing"] = _position_sizing_details(self.settings)
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
            command_factory=lambda: RunStrategyBacktestCycleCommand(
                cycle_id=cycle_id,
                enabled_strategy_ids=self.settings.backtest_strategy_ids,
                disabled_strategy_ids=self.settings.disabled_backtest_strategy_ids,
            ),
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
            "trade execution started",
            signal_id=signal_id,
            mode=self.settings.mode.value,
            symbol=self.settings.symbol,
            timeframe=self.settings.timeframe,
        )
        execution = self._trade_scheduler.run_trade_execution(
            schedule_name=(
                f"{self.settings.symbol}-{self.settings.timeframe}-"
                f"{self.settings.mode.value}"
            ),
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
                "trade execution failed",
                signal_id=signal_id,
                mode=self.settings.mode.value,
                error=str(execution.error),
            )
            raise execution.error
        if execution.result is None:
            error = RuntimeError("trade execution did not return a result")
            runtime_logger.error(
                "trade execution failed",
                mode=self.settings.mode.value,
                error=str(error),
            )
            raise error
        self._last_trade_execution_result = execution.result
        runtime_logger.info(
            "trade execution succeeded",
            signal_id=signal_id,
            mode=self.settings.mode.value,
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
                if self.settings.mode in {RuntimeMode.DRY_RUN, RuntimeMode.LIVE_ARMED}
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
        market = self._market_data.load_snapshot(
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
            base_risk_ratio=self.settings.min_equity_ratio,
            leverage=self.settings.min_leverage,
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


def _market_data_for_mode(settings: RuntimeSettings):
    if settings.mode in {RuntimeMode.TESTNET, RuntimeMode.LIVE_ARMED}:
        return BinanceMarketDataAdapter(_binance_config_for_mode(settings))
    return _LocalCatalogMarketData()


def _order_execution_for_mode(
    settings: RuntimeSettings,
    dry_run_order_execution: _DryRunOrderExecution,
):
    if settings.mode is RuntimeMode.LIVE_ARMED:
        return BinanceOrderExecutionAdapter(_binance_config_for_mode(settings))
    return dry_run_order_execution


def _binance_config_for_mode(settings: RuntimeSettings) -> BinanceConfig:
    if settings.mode is RuntimeMode.TESTNET:
        return BinanceConfig.from_env()
    return BinanceConfig.from_env()


def _take_profit_stop_loss_strategy(settings: RuntimeSettings):
    if settings.take_profit_stop_loss == "fixed":
        return FixedRatioTakeProfitStopLossStrategy(
            stop_loss_ratio=settings.stop_loss_ratio,
            reward_risk_ratio=settings.reward_risk_ratio,
        )
    return AtrTakeProfitStopLossStrategy(atr_period=3)


def _position_sizing_strategy(settings: RuntimeSettings):
    if settings.position_sizing == "fixed":
        return FixedPositionSizingStrategy(
            equity_ratio=settings.fixed_equity_ratio,
            leverage=settings.fixed_leverage,
        )
    return ConfidencePositionSizingStrategy(
        min_equity_ratio=settings.min_equity_ratio,
        max_equity_ratio=settings.max_equity_ratio,
        min_leverage=settings.min_leverage,
        max_leverage=settings.max_leverage,
    )


def _take_profit_stop_loss_details(settings: RuntimeSettings) -> dict[str, str]:
    if settings.take_profit_stop_loss == "fixed":
        return {
            "kind": "fixed",
            "stop_loss_ratio": str(settings.stop_loss_ratio),
            "reward_risk_ratio": str(settings.reward_risk_ratio),
        }
    return {"kind": "atr"}


def _position_sizing_details(settings: RuntimeSettings) -> dict[str, str]:
    if settings.position_sizing == "fixed":
        return {
            "kind": "fixed",
            "equity_ratio": str(settings.fixed_equity_ratio),
            "leverage": str(settings.fixed_leverage),
        }
    return {
        "kind": "confidence",
        "min_equity_ratio": str(settings.min_equity_ratio),
        "max_equity_ratio": str(settings.max_equity_ratio),
        "min_leverage": str(settings.min_leverage),
        "max_leverage": str(settings.max_leverage),
    }


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


def _regime_artifact_file(
    value: str | None,
    *,
    expected_name: str,
    label: str,
) -> Path:
    if value is None:
        raise ValueError(f"{label} is required")
    path = Path(value).expanduser().resolve()
    if path.name != expected_name:
        raise ValueError(f"{label} must point to {expected_name}")
    if not path.is_file():
        raise ValueError(f"{label} must point to an existing file")
    return path


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
