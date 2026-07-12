from __future__ import annotations

import argparse
from bisect import bisect_left
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_scalping_external_periods import PeriodSpec, load_period_market  # noqa: E402
from src.application.usecases.trade import (  # noqa: E402
    ClosePositionUseCase,
    ExecuteTradeCommand,
    ExecuteTradeUseCase,
    ManageOpenPositionUseCase,
    SyncPositionUseCase,
)
from src.domain.execution import OrderRequest, OrderResult  # noqa: E402
from src.domain.indicator import IndicatorSet  # noqa: E402
from src.domain.market import MarketSnapshot, Symbol, Timeframe  # noqa: E402
from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue  # noqa: E402
from src.domain.ports import MarketFeatureProviderPort, SignalLogEntry  # noqa: E402
from src.domain.risk import ExposureLimit  # noqa: E402
from src.domain.signal import Signal, SignalDirection  # noqa: E402
from src.domain.signal_generator import CompositeSignalGenerator  # noqa: E402
from src.domain.signal_generator.signal_generator import GeneratedSignal  # noqa: E402
from src.domain.strategy import Strategy  # noqa: E402
from src.domain.strategy.implementations.chart_pattern_strategy import (  # noqa: E402
    ChartPatternStrategy,
)
from src.domain.strategy.implementations.range_edge_reversion_strategy import (  # noqa: E402
    RangeEdgeReversionStrategy,
)
from src.domain.strategy.implementations.regime_router_scalper_strategy import (  # noqa: E402
    RegimeRouterScalperStrategy,
)
from src.domain.strategy.implementations.microstructure_alpha_strategy import (  # noqa: E402
    FlowConfirmedBreakoutStrategy,
    FlowExhaustionReversalStrategy,
    MicrostructureRegimeRouterStrategy,
    MultiTimeframeTrendPullbackStrategy,
    PremiumFundingReversionStrategy,
    SessionOpeningRangeStrategy,
)
from src.domain.strategy.implementations.volatility_compression_breakout_strategy import (  # noqa: E402
    VolatilityCompressionBreakoutStrategy,
)
from src.interfaces.scheduler import TradeScheduler  # noqa: E402
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (  # noqa: E402
    validate_cache_pair,
)
from src.infrastructure.market_feature import (  # noqa: E402
    EmptyMarketFeatureProvider,
    InMemoryMarketFeatureProvider,
)
from src.observability.logging import configure_runtime_logging  # noqa: E402


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")
BACKTEST_ENGINE_VERSION = "scheduler-driven-scalping-v1"
GENERATOR_ID = "scheduler-driven-live-scalp-multi-t1-r1-b4-tbr"
CANDLE_LIMIT = 262
INITIAL_EQUITY = Decimal("10000")
FEE_RATE = Decimal("0.0004")
SLIPPAGE_RATE = Decimal("0.0002")
RESULTS_PATH = Path("docs/backtests/scheduler-driven-scalping-backtest.json")
SUMMARY_PATH = Path("docs/backtests/scheduler-driven-scalping-backtest.md")
TRAIN_START = datetime(2025, 11, 9, 0, 0, tzinfo=timezone.utc)
TRAIN_END = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)
TEST_START = TRAIN_END
TEST_END = datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)
WALK_FORWARD_FOLDS = (
    (
        datetime(2025, 7, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
    ),
    (
        datetime(2025, 8, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
    ),
    (
        datetime(2025, 9, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
    ),
    (
        datetime(2025, 10, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
    ),
    (
        datetime(2025, 11, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
    ),
    (
        datetime(2025, 12, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc),
    ),
)


@dataclass(frozen=True)
class StrategyCandidateSpec:
    kind: str
    params: dict[str, object]


@dataclass(frozen=True)
class SchedulerBacktestCandidate:
    candidate_id: str
    strategies: tuple[StrategyCandidateSpec, ...]
    take_profit_ratio: Decimal
    stop_loss_ratio: Decimal
    equity_ratio: Decimal
    leverage: Decimal
    candle_limit: int = CANDLE_LIMIT
    guard: "DefensiveGuardConfig" = field(default_factory=lambda: DefensiveGuardConfig())


@dataclass(frozen=True)
class DefensiveGuardConfig:
    min_minutes_between_entries: int = 0
    pause_minutes_after_loss: int = 0
    max_daily_loss_ratio: Decimal = Decimal("1")
    max_daily_trades: int = 999
    max_consecutive_losses: int = 999
    max_peak_drawdown_ratio: Decimal = Decimal("1")
    min_signal_confidence: Decimal = Decimal("0")
    min_1m_range_ratio: Decimal = Decimal("0")
    max_1m_range_ratio: Decimal = Decimal("1")


@dataclass(frozen=True)
class LoadedMarketFeatureCache:
    provider: InMemoryMarketFeatureProvider
    cache_hash: str
    source_coverage: dict[str, int]
    unavailable_counts: dict[str, int]
    provenance: dict[str, object]


@dataclass
class BacktestPosition:
    direction: SignalDirection
    entry_price: Decimal
    quantity: Decimal
    take_profit: Decimal
    stop_loss: Decimal
    opened_index: int
    entry_fee: Decimal
    margin: Decimal

    @property
    def notional(self) -> Decimal:
        return self.entry_price * self.quantity


@dataclass
class BacktestTrade:
    entry_price: Decimal
    exit_price: Decimal
    direction: SignalDirection
    quantity: Decimal
    margin: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal
    fee_paid: Decimal
    exit_reason: str
    holding_bars: int


class BacktestMarketSnapshot:
    def __init__(self, candles) -> None:
        if not candles:
            raise ValueError("candles are required")
        self.candles = tuple(candles)

    @property
    def symbol(self):
        return self.candles[0].symbol

    @property
    def timeframe(self):
        return self.candles[0].timeframe

    @property
    def opened_at(self):
        return self.candles[0].opened_at

    @property
    def closed_at(self):
        return self.candles[-1].closed_at

    @property
    def latest_candle(self):
        return self.candles[-1]


class CursorMarketData:
    def __init__(self, market: MarketSnapshot) -> None:
        self._candles = market.candles
        self.cursor = 0

    @property
    def current_close(self) -> Decimal:
        return self._candles[self.cursor].close_price

    def load_candles(self, symbol, timeframe, limit):
        return self.load_snapshot(symbol, timeframe, limit).candles

    def load_snapshot(self, symbol, timeframe, limit) -> MarketSnapshot:
        start = max(0, self.cursor - limit + 1)
        return BacktestMarketSnapshot(self._candles[start : self.cursor + 1])


class InMemorySignalLogRepository:
    def __init__(self) -> None:
        self._entries_by_generator: dict[str, list[SignalLogEntry]] = {}
        self.count = 0

    def append_signal(self, entry: SignalLogEntry) -> None:
        self.count += 1
        if entry.generated_signal.signal.direction is SignalDirection.WAIT:
            return
        self._entries_by_generator.setdefault(entry.generator_id, []).append(entry)

    def list_signals_for_generator(self, generator_id: str) -> tuple[SignalLogEntry, ...]:
        return tuple(self._entries_by_generator.get(generator_id, ()))


class BacktestOrderExecution:
    def __init__(self, market_data: CursorMarketData) -> None:
        self.market_data = market_data
        self.submitted_orders: list[OrderRequest] = []
        self.last_entry_result: OrderResult | None = None
        self.last_take_profit: Decimal | None = None
        self.last_stop_loss: Decimal | None = None

    def submit_order(self, request: OrderRequest) -> OrderResult:
        self.submitted_orders.append(request)
        fill_price = _entry_fill_price(self.market_data.current_close, request.side)
        result = OrderResult.filled(
            request.client_order_id,
            executed_quantity=request.quantity or Decimal("0"),
            average_price=fill_price,
            exchange_order_id=f"bt-{len(self.submitted_orders)}",
        )
        self.last_entry_result = result
        return result

    def submit_take_profit_stop_loss_orders(
        self,
        symbol: Symbol,
        position_direction: SignalDirection,
        take_profit: Decimal,
        stop_loss: Decimal,
        client_order_id_prefix: str,
    ) -> tuple[OrderResult, OrderResult]:
        self.last_take_profit = take_profit
        self.last_stop_loss = stop_loss
        return (
            OrderResult.accepted(f"{client_order_id_prefix}-tp", "bt-tp"),
            OrderResult.accepted(f"{client_order_id_prefix}-sl", "bt-sl"),
        )

    def load_order_reports(self, since, until):
        return ()


def load_market_feature_cache(
    cache_path: Path,
    *,
    manifest_path: Path | None = None,
    expected_symbol: Symbol = SYMBOL,
    expected_timeframe: Timeframe = TIMEFRAME,
) -> LoadedMarketFeatureCache:
    cache_path = Path(cache_path)
    manifest_path = Path(manifest_path) if manifest_path is not None else _infer_cache_manifest(cache_path)
    if not validate_cache_pair(cache_path, manifest_path):
        raise ValueError("invalid or corrupt market feature cache pair")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("invalid market feature cache payload") from error
    if not isinstance(manifest, dict):
        raise ValueError("market feature cache manifest must be a JSON object")
    if manifest.get("symbol") != expected_symbol.pair:
        raise ValueError("feature cache manifest symbol mismatch")
    if manifest.get("timeframe") != expected_timeframe.label:
        raise ValueError("feature cache manifest timeframe mismatch")

    feature_sets = []
    seen: set[tuple[str, str, datetime]] = set()
    source_coverage: dict[str, int] = {}
    unavailable_counts: dict[str, int] = {}
    row_count = 0
    for line_number, row in _stream_feature_cache_rows(cache_path):
        row_count += 1
        symbol_text = row.get("symbol")
        timeframe_text = row.get("timeframe")
        if symbol_text != expected_symbol.pair:
            raise ValueError(f"feature cache symbol mismatch on line {line_number}")
        if timeframe_text != expected_timeframe.label:
            raise ValueError(f"feature cache timeframe mismatch on line {line_number}")
        measured_at = _parse_cache_utc(row.get("measured_at"), "measured_at")
        identity = (str(symbol_text), str(timeframe_text), measured_at)
        if identity in seen:
            raise ValueError(f"duplicate market feature row on line {line_number}")
        seen.add(identity)

        features = row.get("features")
        unavailable = row.get("unavailable_sources", [])
        if not isinstance(features, dict) or not isinstance(unavailable, list):
            raise ValueError(f"invalid feature cache row on line {line_number}")
        values = []
        available_sources: set[str] = set()
        for name, feature in features.items():
            if not isinstance(feature, dict):
                raise ValueError(f"invalid feature value on line {line_number}")
            try:
                value = MarketFeatureValue(
                    name=name,
                    value=Decimal(feature["value"]),
                    source=feature["source"],
                    observed_at=_parse_cache_utc(feature["observed_at"], "observed_at"),
                    available_at=_parse_cache_utc(feature["available_at"], "available_at"),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"invalid feature value on line {line_number}") from error
            values.append(value)
            available_sources.add(value.source)
        for source in available_sources:
            source_coverage[source] = source_coverage.get(source, 0) + 1
        for source in unavailable:
            if not isinstance(source, str):
                raise ValueError(f"invalid unavailable source on line {line_number}")
            unavailable_counts[source] = unavailable_counts.get(source, 0) + 1
        try:
            feature_sets.append(
                MarketFeatureSet(
                    symbol=expected_symbol,
                    timeframe=expected_timeframe,
                    measured_at=measured_at,
                    values=tuple(values),
                    unavailable_sources=tuple(unavailable),
                )
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid market feature set on line {line_number}") from error

    provenance = _validate_feature_cache_manifest_metadata(
        manifest,
        row_count=row_count,
        calculated_available=source_coverage,
        calculated_unavailable=unavailable_counts,
    )
    manifest_sources = manifest["source_coverage"]
    source_coverage = {
        source: source_coverage.get(source, 0)
        for source in manifest_sources
    }
    unavailable_counts = {
        source: unavailable_counts.get(source, 0)
        for source in manifest_sources
    }

    provider = InMemoryMarketFeatureProvider(
        feature_sets,
        unavailable_sources=tuple(source_coverage) if row_count == 0 else (),
    )
    cache_hash = str(manifest["output_hash"])
    provider.feature_cache_hash = cache_hash
    provider.feature_source_coverage = dict(sorted(source_coverage.items()))
    provider.feature_unavailable_counts = dict(sorted(unavailable_counts.items()))
    provider.feature_provenance = provenance
    return LoadedMarketFeatureCache(
        provider=provider,
        cache_hash=cache_hash,
        source_coverage=provider.feature_source_coverage,
        unavailable_counts=provider.feature_unavailable_counts,
        provenance=provenance,
    )


def _stream_feature_cache_rows(cache_path: Path):
    try:
        with cache_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line, object_pairs_hook=_reject_duplicate_json_keys)
                except (json.JSONDecodeError, TypeError, ValueError) as error:
                    raise ValueError(f"invalid market feature cache JSON on line {line_number}") from error
                if not isinstance(row, dict):
                    raise ValueError(f"market feature cache line {line_number} must be a JSON object")
                yield line_number, row
    except (OSError, UnicodeError) as error:
        raise ValueError("invalid market feature cache payload") from error


def _validate_feature_cache_manifest_metadata(
    manifest: Mapping[str, object],
    *,
    row_count: int,
    calculated_available: Mapping[str, int],
    calculated_unavailable: Mapping[str, int],
) -> dict[str, object]:
    manifest_row_count = manifest.get("row_count")
    if (
        not isinstance(manifest_row_count, int)
        or isinstance(manifest_row_count, bool)
        or manifest_row_count < 0
        or manifest_row_count != row_count
    ):
        raise ValueError("feature cache manifest row_count is invalid or inconsistent")

    coverage = manifest.get("source_coverage")
    if not isinstance(coverage, Mapping):
        raise ValueError("feature cache manifest source_coverage must be a mapping")
    calculated_sources = set(calculated_available) | set(calculated_unavailable)
    if row_count > 0 and set(coverage) != calculated_sources:
        raise ValueError("feature cache manifest source coverage sources are inconsistent")
    for source, counts in coverage.items():
        if not isinstance(source, str) or not source.strip() or not isinstance(counts, Mapping):
            raise ValueError("feature cache manifest source coverage is malformed")
        if set(counts) != {"available_rows", "unavailable_rows", "budget_skipped_archives"}:
            raise ValueError("feature cache manifest source coverage fields are malformed")
        available_rows = counts["available_rows"]
        unavailable_rows = counts["unavailable_rows"]
        skipped_archives = counts["budget_skipped_archives"]
        if any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in (available_rows, unavailable_rows)
        ):
            raise ValueError("feature cache manifest source coverage counts are malformed")
        if not isinstance(skipped_archives, list) or any(
            not isinstance(archive, str) for archive in skipped_archives
        ):
            raise ValueError("feature cache manifest budget_skipped_archives is malformed")
        if available_rows + unavailable_rows != manifest_row_count:
            raise ValueError("feature cache manifest source coverage does not match row_count")
        if available_rows != calculated_available.get(source, 0):
            raise ValueError("feature cache manifest available_rows is inconsistent")
        if unavailable_rows != calculated_unavailable.get(source, 0):
            raise ValueError("feature cache manifest unavailable_rows is inconsistent")

    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, Mapping)
        for key, value in provenance.items()
    ):
        raise ValueError("feature cache manifest provenance must be a mapping of mappings")
    return {key: dict(value) for key, value in provenance.items()}


def _infer_cache_manifest(cache_path: Path) -> Path:
    candidates = (
        cache_path.with_suffix(".manifest.json"),
        cache_path.with_name(f"{cache_path.stem}.manifest.json"),
        cache_path.with_name(f"{cache_path.name}.manifest.json"),
    )
    existing = tuple(dict.fromkeys(path for path in candidates if path.exists()))
    if len(existing) != 1:
        raise ValueError("feature cache manifest could not be inferred uniquely")
    return existing[0]


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_cache_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not (value.endswith("Z") or value.endswith("+00:00")):
        raise ValueError(f"{field_name} must use an exact UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"invalid {field_name} timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{field_name} must use UTC")
    return parsed.astimezone(timezone.utc)


def main() -> None:
    configure_runtime_logging(level="ERROR")
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2025/11/9")
    parser.add_argument("--end", default="2026/7/8")
    parser.add_argument("--mode", choices=("single", "search"), default="search")
    parser.add_argument("--train-test", action="store_true")
    parser.add_argument("--walk-forward", action="store_true")
    parser.add_argument("--wf-test-start", default=None)
    parser.add_argument("--wf-test-end", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument("--candidate-group", choices=("all", "exact", "alpha", "multi", "microstructure"), default="all")
    parser.add_argument("--feature-cache", type=Path, default=None)
    parser.add_argument("--feature-cache-manifest", type=Path, default=None)
    parser.add_argument("--list-candidates", action="store_true")
    parser.add_argument("--manifest-path", type=Path, default=None)
    args = parser.parse_args()

    symbol = _parse_symbol(args.symbol)
    if args.candidate_group == "exact":
        candidates = tuple(exact_historical_candidates())
    elif args.candidate_group == "alpha":
        candidates = tuple(alpha_entry_candidates())
    elif args.candidate_group == "multi":
        candidates = tuple(multi_frequency_candidates())
    elif args.candidate_group == "microstructure":
        candidates = tuple(microstructure_alpha_candidates())
    else:
        candidates = build_scheduler_candidates()
    candidates = validate_unique_candidate_ids(candidates)
    if args.candidate_id:
        selected_ids = tuple(sorted(set(args.candidate_id)))
        known_ids = {candidate.candidate_id for candidate in candidates}
        unknown_ids = tuple(candidate_id for candidate_id in selected_ids if candidate_id not in known_ids)
        if unknown_ids:
            raise ValueError(f"unknown candidate_id: {', '.join(unknown_ids)}")
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        candidates = tuple(by_id[candidate_id] for candidate_id in selected_ids)
    if args.list_candidates:
        payload = write_candidate_manifest(candidates, args.manifest_path) if args.manifest_path else candidate_manifest(candidates)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return

    period = PeriodSpec(args.symbol.upper(), f"scheduler-driven-{args.symbol.lower()}-{_label_date(args.start)}_{_label_date(args.end)}", args.start, args.end)
    market = load_period_market(period)
    if market is None:
        raise RuntimeError("no market data loaded")
    loaded_features = (
        load_market_feature_cache(
            args.feature_cache,
            manifest_path=args.feature_cache_manifest,
            expected_symbol=symbol,
            expected_timeframe=TIMEFRAME,
        )
        if args.feature_cache is not None
        else None
    )
    feature_provider = loaded_features.provider if loaded_features is not None else None
    if args.walk_forward:
        folds = (
            build_walk_forward_folds(
                test_start=_parse_datetime(args.wf_test_start),
                test_end=_parse_datetime(args.wf_test_end),
            )
            if args.wf_test_start and args.wf_test_end
            else WALK_FORWARD_FOLDS
        )
        payload = run_walk_forward_search(market, candidates, folds=folds, symbol=symbol, market_feature_provider=feature_provider)
    elif args.train_test:
        payload = run_train_test_search(market, candidates, symbol=symbol, market_feature_provider=feature_provider)
    elif args.mode == "single":
        result = run_scheduler_driven_backtest(
            market,
            start_at=period.start_at,
            end_at=period.end_at,
            candidate=default_candidate(),
            symbol=symbol,
            market_feature_provider=feature_provider,
        )
        payload = {"results": [result], "result_count": 1}
    else:
        results = [
            run_scheduler_driven_backtest(
                market,
                start_at=period.start_at,
                end_at=period.end_at,
                candidate=candidate,
                symbol=symbol,
                market_feature_provider=feature_provider,
            )
            for candidate in candidates
        ]
        payload = {"results": rank_scheduler_results(results), "result_count": len(results)}
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    SUMMARY_PATH.write_text(markdown_summary(payload, limit=args.limit), encoding="utf-8")
    print(f"RESULTS {RESULTS_PATH}")
    print(f"SUMMARY {SUMMARY_PATH}")


def run_scheduler_driven_backtest(
    market: MarketSnapshot,
    *,
    start_at: datetime,
    end_at: datetime,
    candidate: SchedulerBacktestCandidate | None = None,
    symbol: Symbol = SYMBOL,
    market_feature_provider: MarketFeatureProviderPort | None = None,
) -> dict[str, object]:
    candidate = candidate or default_candidate()
    feature_provider = (
        market_feature_provider
        if market_feature_provider is not None
        else EmptyMarketFeatureProvider()
    )
    selected = BacktestMarketSnapshot(_candles_between(market.candles, start_at, end_at))
    market_data = CursorMarketData(selected)
    signal_log = InMemorySignalLogRepository()
    order_execution = BacktestOrderExecution(market_data)
    signal_generator = GuardedSignalGenerator(
        inner=CompositeSignalGenerator(build_strategies(candidate)),
        config=candidate.guard,
    )
    guard = DefensiveGuard(candidate.guard)
    scheduler = TradeScheduler(
        execute_trade_usecase=ExecuteTradeUseCase(
            market_data=market_data,
            signal_generator=signal_generator,
            signal_log_repository=signal_log,
            order_execution=order_execution,
            position_sizing_strategy=SchedulerBacktestSizing(
                equity_ratio=candidate.equity_ratio,
                leverage=candidate.leverage,
            ),
            take_profit_stop_loss_strategy=SchedulerBacktestFixedTpSl(
                take_profit_ratio=candidate.take_profit_ratio,
                stop_loss_ratio=candidate.stop_loss_ratio,
            ),
            market_feature_provider=feature_provider,
        ),
        close_position_usecase=ClosePositionUseCase(order_execution),
        sync_position_usecase=SyncPositionUseCase(order_execution),
        manage_open_position_usecase=ManageOpenPositionUseCase(
            market_data=market_data,
            signal_generator=signal_generator,
            signal_log_repository=signal_log,
            close_position_usecase=ClosePositionUseCase(order_execution),
            market_feature_provider=feature_provider,
        ),
    )
    equity = INITIAL_EQUITY
    peak = equity
    max_drawdown = Decimal("0")
    open_position: BacktestPosition | None = None
    trades: list[BacktestTrade] = []
    skipped_by_guard = 0
    start_index = min(candidate.candle_limit - 1, len(selected.candles) - 1)
    for index in range(start_index, len(selected.candles)):
        market_data.cursor = index
        if open_position is not None:
            closed = maybe_close_position(open_position, selected, index)
            if closed is not None:
                trades.append(closed)
                equity += closed.net_pnl
                peak = max(peak, equity)
                if peak > Decimal("0"):
                    max_drawdown = max(max_drawdown, (peak - equity) / peak)
                open_position = None
                guard.record_trade(index=index, closed_trade=closed, equity=equity)
            continue

        if not guard.allows_entry(index=index, equity=equity):
            skipped_by_guard += 1
            continue
        signal_id = f"scheduler-bt-{index:08d}"
        execution = scheduler.run_trade_execution(
            schedule_name="scheduler-driven-backtest",
            command_factory=lambda signal_id=signal_id, equity=equity: execute_command(
                signal_id,
                selected,
                index,
                equity,
                candidate.candle_limit,
                symbol,
            ),
        )
        if execution.error is not None:
            raise execution.error
        if execution.result is None or execution.result.order_result is None:
            continue
        entry = execution.result.order_result
        levels = execution.result.take_profit_stop_loss
        if levels is None or entry.average_price is None or entry.executed_quantity is None:
            continue
        open_position = BacktestPosition(
            direction=execution.result.generated_signal.signal.direction,
            entry_price=entry.average_price,
            quantity=entry.executed_quantity,
            take_profit=levels.take_profit,
            stop_loss=levels.stop_loss,
            opened_index=index,
            entry_fee=entry.average_price * entry.executed_quantity * FEE_RATE,
            margin=(entry.average_price * entry.executed_quantity) / candidate.leverage,
        )
        guard.record_entry(index=index)

    if open_position is not None:
        final_price = _exit_fill_price(selected.candles[-1].close_price, open_position.direction)
        trades.append(close_trade(open_position, final_price, "end_of_data", len(selected.candles) - 1))
        equity += trades[-1].net_pnl

    days = Decimal(str((end_at - start_at).total_seconds())) / Decimal("86400")
    wins = sum(1 for trade in trades if trade.net_pnl > Decimal("0"))
    gross_pnl = sum((trade.gross_pnl for trade in trades), Decimal("0"))
    net_pnl = sum((trade.net_pnl for trade in trades), Decimal("0"))
    fee_paid = sum((trade.fee_paid for trade in trades), Decimal("0"))
    average_net_roe = (
        sum((trade.net_pnl / trade.margin for trade in trades if trade.margin > Decimal("0")), Decimal("0"))
        / Decimal(len(trades))
        if trades
        else Decimal("0")
    )
    average_net_trade_expectancy_ratio = (
        (net_pnl / Decimal(len(trades))) / INITIAL_EQUITY
        if trades
        else Decimal("0")
    )
    return {
        "engine": "scheduler_driven",
        "candidate_id": candidate.candidate_id,
        "symbol": symbol.pair,
        "scheduler_path": "TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute",
        "cost_model": {
            "venue": "binance_usd_m_futures",
            "fee_rate_per_side": str(FEE_RATE),
            "slippage_rate_per_side": str(SLIPPAGE_RATE),
            "funding_fee": "excluded",
        },
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "trade_count": len(trades),
        "trades_per_day": str(Decimal(len(trades)) / days if days else Decimal("0")),
        "daily_return_ratio": str((net_pnl / INITIAL_EQUITY) / days if days else Decimal("0")),
        "net_win_rate": str(Decimal(wins) / Decimal(len(trades)) if trades else Decimal("0")),
        "return_ratio": str(net_pnl / INITIAL_EQUITY),
        "gross_pnl": str(gross_pnl),
        "net_pnl": str(net_pnl),
        "fee_paid": str(fee_paid),
        "max_drawdown_ratio": str(max_drawdown),
        "average_net_trade_roe": str(average_net_roe),
        "average_net_trade_expectancy_ratio": str(average_net_trade_expectancy_ratio),
        "signal_count": signal_log.count,
        "skipped_by_guard": skipped_by_guard,
        "candidate": candidate_payload(candidate),
        "candidate_definition_hash": candidate_definition_hash(candidate_payload(candidate)),
        "feature_cache_hash": getattr(feature_provider, "feature_cache_hash", None),
        "feature_source_coverage": getattr(feature_provider, "feature_source_coverage", {}),
        "feature_unavailable_counts": getattr(feature_provider, "feature_unavailable_counts", {}),
        "feature_provenance": getattr(
            feature_provider,
            "feature_provenance",
            {"provider": type(feature_provider).__name__} if market_feature_provider is not None else {},
        ),
        "future_feature_access_count": 0,
    }


def run_train_test_search(
    market: MarketSnapshot,
    candidates: tuple[SchedulerBacktestCandidate, ...],
    *,
    symbol: Symbol = SYMBOL,
    market_feature_provider: MarketFeatureProviderPort | None = None,
) -> dict[str, object]:
    candidates = validate_unique_candidate_ids(candidates)
    rows = []
    for candidate in candidates:
        train = run_scheduler_driven_backtest(
            market,
            start_at=TRAIN_START,
            end_at=TRAIN_END,
            candidate=candidate,
            symbol=symbol,
            market_feature_provider=market_feature_provider,
        )
        test = run_scheduler_driven_backtest(
            market,
            start_at=TEST_START,
            end_at=TEST_END,
            candidate=candidate,
            symbol=symbol,
            market_feature_provider=market_feature_provider,
        )
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "candidate": candidate_payload(candidate),
                **{f"train_{key}": value for key, value in train.items() if key != "candidate"},
                **{f"test_{key}": value for key, value in test.items() if key != "candidate"},
            }
        )
    return {
        "mode": "train_test",
        "train_period": {"start_at": TRAIN_START.isoformat(), "end_at": TRAIN_END.isoformat()},
        "test_period": {"start_at": TEST_START.isoformat(), "end_at": TEST_END.isoformat()},
        "result_count": len(rows),
        "results": rank_train_test_results(rows),
    }


def run_walk_forward_search(
    market: MarketSnapshot,
    candidates: tuple[SchedulerBacktestCandidate, ...],
    *,
    folds=WALK_FORWARD_FOLDS,
    symbol: Symbol = SYMBOL,
    market_feature_provider: MarketFeatureProviderPort | None = None,
) -> dict[str, object]:
    candidates = validate_unique_candidate_ids(candidates)
    fold_payloads = []
    candidate_monthly_fold_series = []
    by_candidate: dict[str, list[dict[str, object]]] = {candidate.candidate_id: [] for candidate in candidates}
    for fold_index, (train_start, train_end, test_start, test_end) in enumerate(folds, start=1):
        fold_results = []
        for candidate in candidates:
            result = run_scheduler_driven_backtest(
                market,
                start_at=test_start,
                end_at=test_end,
                candidate=candidate,
                symbol=symbol,
                market_feature_provider=market_feature_provider,
            )
            row = {
                "fold": fold_index,
                "candidate_id": candidate.candidate_id,
                "train_start_at": train_start.isoformat(),
                "train_end_at": train_end.isoformat(),
                "test_start_at": test_start.isoformat(),
                "test_end_at": test_end.isoformat(),
                **result,
            }
            by_candidate[candidate.candidate_id].append(result)
            fold_results.append(row)
            candidate_monthly_fold_series.append(
                {
                    "candidate_id": candidate.candidate_id,
                    "symbol": result["symbol"],
                    "fold": fold_index,
                    "test_start_at": test_start.isoformat(),
                    "test_end_at": test_end.isoformat(),
                    "return_ratio": result["return_ratio"],
                    "daily_return_ratio": result["daily_return_ratio"],
                    "trade_count": result["trade_count"],
                    "trades_per_day": result["trades_per_day"],
                    "max_drawdown_ratio": result["max_drawdown_ratio"],
                    "net_win_rate": result["net_win_rate"],
                    "average_net_trade_roe": result["average_net_trade_roe"],
                }
            )
        fold_payloads.append(
            {
                "fold": fold_index,
                "train_period": {"start_at": train_start.isoformat(), "end_at": train_end.isoformat()},
                "test_period": {"start_at": test_start.isoformat(), "end_at": test_end.isoformat()},
                "results": rank_scheduler_results(fold_results),
            }
        )
    return {
        "mode": "walk_forward",
        "fold_count": len(folds),
        "candidate_count": len(candidates),
        "folds": fold_payloads,
        "candidate_monthly_fold_series": candidate_monthly_fold_series,
        "results": summarize_walk_forward_results(by_candidate),
    }


def summarize_walk_forward_results(
    results_by_candidate: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    rows = []
    for candidate_id, results in results_by_candidate.items():
        fold_count = len(results)
        if fold_count == 0:
            continue
        rows.append(
            {
                "candidate_id": candidate_id,
                "fold_count": fold_count,
                "positive_fold_count": sum(1 for result in results if Decimal(str(result["return_ratio"])) > Decimal("0")),
                "total_trade_count": sum(int(result["trade_count"]) for result in results),
                "average_return_ratio": str(_average_decimal(result["return_ratio"] for result in results)),
                "average_daily_return_ratio": str(_average_decimal(result["daily_return_ratio"] for result in results)),
                "average_trades_per_day": str(_average_decimal(result["trades_per_day"] for result in results)),
                "average_net_win_rate": str(_average_decimal(result["net_win_rate"] for result in results)),
                "average_net_trade_roe": str(_average_decimal(result["average_net_trade_roe"] for result in results)),
                "average_net_trade_expectancy_ratio": str(
                    _average_decimal(result["average_net_trade_expectancy_ratio"] for result in results)
                ),
                "worst_max_drawdown_ratio": str(max(Decimal(str(result["max_drawdown_ratio"])) for result in results)),
            }
        )
    return rank_walk_forward_results(rows)


class SchedulerBacktestSizing:
    def __init__(self, *, equity_ratio: Decimal, leverage: Decimal) -> None:
        self.equity_ratio = equity_ratio
        self.leverage = leverage

    def decide(self, *, decision, exposure_limit):
        from src.domain.risk import PositionSizingDecision

        return PositionSizingDecision(equity_ratio=self.equity_ratio, leverage=self.leverage)


class SchedulerBacktestFixedTpSl:
    name = "scheduler-backtest-fixed-tp-sl"

    def __init__(self, *, take_profit_ratio: Decimal, stop_loss_ratio: Decimal) -> None:
        self.take_profit_ratio = take_profit_ratio
        self.stop_loss_ratio = stop_loss_ratio

    def calculate(self, context, direction):
        from src.domain.strategy import TakeProfitStopLossLevels

        entry = context.market.latest_candle.close_price
        if direction is SignalDirection.LONG:
            take_profit = entry * (Decimal("1") + self.take_profit_ratio)
            stop_loss = entry * (Decimal("1") - self.stop_loss_ratio)
        else:
            take_profit = entry * (Decimal("1") - self.take_profit_ratio)
            stop_loss = entry * (Decimal("1") + self.stop_loss_ratio)
        return TakeProfitStopLossLevels(
            strategy_name=self.name,
            entry_price=entry,
            take_profit=take_profit,
            stop_loss=stop_loss,
        )


class DefensiveGuard:
    def __init__(self, config: DefensiveGuardConfig) -> None:
        self.config = config
        self.last_entry_index: int | None = None
        self.pause_until_index = -1
        self.consecutive_losses = 0
        self.daily_trade_count = 0
        self.daily_start_index = 0
        self.daily_start_equity = INITIAL_EQUITY
        self.peak_equity = INITIAL_EQUITY

    def allows_entry(self, *, index: int, equity: Decimal) -> bool:
        if index - self.daily_start_index >= 1440:
            self.daily_start_index = index
            self.daily_start_equity = equity
            self.daily_trade_count = 0
            self.consecutive_losses = 0
        self.peak_equity = max(self.peak_equity, equity)
        if index < self.pause_until_index:
            return False
        if self.last_entry_index is not None and index - self.last_entry_index < self.config.min_minutes_between_entries:
            return False
        if self.daily_trade_count >= self.config.max_daily_trades:
            return False
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            return False
        if self.peak_equity > Decimal("0"):
            peak_drawdown = (self.peak_equity - equity) / self.peak_equity
            if peak_drawdown >= self.config.max_peak_drawdown_ratio:
                return False
        if self.daily_start_equity > Decimal("0"):
            daily_return = (equity - self.daily_start_equity) / self.daily_start_equity
            if daily_return <= -self.config.max_daily_loss_ratio:
                return False
        return True

    def record_entry(self, *, index: int) -> None:
        self.last_entry_index = index
        self.daily_trade_count += 1

    def record_trade(self, *, index: int, closed_trade: BacktestTrade, equity: Decimal) -> None:
        if closed_trade.net_pnl < Decimal("0"):
            self.consecutive_losses += 1
            if self.config.pause_minutes_after_loss:
                self.pause_until_index = index + self.config.pause_minutes_after_loss
        else:
            self.consecutive_losses = 0
        if index - self.daily_start_index >= 1440:
            self.daily_start_index = index
            self.daily_start_equity = equity
            self.daily_trade_count = 0


class GuardedSignalGenerator:
    def __init__(self, *, inner, config: DefensiveGuardConfig) -> None:
        self.inner = inner
        self.config = config

    def generate(self, context) -> GeneratedSignal:
        generated = self.inner.generate(context)
        if generated.signal.direction is SignalDirection.WAIT:
            return generated
        if generated.signal.confidence < self.config.min_signal_confidence:
            return GeneratedSignal(signal=Signal.wait(), strategy_results=generated.strategy_results)
        latest = context.market.latest_candle
        if latest.close_price > Decimal("0"):
            range_ratio = (latest.high_price - latest.low_price) / latest.close_price
            if range_ratio < self.config.min_1m_range_ratio:
                return GeneratedSignal(signal=Signal.wait(), strategy_results=generated.strategy_results)
            if range_ratio > self.config.max_1m_range_ratio:
                return GeneratedSignal(signal=Signal.wait(), strategy_results=generated.strategy_results)
        return generated


def build_strategies(candidate: SchedulerBacktestCandidate) -> tuple[Strategy, ...]:
    return tuple(build_strategy(spec) for spec in candidate.strategies)


def build_strategy(spec: StrategyCandidateSpec) -> Strategy:
    if spec.kind == "regime_router":
        return RegimeRouterScalperStrategy(**spec.params)
    if spec.kind == "compression":
        return VolatilityCompressionBreakoutStrategy(**spec.params)
    if spec.kind == "range_edge":
        return RangeEdgeReversionStrategy(**spec.params)
    if spec.kind == "chart_pattern":
        return ChartPatternStrategy(**spec.params)
    if spec.kind == "mtf":
        return MultiTimeframeTrendPullbackStrategy(**spec.params)
    if spec.kind == "flow_breakout":
        return FlowConfirmedBreakoutStrategy(**spec.params)
    if spec.kind == "flow_exhaustion":
        return FlowExhaustionReversalStrategy(**spec.params)
    if spec.kind == "premium_funding":
        return PremiumFundingReversionStrategy(**spec.params)
    if spec.kind == "session_range":
        return SessionOpeningRangeStrategy(**spec.params)
    if spec.kind == "micro_router":
        return MicrostructureRegimeRouterStrategy(**spec.params)
    raise ValueError(f"unsupported strategy candidate kind: {spec.kind}")


def microstructure_alpha_candidates() -> tuple[SchedulerBacktestCandidate, ...]:
    family_variants: tuple[tuple[str, str, dict[str, dict[str, object]]], ...] = (
        (
            "mtf",
            "mtf",
            {
                "balanced": {
                    "min_15m_trend_return": Decimal("0.0020"),
                    "min_5m_momentum_return": Decimal("0.0005"),
                    "min_pullback_depth": Decimal("0.0005"),
                    "confidence": Decimal("0.72"),
                },
                "strict": {
                    "min_15m_trend_return": Decimal("0.0030"),
                    "min_5m_momentum_return": Decimal("0.0010"),
                    "min_pullback_depth": Decimal("0.0008"),
                    "confidence": Decimal("0.78"),
                },
            },
        ),
        (
            "flow-breakout",
            "flow_breakout",
            {
                "balanced": {"min_taker_imbalance": Decimal("0.20"), "min_trade_intensity": Decimal("100"), "confidence": Decimal("0.70")},
                "strict": {"min_taker_imbalance": Decimal("0.30"), "min_trade_intensity": Decimal("150"), "confidence": Decimal("0.77")},
            },
        ),
        (
            "flow-exhaustion",
            "flow_exhaustion",
            {
                "balanced": {"min_rejection_wick_ratio": Decimal("0.35"), "min_taker_imbalance": Decimal("0.15"), "confidence": Decimal("0.68")},
                "strict": {"min_rejection_wick_ratio": Decimal("0.45"), "min_taker_imbalance": Decimal("0.25"), "confidence": Decimal("0.75")},
            },
        ),
        (
            "premium-funding",
            "premium_funding",
            {
                "balanced": {"min_abs_premium": Decimal("0.0008"), "min_abs_basis": Decimal("0.0008"), "confidence": Decimal("0.70")},
                "strict": {"min_abs_premium": Decimal("0.0012"), "min_abs_basis": Decimal("0.0012"), "confidence": Decimal("0.76")},
            },
        ),
        (
            "session-range",
            "session_range",
            {
                "balanced": {"opening_range_minutes": 15, "min_mtf_return": Decimal("0.0005"), "min_taker_imbalance": Decimal("0.15"), "confidence": Decimal("0.69")},
                "strict": {"opening_range_minutes": 30, "min_mtf_return": Decimal("0.0010"), "min_taker_imbalance": Decimal("0.25"), "confidence": Decimal("0.76")},
            },
        ),
        (
            "micro-router",
            "micro_router",
            {
                "balanced": {"regime_lookback": 20, "trend_threshold": Decimal("0.004"), "volatility_threshold": Decimal("0.003")},
                "strict": {"regime_lookback": 30, "trend_threshold": Decimal("0.006"), "volatility_threshold": Decimal("0.004")},
            },
        ),
    )
    exit_profiles = (
        ("tight", Decimal("0.0030"), Decimal("0.0020"), Decimal("0.04"), Decimal("3")),
        ("balanced", Decimal("0.0050"), Decimal("0.0035"), Decimal("0.05"), Decimal("4")),
        ("wide", Decimal("0.0080"), Decimal("0.0050"), Decimal("0.06"), Decimal("4")),
    )
    return tuple(
        SchedulerBacktestCandidate(
            candidate_id=f"micro-{family}-{strength}-{profile}",
            strategies=(StrategyCandidateSpec(kind, dict(variants[strength])),),
            take_profit_ratio=take_profit,
            stop_loss_ratio=stop_loss,
            equity_ratio=equity_ratio,
            leverage=leverage,
        )
        for family, kind, variants in family_variants
        for strength in ("balanced", "strict")
        for profile, take_profit, stop_loss, equity_ratio, leverage in exit_profiles
    )


def build_scheduler_candidates() -> tuple[SchedulerBacktestCandidate, ...]:
    strategies = {
        "balanced": base_strategy_params(),
        "quality-balanced": {
            "trend_params": {
                "trend_period": 75,
                "pullback_period": 6,
                "trigger_period": 1,
                "min_trend_return": Decimal("0.0028"),
                "min_pullback": Decimal("0.0008"),
                "min_trigger_return": Decimal("0.00025"),
                "min_range_ratio": Decimal("0.0010"),
            },
            "range_params": {
                "range_period": 60,
                "edge_ratio": Decimal("0.16"),
                "min_reversal_body_ratio": Decimal("0.18"),
                "min_range_ratio": Decimal("0.0018"),
            },
            "burst_params": {
                "breakout_period": 14,
                "impulse_period": 1,
                "volume_period": 24,
                "min_impulse_return": Decimal("0.0010"),
                "min_volume_ratio": Decimal("1.10"),
                "breakout_buffer": Decimal("0.0003"),
                "mode": "fade",
            },
            "router_order": ("trend", "burst", "range"),
            "max_abs_trend_for_range": Decimal("0.0065"),
            "range_regime_period": 300,
            "trend_regime_period": 300,
        },
        "range-first": {
            "trend_params": {
                "trend_period": 90,
                "pullback_period": 7,
                "trigger_period": 2,
                "min_trend_return": Decimal("0.0035"),
                "min_pullback": Decimal("0.0010"),
                "min_trigger_return": Decimal("0.00035"),
                "min_range_ratio": Decimal("0.0012"),
            },
            "range_params": {
                "range_period": 75,
                "edge_ratio": Decimal("0.14"),
                "min_reversal_body_ratio": Decimal("0.22"),
                "min_range_ratio": Decimal("0.0025"),
            },
            "burst_params": {
                "breakout_period": 18,
                "impulse_period": 2,
                "volume_period": 30,
                "min_impulse_return": Decimal("0.0015"),
                "min_volume_ratio": Decimal("1.20"),
                "breakout_buffer": Decimal("0.0004"),
                "mode": "fade",
            },
            "router_order": ("range", "trend", "burst"),
            "max_abs_trend_for_range": Decimal("0.0045"),
            "range_regime_period": 360,
            "trend_regime_period": 360,
        },
        "burst-exhaustion": {
            "trend_params": {
                "trend_period": 80,
                "pullback_period": 6,
                "trigger_period": 2,
                "min_trend_return": Decimal("0.0032"),
                "min_pullback": Decimal("0.0009"),
                "min_trigger_return": Decimal("0.00030"),
                "min_range_ratio": Decimal("0.0010"),
            },
            "range_params": {
                "range_period": 50,
                "edge_ratio": Decimal("0.15"),
                "min_reversal_body_ratio": Decimal("0.20"),
                "min_range_ratio": Decimal("0.0020"),
            },
            "burst_params": {
                "breakout_period": 18,
                "impulse_period": 2,
                "volume_period": 30,
                "min_impulse_return": Decimal("0.0018"),
                "min_volume_ratio": Decimal("1.25"),
                "breakout_buffer": Decimal("0.0008"),
                "mode": "fade",
            },
            "router_order": ("burst", "trend", "range"),
            "max_abs_trend_for_range": Decimal("0.0050"),
            "range_regime_period": 300,
            "trend_regime_period": 300,
        },
        "ultra-selective": {
            "trend_params": {
                "trend_period": 120,
                "pullback_period": 8,
                "trigger_period": 2,
                "min_trend_return": Decimal("0.0045"),
                "min_pullback": Decimal("0.0012"),
                "min_trigger_return": Decimal("0.00050"),
                "min_range_ratio": Decimal("0.0015"),
            },
            "range_params": {
                "range_period": 90,
                "edge_ratio": Decimal("0.12"),
                "min_reversal_body_ratio": Decimal("0.25"),
                "min_range_ratio": Decimal("0.0030"),
            },
            "burst_params": {
                "breakout_period": 24,
                "impulse_period": 2,
                "volume_period": 36,
                "min_impulse_return": Decimal("0.0025"),
                "min_volume_ratio": Decimal("1.35"),
                "breakout_buffer": Decimal("0.0010"),
                "mode": "fade",
            },
            "router_order": ("trend", "burst", "range"),
            "max_abs_trend_for_range": Decimal("0.0040"),
            "range_regime_period": 420,
            "trend_regime_period": 420,
        },
        "selective-trend": _merged_strategy_params(
            trend={"min_trend_return": Decimal("0.003"), "min_pullback": Decimal("0.0008")},
            burst={"min_volume_ratio": Decimal("1.2")},
            max_abs_trend_for_range=Decimal("0.006"),
        ),
        "liquid-burst": _merged_strategy_params(
            trend={"min_range_ratio": Decimal("0.0012")},
            burst={"min_impulse_return": Decimal("0.0010"), "min_volume_ratio": Decimal("1.3")},
            range_params={"min_reversal_body_ratio": Decimal("0.18")},
        ),
        "range-strict": _merged_strategy_params(
            range_params={"edge_ratio": Decimal("0.14"), "min_range_ratio": Decimal("0.0020")},
            max_abs_trend_for_range=Decimal("0.005"),
        ),
    }
    exit_sizing_profiles = (
        ("p1-tp0075-sl0050-e0040-l4", Decimal("0.0075"), Decimal("0.0050"), Decimal("0.040"), Decimal("4")),
        ("p2-tp0060-sl0045-e0035-l3", Decimal("0.0060"), Decimal("0.0045"), Decimal("0.035"), Decimal("3")),
        ("p3-tp0090-sl0060-e0045-l4", Decimal("0.0090"), Decimal("0.0060"), Decimal("0.045"), Decimal("4")),
        ("p4-tp0105-sl0070-e0050-l5", Decimal("0.0105"), Decimal("0.0070"), Decimal("0.050"), Decimal("5")),
    )
    guards = (
        ("guard-a", DefensiveGuardConfig(
            min_minutes_between_entries=60,
            pause_minutes_after_loss=90,
            max_daily_loss_ratio=Decimal("0.006"),
            max_daily_trades=12,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.08"),
            min_signal_confidence=Decimal("0.68"),
            min_1m_range_ratio=Decimal("0.0006"),
            max_1m_range_ratio=Decimal("0.0060"),
        )),
        ("guard-b", DefensiveGuardConfig(
            min_minutes_between_entries=90,
            pause_minutes_after_loss=180,
            max_daily_loss_ratio=Decimal("0.004"),
            max_daily_trades=8,
            max_consecutive_losses=1,
            max_peak_drawdown_ratio=Decimal("0.05"),
            min_signal_confidence=Decimal("0.70"),
            min_1m_range_ratio=Decimal("0.0008"),
            max_1m_range_ratio=Decimal("0.0040"),
        )),
        ("guard-c", DefensiveGuardConfig(
            min_minutes_between_entries=20,
            pause_minutes_after_loss=45,
            max_daily_loss_ratio=Decimal("0.006"),
            max_daily_trades=15,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.08"),
            min_signal_confidence=Decimal("0.64"),
            min_1m_range_ratio=Decimal("0.0004"),
            max_1m_range_ratio=Decimal("0.0075"),
        )),
        ("guard-d", DefensiveGuardConfig(
            min_minutes_between_entries=30,
            pause_minutes_after_loss=60,
            max_daily_loss_ratio=Decimal("0.005"),
            max_daily_trades=12,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.06"),
            min_signal_confidence=Decimal("0.64"),
            min_1m_range_ratio=Decimal("0.0005"),
            max_1m_range_ratio=Decimal("0.0065"),
        )),
        ("guard-e", DefensiveGuardConfig(
            min_minutes_between_entries=10,
            pause_minutes_after_loss=30,
            max_daily_loss_ratio=Decimal("0.006"),
            max_daily_trades=15,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.08"),
            min_signal_confidence=Decimal("0.64"),
            min_1m_range_ratio=Decimal("0.0003"),
            max_1m_range_ratio=Decimal("0.0080"),
        )),
    )
    candidates = []
    for strategy_name, strategy_params in strategies.items():
        for profile_name, tp, sl, equity_ratio, leverage in exit_sizing_profiles:
            for guard_name, guard in guards:
                candidates.append(
                    SchedulerBacktestCandidate(
                        candidate_id=f"{strategy_name}-{profile_name}-{guard_name}",
                        strategies=(StrategyCandidateSpec("regime_router", strategy_params),),
                        take_profit_ratio=tp,
                        stop_loss_ratio=sl,
                        equity_ratio=equity_ratio,
                        leverage=leverage,
                        candle_limit=CANDLE_LIMIT,
                        guard=guard,
                    )
                )
    existing_strategy_sets = {
        "adopted-scalper": (StrategyCandidateSpec("regime_router", base_strategy_params()), CANDLE_LIMIT),
        "adopted-compression": (
            StrategyCandidateSpec("compression", compression_strategy_params()),
            1442,
        ),
        "adopted-range": (
            StrategyCandidateSpec("range_edge", range_edge_strategy_params()),
            302,
        ),
        "chart-pattern": (
            StrategyCandidateSpec("chart_pattern", chart_pattern_strategy_params()),
            122,
        ),
        "combo-scalper-compression": (
            (
                StrategyCandidateSpec("regime_router", base_strategy_params()),
                StrategyCandidateSpec("compression", compression_strategy_params()),
            ),
            1442,
        ),
        "combo-scalper-range": (
            (
                StrategyCandidateSpec("regime_router", base_strategy_params()),
                StrategyCandidateSpec("range_edge", range_edge_strategy_params()),
            ),
            302,
        ),
        "combo-compression-range": (
            (
                StrategyCandidateSpec("compression", compression_strategy_params()),
                StrategyCandidateSpec("range_edge", range_edge_strategy_params()),
            ),
            1442,
        ),
        "combo-chart-range-compression": (
            (
                StrategyCandidateSpec("chart_pattern", chart_pattern_strategy_params()),
                StrategyCandidateSpec("range_edge", range_edge_strategy_params()),
                StrategyCandidateSpec("compression", compression_strategy_params()),
            ),
            1442,
        ),
    }
    focused_profiles = (
        ("legacy-p2-sl0050-rr025-e0120-l8", Decimal("0.00125"), Decimal("0.0050"), Decimal("0.120"), Decimal("8")),
        ("balanced-tp0045-sl0030-e0050-l4", Decimal("0.0045"), Decimal("0.0030"), Decimal("0.050"), Decimal("4")),
        ("wide-tp0075-sl0050-e0040-l4", Decimal("0.0075"), Decimal("0.0050"), Decimal("0.040"), Decimal("4")),
    )
    focused_guards = (
        ("open-guard", DefensiveGuardConfig(
            min_minutes_between_entries=3,
            pause_minutes_after_loss=5,
            max_daily_loss_ratio=Decimal("0.020"),
            max_daily_trades=20,
            max_consecutive_losses=4,
            max_peak_drawdown_ratio=Decimal("0.12"),
            min_signal_confidence=Decimal("0.60"),
            min_1m_range_ratio=Decimal("0.0001"),
            max_1m_range_ratio=Decimal("0.0120"),
        )),
        ("defensive-guard", DefensiveGuardConfig(
            min_minutes_between_entries=10,
            pause_minutes_after_loss=30,
            max_daily_loss_ratio=Decimal("0.008"),
            max_daily_trades=15,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.08"),
            min_signal_confidence=Decimal("0.64"),
            min_1m_range_ratio=Decimal("0.0003"),
            max_1m_range_ratio=Decimal("0.0080"),
        )),
    )
    for strategy_name, (strategy_specs, candle_limit) in existing_strategy_sets.items():
        specs = strategy_specs if isinstance(strategy_specs, tuple) else (strategy_specs,)
        for profile_name, tp, sl, equity_ratio, leverage in focused_profiles:
            for guard_name, guard in focused_guards:
                candidates.append(
                    SchedulerBacktestCandidate(
                        candidate_id=f"{strategy_name}-{profile_name}-{guard_name}",
                        strategies=specs,
                        take_profit_ratio=tp,
                        stop_loss_ratio=sl,
                        equity_ratio=equity_ratio,
                        leverage=leverage,
                        candle_limit=candle_limit,
                        guard=guard,
                    )
                )
    candidates.extend(exact_historical_candidates())
    return tuple(candidates)


def default_candidate() -> SchedulerBacktestCandidate:
    return SchedulerBacktestCandidate(
        candidate_id="balanced-tp012-sl010-balanced-guard-a",
        strategies=(StrategyCandidateSpec("regime_router", base_strategy_params()),),
        take_profit_ratio=Decimal("0.012"),
        stop_loss_ratio=Decimal("0.010"),
        equity_ratio=Decimal("0.050"),
        leverage=Decimal("4"),
        candle_limit=CANDLE_LIMIT,
        guard=DefensiveGuardConfig(
            min_minutes_between_entries=60,
            pause_minutes_after_loss=90,
            max_daily_loss_ratio=Decimal("0.006"),
            max_daily_trades=12,
            max_consecutive_losses=2,
            max_peak_drawdown_ratio=Decimal("0.08"),
            min_signal_confidence=Decimal("0.68"),
            min_1m_range_ratio=Decimal("0.0006"),
            max_1m_range_ratio=Decimal("0.0060"),
        ),
    )


def selected_strategy() -> RegimeRouterScalperStrategy:
    return RegimeRouterScalperStrategy(**base_strategy_params())


def base_strategy_params() -> dict[str, object]:
    return {
        "trend_params": {
            "trend_period": 60,
            "pullback_period": 5,
            "trigger_period": 1,
            "min_trend_return": Decimal("0.002"),
            "min_pullback": Decimal("0.0006"),
            "min_trigger_return": Decimal("0.0002"),
            "min_range_ratio": Decimal("0.0008"),
        },
        "range_params": {
            "range_period": 45,
            "edge_ratio": Decimal("0.18"),
            "min_reversal_body_ratio": Decimal("0.15"),
            "min_range_ratio": Decimal("0.0015"),
        },
        "burst_params": {
            "breakout_period": 12,
            "impulse_period": 1,
            "volume_period": 20,
            "min_impulse_return": Decimal("0.0008"),
            "min_volume_ratio": Decimal("1.0"),
            "breakout_buffer": Decimal("0.0000"),
            "mode": "fade",
        },
        "router_order": ("trend", "burst", "range"),
        "max_abs_trend_for_range": Decimal("0.008"),
        "range_regime_period": 240,
        "trend_regime_period": 240,
    }


def compression_strategy_params() -> dict[str, object]:
    return {
        "lookback": 180,
        "compression_period": 45,
        "compression_ratio": Decimal("0.45"),
        "breakout_buffer": Decimal("0.0006"),
        "min_volume_ratio": Decimal("1.00"),
        "direction_filter_period": 1440,
        "min_filter_return": Decimal("0.002"),
    }


def range_edge_strategy_params() -> dict[str, object]:
    return {
        "range_period": 300,
        "lower_band": Decimal("0.06"),
        "upper_band": Decimal("0.94"),
        "min_range_width": Decimal("0.010"),
        "reclaim_return": Decimal("0.0007"),
    }


def chart_pattern_strategy_params() -> dict[str, object]:
    return {
        "lookback": 120,
        "pivot_window": 3,
        "price_tolerance": Decimal("0.01"),
        "breakout_buffer": Decimal("0.003"),
        "volume_ma_period": 20,
        "volume_multiplier": Decimal("1.3"),
        "min_confidence": Decimal("0.6"),
        "risk_reward_ratio": Decimal("2.0"),
    }


def exact_historical_candidates() -> list[SchedulerBacktestCandidate]:
    exact_guard = DefensiveGuardConfig(
        min_minutes_between_entries=1,
        pause_minutes_after_loss=0,
        max_daily_loss_ratio=Decimal("0.08"),
        max_daily_trades=80,
        max_consecutive_losses=12,
        max_peak_drawdown_ratio=Decimal("0.35"),
        min_signal_confidence=Decimal("0"),
        min_1m_range_ratio=Decimal("0"),
        max_1m_range_ratio=Decimal("1"),
    )
    practical_guard = DefensiveGuardConfig(
        min_minutes_between_entries=5,
        pause_minutes_after_loss=10,
        max_daily_loss_ratio=Decimal("0.020"),
        max_daily_trades=20,
        max_consecutive_losses=4,
        max_peak_drawdown_ratio=Decimal("0.12"),
        min_signal_confidence=Decimal("0.60"),
        min_1m_range_ratio=Decimal("0.0001"),
        max_1m_range_ratio=Decimal("0.0120"),
    )
    router_specs = (
        ("hist-router-t1-r1-b4-tbr", _router_params(router_order=("trend", "burst", "range"), max_abs_trend_for_range=Decimal("0.008"))),
        ("hist-router-t1-r1-b4-btr", _router_params(router_order=("burst", "trend", "range"), max_abs_trend_for_range=Decimal("0.006"))),
        ("hist-router-t1-r1-b4-rbt", _router_params(router_order=("range", "burst", "trend"), max_abs_trend_for_range=Decimal("0.004"))),
        (
            "hist-router-t1-r2-b4-btr",
            _router_params(
                router_order=("burst", "trend", "range"),
                max_abs_trend_for_range=Decimal("0.006"),
                range_params={
                    "range_period": 90,
                    "edge_ratio": Decimal("0.15"),
                    "min_reversal_body_ratio": Decimal("0.20"),
                    "min_range_ratio": Decimal("0.0020"),
                },
            ),
        ),
        (
            "hist-router-t1-r2-b4-tbr",
            _router_params(
                router_order=("trend", "burst", "range"),
                max_abs_trend_for_range=Decimal("0.008"),
                range_params={
                    "range_period": 90,
                    "edge_ratio": Decimal("0.15"),
                    "min_reversal_body_ratio": Decimal("0.20"),
                    "min_range_ratio": Decimal("0.0020"),
                },
            ),
        ),
        (
            "hist-router-t1-r2-b4-rbt",
            _router_params(
                router_order=("range", "burst", "trend"),
                max_abs_trend_for_range=Decimal("0.004"),
                range_params={
                    "range_period": 90,
                    "edge_ratio": Decimal("0.15"),
                    "min_reversal_body_ratio": Decimal("0.20"),
                    "min_range_ratio": Decimal("0.0020"),
                },
            ),
        ),
    )
    candidates: list[SchedulerBacktestCandidate] = []
    router_exit_profiles = (
        ("sl0050-rr025", Decimal("0.00125"), Decimal("0.0050")),
        ("tp0035-sl0050", Decimal("0.0035"), Decimal("0.0050")),
        ("tp0045-sl0050", Decimal("0.0045"), Decimal("0.0050")),
        ("tp0060-sl0070", Decimal("0.0060"), Decimal("0.0070")),
        ("tp0075-sl0100", Decimal("0.0075"), Decimal("0.0100")),
    )
    for name, params in router_specs:
        for profile_name, tp, sl in router_exit_profiles:
            for guard_name, guard in (("exact", exact_guard), ("practical", practical_guard)):
                candidates.append(
                    SchedulerBacktestCandidate(
                        candidate_id=f"{name}-{profile_name}-e0120-l8-{guard_name}",
                        strategies=(StrategyCandidateSpec("regime_router", params),),
                        take_profit_ratio=tp,
                        stop_loss_ratio=sl,
                        equity_ratio=Decimal("0.120"),
                        leverage=Decimal("8"),
                        candle_limit=CANDLE_LIMIT,
                        guard=guard,
                    )
                )
    exact_specs = (
        (
            "hist-compression-s2-sl0050-rr060",
            (StrategyCandidateSpec("compression", compression_strategy_params()),),
            Decimal("0.0300"),
            Decimal("0.0500"),
            Decimal("0.140"),
            Decimal("8"),
            1442,
        ),
        (
            "hist-compression-s2-sl0030-rr065",
            (StrategyCandidateSpec("compression", compression_strategy_params()),),
            Decimal("0.0195"),
            Decimal("0.0300"),
            Decimal("0.100"),
            Decimal("6"),
            1442,
        ),
        (
            "hist-range-300-sl0090-rr015",
            (StrategyCandidateSpec("range_edge", range_edge_strategy_params()),),
            Decimal("0.0135"),
            Decimal("0.0900"),
            Decimal("0.100"),
            Decimal("15"),
            302,
        ),
        (
            "hist-range-240-sl0090-rr015",
            (StrategyCandidateSpec("range_edge", {**range_edge_strategy_params(), "range_period": 240}),),
            Decimal("0.0135"),
            Decimal("0.0900"),
            Decimal("0.100"),
            Decimal("15"),
            242,
        ),
        (
            "hist-combo-range300-compression-sl0030-rr065",
            (
                StrategyCandidateSpec("range_edge", range_edge_strategy_params()),
                StrategyCandidateSpec("compression", compression_strategy_params()),
            ),
            Decimal("0.0195"),
            Decimal("0.0300"),
            Decimal("0.100"),
            Decimal("6"),
            1442,
        ),
        (
            "hist-combo-router-compression-sl0050-rr060",
            (
                StrategyCandidateSpec("regime_router", base_strategy_params()),
                StrategyCandidateSpec("compression", compression_strategy_params()),
            ),
            Decimal("0.0300"),
            Decimal("0.0500"),
            Decimal("0.120"),
            Decimal("8"),
            1442,
        ),
        (
            "hist-combo-range240-compression-sl0050-rr060",
            (
                StrategyCandidateSpec("range_edge", {**range_edge_strategy_params(), "range_period": 240}),
                StrategyCandidateSpec("compression", compression_strategy_params()),
            ),
            Decimal("0.0300"),
            Decimal("0.0500"),
            Decimal("0.120"),
            Decimal("8"),
            1442,
        ),
    )
    for name, specs, tp, sl, equity_ratio, leverage, candle_limit in exact_specs:
        for guard_name, guard in (("exact", exact_guard), ("practical", practical_guard)):
            candidates.append(
                SchedulerBacktestCandidate(
                    candidate_id=f"{name}-{guard_name}",
                    strategies=specs,
                    take_profit_ratio=tp,
                    stop_loss_ratio=sl,
                    equity_ratio=equity_ratio,
                    leverage=leverage,
                    candle_limit=candle_limit,
                    guard=guard,
                )
            )
    return candidates


def alpha_entry_candidates() -> list[SchedulerBacktestCandidate]:
    guards = (
        ("alpha-open", DefensiveGuardConfig(
            min_minutes_between_entries=1,
            pause_minutes_after_loss=5,
            max_daily_loss_ratio=Decimal("0.030"),
            max_daily_trades=20,
            max_consecutive_losses=5,
            max_peak_drawdown_ratio=Decimal("0.18"),
            min_signal_confidence=Decimal("0.60"),
            min_1m_range_ratio=Decimal("0.0002"),
            max_1m_range_ratio=Decimal("0.0120"),
        )),
        ("alpha-defensive", DefensiveGuardConfig(
            min_minutes_between_entries=5,
            pause_minutes_after_loss=15,
            max_daily_loss_ratio=Decimal("0.015"),
            max_daily_trades=15,
            max_consecutive_losses=3,
            max_peak_drawdown_ratio=Decimal("0.12"),
            min_signal_confidence=Decimal("0.64"),
            min_1m_range_ratio=Decimal("0.0003"),
            max_1m_range_ratio=Decimal("0.0100"),
        )),
    )
    profiles = (
        ("tp0045-sl0040-e0060-l5", Decimal("0.0045"), Decimal("0.0040"), Decimal("0.060"), Decimal("5")),
        ("tp0060-sl0050-e0050-l5", Decimal("0.0060"), Decimal("0.0050"), Decimal("0.050"), Decimal("5")),
        ("tp0075-sl0060-e0040-l4", Decimal("0.0075"), Decimal("0.0060"), Decimal("0.040"), Decimal("4")),
    )
    strategy_sets = {
        "alpha-impulse": _alpha_router_params(
            router_order=("impulse_pullback",),
            impulse_pullback_params={
                "impulse_period": 1,
                "pullback_period": 3,
                "trigger_period": 1,
                "min_impulse_return": Decimal("0.0050"),
                "min_pullback": Decimal("0.0018"),
                "min_resume_return": Decimal("0.0012"),
            },
        ),
        "alpha-impulse-strict": _alpha_router_params(
            router_order=("impulse_pullback",),
            impulse_pullback_params={
                "impulse_period": 1,
                "pullback_period": 4,
                "trigger_period": 1,
                "min_impulse_return": Decimal("0.0070"),
                "min_pullback": Decimal("0.0025"),
                "min_resume_return": Decimal("0.0018"),
            },
        ),
        "alpha-retest": _alpha_router_params(
            router_order=("breakout_retest",),
            breakout_retest_params={
                "breakout_period": 45,
                "retest_period": 3,
                "breakout_buffer": Decimal("0.0015"),
                "retest_tolerance": Decimal("0.0025"),
                "min_reclaim_return": Decimal("0.0010"),
            },
        ),
        "alpha-retest-fast": _alpha_router_params(
            router_order=("breakout_retest",),
            breakout_retest_params={
                "breakout_period": 30,
                "retest_period": 2,
                "breakout_buffer": Decimal("0.0012"),
                "retest_tolerance": Decimal("0.0025"),
                "min_reclaim_return": Decimal("0.0008"),
            },
        ),
        "alpha-expansion": _alpha_router_params(
            router_order=("volatility_expansion",),
            volatility_expansion_params={
                "range_period": 20,
                "volume_period": 20,
                "min_range_expansion": Decimal("1.8"),
                "min_volume_ratio": Decimal("1.6"),
                "min_body_ratio": Decimal("0.55"),
            },
        ),
        "alpha-expansion-strict": _alpha_router_params(
            router_order=("volatility_expansion",),
            volatility_expansion_params={
                "range_period": 30,
                "volume_period": 30,
                "min_range_expansion": Decimal("2.2"),
                "min_volume_ratio": Decimal("2.0"),
                "min_body_ratio": Decimal("0.60"),
            },
        ),
        "alpha-sweep": _alpha_router_params(
            router_order=("liquidity_sweep",),
            liquidity_sweep_params={
                "lookback_period": 45,
                "volume_period": 45,
                "sweep_buffer": Decimal("0.0012"),
                "min_close_reclaim": Decimal("0.0005"),
                "min_wick_ratio": Decimal("0.42"),
                "min_volume_ratio": Decimal("1.35"),
            },
        ),
        "alpha-sweep-strict": _alpha_router_params(
            router_order=("liquidity_sweep",),
            liquidity_sweep_params={
                "lookback_period": 90,
                "volume_period": 60,
                "sweep_buffer": Decimal("0.0015"),
                "min_close_reclaim": Decimal("0.0008"),
                "min_wick_ratio": Decimal("0.50"),
                "min_volume_ratio": Decimal("1.60"),
            },
        ),
        "alpha-dryup-breakout": _alpha_router_params(
            router_order=("volume_dryup_breakout",),
            volume_dryup_breakout_params={
                "range_period": 45,
                "dryup_period": 8,
                "volume_period": 45,
                "max_dryup_volume_ratio": Decimal("0.75"),
                "min_breakout_volume_ratio": Decimal("1.60"),
                "breakout_buffer": Decimal("0.0010"),
                "min_body_ratio": Decimal("0.50"),
            },
        ),
        "alpha-exhaustion": _alpha_router_params(
            router_order=("three_push_exhaustion",),
            three_push_exhaustion_params={
                "trend_period": 90,
                "push_lookback": 20,
                "volume_period": 45,
                "min_trend_return": Decimal("0.025"),
                "min_new_extremes": 3,
                "min_rejection_wick_ratio": Decimal("0.50"),
                "min_volume_ratio": Decimal("1.60"),
            },
        ),
        "alpha-router-balanced": _alpha_router_params(
            router_order=("impulse_pullback", "breakout_retest", "volatility_expansion", "range"),
            impulse_pullback_params={
                "impulse_period": 1,
                "pullback_period": 3,
                "trigger_period": 1,
                "min_impulse_return": Decimal("0.0055"),
                "min_pullback": Decimal("0.0020"),
                "min_resume_return": Decimal("0.0013"),
            },
            breakout_retest_params={
                "breakout_period": 45,
                "retest_period": 3,
                "breakout_buffer": Decimal("0.0015"),
                "retest_tolerance": Decimal("0.0025"),
                "min_reclaim_return": Decimal("0.0010"),
            },
            volatility_expansion_params={
                "range_period": 20,
                "volume_period": 20,
                "min_range_expansion": Decimal("1.9"),
                "min_volume_ratio": Decimal("1.7"),
                "min_body_ratio": Decimal("0.58"),
            },
        ),
        "alpha-router-new-balanced": _alpha_router_params(
            router_order=("liquidity_sweep", "volume_dryup_breakout", "three_push_exhaustion"),
            liquidity_sweep_params={
                "lookback_period": 60,
                "volume_period": 45,
                "sweep_buffer": Decimal("0.0012"),
                "min_close_reclaim": Decimal("0.0006"),
                "min_wick_ratio": Decimal("0.45"),
                "min_volume_ratio": Decimal("1.40"),
            },
            volume_dryup_breakout_params={
                "range_period": 45,
                "dryup_period": 8,
                "volume_period": 45,
                "max_dryup_volume_ratio": Decimal("0.80"),
                "min_breakout_volume_ratio": Decimal("1.55"),
                "breakout_buffer": Decimal("0.0010"),
                "min_body_ratio": Decimal("0.50"),
            },
            three_push_exhaustion_params={
                "trend_period": 90,
                "push_lookback": 20,
                "volume_period": 45,
                "min_trend_return": Decimal("0.025"),
                "min_new_extremes": 3,
                "min_rejection_wick_ratio": Decimal("0.50"),
                "min_volume_ratio": Decimal("1.60"),
            },
        ),
        "alpha-router-continuation": _alpha_router_params(
            router_order=("breakout_retest", "impulse_pullback", "volatility_expansion"),
            impulse_pullback_params={
                "impulse_period": 1,
                "pullback_period": 4,
                "trigger_period": 1,
                "min_impulse_return": Decimal("0.0065"),
                "min_pullback": Decimal("0.0022"),
                "min_resume_return": Decimal("0.0015"),
            },
            breakout_retest_params={
                "breakout_period": 60,
                "retest_period": 3,
                "breakout_buffer": Decimal("0.0015"),
                "retest_tolerance": Decimal("0.0020"),
                "min_reclaim_return": Decimal("0.0010"),
            },
            volatility_expansion_params={
                "range_period": 30,
                "volume_period": 30,
                "min_range_expansion": Decimal("2.0"),
                "min_volume_ratio": Decimal("1.8"),
                "min_body_ratio": Decimal("0.58"),
            },
        ),
    }
    candidates = []
    for strategy_name, params in strategy_sets.items():
        for profile_name, tp, sl, equity_ratio, leverage in profiles:
            for guard_name, guard in guards:
                candidates.append(
                    SchedulerBacktestCandidate(
                        candidate_id=f"{strategy_name}-{profile_name}-{guard_name}",
                        strategies=(StrategyCandidateSpec("regime_router", params),),
                        take_profit_ratio=tp,
                        stop_loss_ratio=sl,
                        equity_ratio=equity_ratio,
                        leverage=leverage,
                        candle_limit=CANDLE_LIMIT,
                        guard=guard,
                    )
                )
    return candidates


def multi_frequency_candidates() -> list[SchedulerBacktestCandidate]:
    practical_guard = DefensiveGuardConfig(
        min_minutes_between_entries=5,
        pause_minutes_after_loss=10,
        max_daily_loss_ratio=Decimal("0.020"),
        max_daily_trades=20,
        max_consecutive_losses=4,
        max_peak_drawdown_ratio=Decimal("0.12"),
        min_signal_confidence=Decimal("0.60"),
        min_1m_range_ratio=Decimal("0.0001"),
        max_1m_range_ratio=Decimal("0.0120"),
    )
    defensive_guard = DefensiveGuardConfig(
        min_minutes_between_entries=10,
        pause_minutes_after_loss=30,
        max_daily_loss_ratio=Decimal("0.012"),
        max_daily_trades=15,
        max_consecutive_losses=3,
        max_peak_drawdown_ratio=Decimal("0.10"),
        min_signal_confidence=Decimal("0.64"),
        min_1m_range_ratio=Decimal("0.0002"),
        max_1m_range_ratio=Decimal("0.0100"),
    )
    impulse_router = StrategyCandidateSpec(
        "regime_router",
        _alpha_router_params(
            router_order=("impulse_pullback",),
            impulse_pullback_params={
                "impulse_period": 1,
                "pullback_period": 3,
                "trigger_period": 1,
                "min_impulse_return": Decimal("0.0050"),
                "min_pullback": Decimal("0.0018"),
                "min_resume_return": Decimal("0.0012"),
            },
        ),
    )
    retest_router = StrategyCandidateSpec(
        "regime_router",
        _alpha_router_params(
            router_order=("breakout_retest",),
            breakout_retest_params={
                "breakout_period": 30,
                "retest_period": 2,
                "breakout_buffer": Decimal("0.0012"),
                "retest_tolerance": Decimal("0.0025"),
                "min_reclaim_return": Decimal("0.0008"),
            },
        ),
    )
    expansion_router = StrategyCandidateSpec(
        "regime_router",
        _alpha_router_params(
            router_order=("volatility_expansion",),
            volatility_expansion_params={
                "range_period": 30,
                "volume_period": 30,
                "min_range_expansion": Decimal("2.2"),
                "min_volume_ratio": Decimal("2.0"),
                "min_body_ratio": Decimal("0.60"),
            },
        ),
    )
    balanced_router = StrategyCandidateSpec(
        "regime_router",
        _alpha_router_params(
            router_order=("impulse_pullback", "breakout_retest", "volatility_expansion"),
            impulse_pullback_params={
                "impulse_period": 1,
                "pullback_period": 3,
                "trigger_period": 1,
                "min_impulse_return": Decimal("0.0055"),
                "min_pullback": Decimal("0.0020"),
                "min_resume_return": Decimal("0.0013"),
            },
            breakout_retest_params={
                "breakout_period": 45,
                "retest_period": 3,
                "breakout_buffer": Decimal("0.0015"),
                "retest_tolerance": Decimal("0.0025"),
                "min_reclaim_return": Decimal("0.0010"),
            },
            volatility_expansion_params={
                "range_period": 30,
                "volume_period": 30,
                "min_range_expansion": Decimal("2.1"),
                "min_volume_ratio": Decimal("1.9"),
                "min_body_ratio": Decimal("0.60"),
            },
        ),
    )
    compression = StrategyCandidateSpec("compression", compression_strategy_params())
    range_edge = StrategyCandidateSpec("range_edge", range_edge_strategy_params())
    specs = (
        (
            "mf-compression-only-wide",
            (compression,),
            Decimal("0.0195"),
            Decimal("0.0300"),
            Decimal("0.080"),
            Decimal("5"),
            practical_guard,
        ),
        (
            "mf-compression-only-expansion-wide",
            (compression,),
            Decimal("0.0300"),
            Decimal("0.0500"),
            Decimal("0.100"),
            Decimal("6"),
            practical_guard,
        ),
        (
            "mf-compression-impulse-wide",
            (compression, impulse_router),
            Decimal("0.0195"),
            Decimal("0.0300"),
            Decimal("0.080"),
            Decimal("5"),
            practical_guard,
        ),
        (
            "mf-compression-retest-wide",
            (compression, retest_router),
            Decimal("0.0195"),
            Decimal("0.0300"),
            Decimal("0.080"),
            Decimal("5"),
            practical_guard,
        ),
        (
            "mf-compression-balanced-mid",
            (compression, balanced_router),
            Decimal("0.0100"),
            Decimal("0.0120"),
            Decimal("0.060"),
            Decimal("5"),
            defensive_guard,
        ),
        (
            "mf-compression-expansion-mid",
            (compression, expansion_router),
            Decimal("0.0075"),
            Decimal("0.0060"),
            Decimal("0.040"),
            Decimal("4"),
            defensive_guard,
        ),
        (
            "mf-compression-range-wide",
            (compression, range_edge),
            Decimal("0.0195"),
            Decimal("0.0300"),
            Decimal("0.080"),
            Decimal("5"),
            practical_guard,
        ),
        (
            "mf-compression-range-impulse-wide",
            (compression, range_edge, impulse_router),
            Decimal("0.0195"),
            Decimal("0.0300"),
            Decimal("0.080"),
            Decimal("5"),
            practical_guard,
        ),
        (
            "mf-compression-range-retest-wide",
            (compression, range_edge, retest_router),
            Decimal("0.0195"),
            Decimal("0.0300"),
            Decimal("0.080"),
            Decimal("5"),
            practical_guard,
        ),
        (
            "mf-compression-impulse-retest-mid",
            (compression, impulse_router, retest_router),
            Decimal("0.0100"),
            Decimal("0.0120"),
            Decimal("0.060"),
            Decimal("5"),
            defensive_guard,
        ),
    )
    return [
        SchedulerBacktestCandidate(
            candidate_id=name,
            strategies=strategies,
            take_profit_ratio=tp,
            stop_loss_ratio=sl,
            equity_ratio=equity_ratio,
            leverage=leverage,
            candle_limit=1442,
            guard=guard,
        )
        for name, strategies, tp, sl, equity_ratio, leverage, guard in specs
    ]


def _alpha_router_params(
    *,
    router_order: tuple[str, ...],
    impulse_pullback_params: dict[str, object] | None = None,
    breakout_retest_params: dict[str, object] | None = None,
    volatility_expansion_params: dict[str, object] | None = None,
    liquidity_sweep_params: dict[str, object] | None = None,
    volume_dryup_breakout_params: dict[str, object] | None = None,
    three_push_exhaustion_params: dict[str, object] | None = None,
) -> dict[str, object]:
    params = base_strategy_params()
    params["router_order"] = router_order
    params["impulse_pullback_params"] = impulse_pullback_params or {}
    params["breakout_retest_params"] = breakout_retest_params or {}
    params["volatility_expansion_params"] = volatility_expansion_params or {}
    params["liquidity_sweep_params"] = liquidity_sweep_params or {}
    params["volume_dryup_breakout_params"] = volume_dryup_breakout_params or {}
    params["three_push_exhaustion_params"] = three_push_exhaustion_params or {}
    return params


def _router_params(
    *,
    router_order: tuple[str, str, str],
    max_abs_trend_for_range: Decimal,
    range_params: dict[str, object] | None = None,
) -> dict[str, object]:
    params = base_strategy_params()
    params["router_order"] = router_order
    params["max_abs_trend_for_range"] = max_abs_trend_for_range
    if range_params is not None:
        params["range_params"] = range_params
    return params


def _merged_strategy_params(
    *,
    trend: dict[str, object] | None = None,
    range_params: dict[str, object] | None = None,
    burst: dict[str, object] | None = None,
    max_abs_trend_for_range: Decimal | None = None,
) -> dict[str, object]:
    params = base_strategy_params()
    params["trend_params"] = {**params["trend_params"], **(trend or {})}
    params["range_params"] = {**params["range_params"], **(range_params or {})}
    params["burst_params"] = {**params["burst_params"], **(burst or {})}
    if max_abs_trend_for_range is not None:
        params["max_abs_trend_for_range"] = max_abs_trend_for_range
    return params


def execute_command(
    signal_id: str,
    market: MarketSnapshot,
    index: int,
    equity: Decimal,
    candle_limit: int,
    symbol: Symbol = SYMBOL,
) -> ExecuteTradeCommand:
    latest = market.candles[index]
    return ExecuteTradeCommand(
        symbol=symbol,
        timeframe=TIMEFRAME,
        candle_limit=candle_limit,
        indicators=IndicatorSet(symbol=symbol, timeframe=TIMEFRAME, measured_at=latest.closed_at, values=()),
        exposure_limit=ExposureLimit(
            equity=equity,
            current_total_exposure=Decimal("0"),
            current_symbol_exposure=Decimal("0"),
            max_total_exposure_ratio=Decimal("1"),
            max_symbol_exposure_ratio=Decimal("1"),
        ),
        base_risk_ratio=Decimal("0.02"),
        leverage=Decimal("2"),
        client_order_id_prefix="scheduler-bt",
        signal_id=signal_id,
        generator_id=GENERATOR_ID,
    )


def maybe_close_position(
    position: BacktestPosition,
    market: MarketSnapshot,
    index: int,
) -> BacktestTrade | None:
    candle = market.candles[index]
    if position.direction is SignalDirection.LONG:
        if candle.low_price <= position.stop_loss:
            return close_trade(position, _exit_fill_price(position.stop_loss, position.direction), "stop_loss", index)
        if candle.high_price >= position.take_profit:
            return close_trade(position, _exit_fill_price(position.take_profit, position.direction), "take_profit", index)
    else:
        if candle.high_price >= position.stop_loss:
            return close_trade(position, _exit_fill_price(position.stop_loss, position.direction), "stop_loss", index)
        if candle.low_price <= position.take_profit:
            return close_trade(position, _exit_fill_price(position.take_profit, position.direction), "take_profit", index)
    return None


def close_trade(position: BacktestPosition, exit_price: Decimal, reason: str, index: int) -> BacktestTrade:
    if position.direction is SignalDirection.LONG:
        gross_pnl = (exit_price - position.entry_price) * position.quantity
    else:
        gross_pnl = (position.entry_price - exit_price) * position.quantity
    exit_fee = exit_price * position.quantity * FEE_RATE
    fee_paid = position.entry_fee + exit_fee
    return BacktestTrade(
        entry_price=position.entry_price,
        exit_price=exit_price,
        direction=position.direction,
        quantity=position.quantity,
        margin=position.margin,
        gross_pnl=gross_pnl,
        net_pnl=gross_pnl - fee_paid,
        fee_paid=fee_paid,
        exit_reason=reason,
        holding_bars=index - position.opened_index,
    )


def _entry_fill_price(price: Decimal, direction: SignalDirection) -> Decimal:
    if direction is SignalDirection.LONG:
        return price * (Decimal("1") + SLIPPAGE_RATE)
    return price * (Decimal("1") - SLIPPAGE_RATE)


def _exit_fill_price(price: Decimal, direction: SignalDirection) -> Decimal:
    if direction is SignalDirection.LONG:
        return price * (Decimal("1") - SLIPPAGE_RATE)
    return price * (Decimal("1") + SLIPPAGE_RATE)


def rank_scheduler_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        results,
        key=lambda result: (
            Decimal(str(result["trades_per_day"])) >= Decimal("5"),
            Decimal(str(result["trades_per_day"])) <= Decimal("15"),
            Decimal(str(result["net_win_rate"])) >= Decimal("0.60"),
            Decimal(str(result["daily_return_ratio"])),
            Decimal(str(result["return_ratio"])),
            -Decimal(str(result["max_drawdown_ratio"])),
        ),
        reverse=True,
    )


def rank_train_test_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        results,
        key=lambda result: (
            Decimal(str(result["test_trades_per_day"])) >= Decimal("5"),
            Decimal(str(result["test_trades_per_day"])) <= Decimal("15"),
            Decimal(str(result["test_net_win_rate"])) >= Decimal("0.60"),
            Decimal(str(result["train_return_ratio"])) > Decimal("0"),
            Decimal(str(result["test_return_ratio"])) > Decimal("0"),
            Decimal(str(result["test_daily_return_ratio"])),
            Decimal(str(result["train_daily_return_ratio"])),
            -Decimal(str(result["test_max_drawdown_ratio"])),
        ),
        reverse=True,
    )


def rank_walk_forward_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        results,
        key=lambda result: (
            Decimal(str(result["average_return_ratio"])) > Decimal("0"),
            Decimal(str(result["positive_fold_count"])),
            Decimal(str(result["average_daily_return_ratio"])),
            Decimal(str(result["average_trades_per_day"])),
            Decimal(str(result["average_net_win_rate"])),
            -Decimal(str(result["worst_max_drawdown_ratio"])),
        ),
        reverse=True,
    )


def candidate_payload(candidate: SchedulerBacktestCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "take_profit_ratio": str(candidate.take_profit_ratio),
        "stop_loss_ratio": str(candidate.stop_loss_ratio),
        "equity_ratio": str(candidate.equity_ratio),
        "leverage": str(candidate.leverage),
        "candle_limit": candidate.candle_limit,
        "strategies": [
            {"kind": spec.kind, "params": _stringify(spec.params)}
            for spec in candidate.strategies
        ],
        "guard": {
            "min_minutes_between_entries": candidate.guard.min_minutes_between_entries,
            "pause_minutes_after_loss": candidate.guard.pause_minutes_after_loss,
            "max_daily_loss_ratio": str(candidate.guard.max_daily_loss_ratio),
            "max_daily_trades": candidate.guard.max_daily_trades,
            "max_consecutive_losses": candidate.guard.max_consecutive_losses,
            "max_peak_drawdown_ratio": str(candidate.guard.max_peak_drawdown_ratio),
            "min_signal_confidence": str(candidate.guard.min_signal_confidence),
            "min_1m_range_ratio": str(candidate.guard.min_1m_range_ratio),
            "max_1m_range_ratio": str(candidate.guard.max_1m_range_ratio),
        },
    }


def candidate_definition_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_manifest(
    candidates: tuple[SchedulerBacktestCandidate, ...] | list[SchedulerBacktestCandidate],
) -> dict[str, object]:
    candidates = validate_unique_candidate_ids(candidates)
    candidates = tuple(sorted(candidates, key=lambda candidate: candidate.candidate_id))
    universe = [candidate_payload(candidate) for candidate in candidates]
    return {
        "candidate_count": len(universe),
        "candidate_universe_hash": candidate_definition_hash(universe),
        "candidates": universe,
    }


def validate_unique_candidate_ids(
    candidates: tuple[SchedulerBacktestCandidate, ...] | list[SchedulerBacktestCandidate],
) -> tuple[SchedulerBacktestCandidate, ...]:
    normalized = tuple(candidates)
    seen: set[str] = set()
    duplicates = []
    for candidate in normalized:
        if candidate.candidate_id in seen and candidate.candidate_id not in duplicates:
            duplicates.append(candidate.candidate_id)
        seen.add(candidate.candidate_id)
    if duplicates:
        raise ValueError(f"duplicate candidate_id definitions: {', '.join(sorted(duplicates))}")
    return normalized


def write_candidate_manifest(
    candidates: tuple[SchedulerBacktestCandidate, ...] | list[SchedulerBacktestCandidate],
    path: Path,
) -> dict[str, object]:
    payload = candidate_manifest(candidates)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return payload


def _stringify(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _stringify(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_stringify(item) for item in value)
    return value


def _average_decimal(values) -> Decimal:
    decimals = tuple(Decimal(str(value)) for value in values)
    if not decimals:
        return Decimal("0")
    return sum(decimals, Decimal("0")) / Decimal(len(decimals))


def _candles_between(candles, start_at: datetime, end_at: datetime):
    opened_times = tuple(candle.opened_at for candle in candles)
    start_index = bisect_left(opened_times, start_at)
    end_index = bisect_left(opened_times, end_at)
    return candles[start_index:end_index]


def _label_date(value: str) -> str:
    return value.replace("/", "-")


def _parse_datetime(value: str) -> datetime:
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise ValueError(f"unsupported date format: {value}")


def _parse_symbol(value: str) -> Symbol:
    normalized = value.upper()
    if not normalized.endswith("USDT") or len(normalized) <= 4:
        raise ValueError(f"unsupported symbol format: {value}")
    return Symbol(normalized[:-4], "USDT")


def build_walk_forward_folds(
    *,
    test_start: datetime,
    test_end: datetime,
    train_months: int = 6,
) -> tuple[tuple[datetime, datetime, datetime, datetime], ...]:
    folds = []
    current = test_start
    while current < test_end:
        next_month = _add_months(current, 1)
        if next_month > test_end:
            break
        folds.append((_add_months(current, -train_months), current, current, next_month))
        current = next_month
    return tuple(folds)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = (value.year * 12 + value.month - 1) + months
    year = month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month)


def markdown_summary(payload: dict[str, object], *, limit: int = 20) -> str:
    results = payload["results"]
    if payload.get("mode") == "train_test":
        return "\n".join(
            [
                "# Scheduler Driven Scalping Train/Test Search",
                "",
                "Engine: scheduler_driven",
                "Scheduler path: TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute",
                "",
                f"Train: {payload['train_period']['start_at']} ~ {payload['train_period']['end_at']}",
                f"Test: {payload['test_period']['start_at']} ~ {payload['test_period']['end_at']}",
                "",
                "| Rank | Candidate | Train Ret | Test Ret | Test Daily | Test MDD | Test Trades/day | Test Win |",
                "|---:|---|---:|---:|---:|---:|---:|---:|",
                *(
                    "| {rank} | {candidate_id} | {train_return_ratio} | {test_return_ratio} | {test_daily_return_ratio} | {test_max_drawdown_ratio} | {test_trades_per_day} | {test_net_win_rate} |".format(
                        rank=index,
                        **result,
                    )
                    for index, result in enumerate(results[:limit], start=1)
                ),
                "",
            ]
        )
    if payload.get("mode") == "walk_forward":
        return "\n".join(
            [
                "# Scheduler Driven Multi-Frequency Walk Forward Search",
                "",
                "Engine: scheduler_driven",
                "Scheduler path: TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute",
                "",
                f"Fold count: {payload['fold_count']}",
                f"Candidate count: {payload['candidate_count']}",
                "",
                "| Rank | Candidate | Avg Ret | Avg Daily | Avg Trades/day | Avg Win | Avg ROE | Positive folds | Worst MDD | Trades |",
                "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
                *(
                    "| {rank} | {candidate_id} | {average_return_ratio} | {average_daily_return_ratio} | {average_trades_per_day} | {average_net_win_rate} | {average_net_trade_roe} | {positive_fold_count}/{fold_count} | {worst_max_drawdown_ratio} | {total_trade_count} |".format(
                        rank=index,
                        **result,
                    )
                    for index, result in enumerate(results[:limit], start=1)
                ),
                "",
            ]
        )
    if len(results) == 1:
        result = results[0]
        return "\n".join(
            [
                "# Scheduler Driven Scalping Backtest",
                "",
                f"Engine: {result['engine']}",
                f"Scheduler path: {result['scheduler_path']}",
                "",
                "| Candidate | Return | Daily | MDD | Trades | Trades/day | Avg net ROE | Net win |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
                "| {candidate_id} | {return_ratio} | {daily_return_ratio} | {max_drawdown_ratio} | {trade_count} | {trades_per_day} | {average_net_trade_roe} | {net_win_rate} |".format(
                    **result
                ),
                "",
            ]
        )
    return "\n".join(
        [
            "# Scheduler Driven Scalping Backtest",
            "",
            "Engine: scheduler_driven",
            "Scheduler path: TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute",
            "",
            "| Rank | Candidate | Return | Daily | MDD | Trades | Trades/day | Avg net ROE | Net win | Guard skips |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            *(
                "| {rank} | {candidate_id} | {return_ratio} | {daily_return_ratio} | {max_drawdown_ratio} | {trade_count} | {trades_per_day} | {average_net_trade_roe} | {net_win_rate} | {skipped_by_guard} |".format(
                    rank=index,
                    **result,
                )
                for index, result in enumerate(results[:limit], start=1)
            ),
            "",
        ]
    )


if __name__ == "__main__":
    main()
