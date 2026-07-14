import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.scheduler_driven_scalping_backtest import (
    BacktestPosition,
    SchedulerBacktestCandidate,
    StrategyCandidateSpec,
    alpha_entry_candidates,
    build_strategies,
    build_walk_forward_folds,
    candidate_definition_hash,
    candidate_manifest,
    counter_microstructure_candidates,
    metrics_positioning_candidates,
    discovered_metrics_candidates,
    maybe_close_position,
    load_market_feature_cache,
    microstructure_alpha_candidates,
    run_walk_forward_search,
    summarize_walk_forward_results,
    run_scheduler_driven_backtest,
    write_candidate_manifest,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.signal import SignalDirection
from src.domain.strategy.implementations.microstructure_alpha_strategy import (
    FlowConfirmedBreakoutStrategy,
    FlowExhaustionReversalStrategy,
    MicrostructureRegimeRouterStrategy,
    MultiTimeframeTrendPullbackStrategy,
    PremiumFundingReversionStrategy,
    SessionOpeningRangeStrategy,
    InvertedSignalStrategy,
    OpenInterestDivergenceStrategy,
    OpenInterestImpulseStrategy,
    PositioningCrowdingReversalStrategy,
)
from src.domain.strategy import StrategyResult
from src.domain.signal import Signal


def test_deferred_strategy_registry_is_complete_and_evidence_exists() -> None:
    from scripts.deferred_strategy_registry import (
        REGISTRY_PATH,
        load_deferred_strategy_registry,
    )

    payload = load_deferred_strategy_registry()
    project_root = REGISTRY_PATH.parents[2]

    assert {family["candidate_group"] for family in payload["families"]} == {
        "all",
        "exact",
        "multi",
        "alpha",
        "microstructure",
        "counter",
        "metrics",
        "discovered",
    }
    for family in payload["families"]:
        assert family["status"] in {"failed", "deferred", "superseded"}
        assert family["reason"]
        assert family["revisit_only_if"]
        for evidence in family["evidence"]:
            assert (project_root / evidence).is_file(), evidence


def test_scheduler_cli_blocks_deferred_default_group(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    monkeypatch.setattr(sys, "argv", ["scheduler_driven_scalping_backtest.py", "--list-candidates"])

    with pytest.raises(ValueError, match="candidate group 'all' is deferred"):
        module.main()


def test_scheduler_cli_can_list_deferred_candidate_with_explicit_opt_in(
    monkeypatch,
    capsys,
) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scheduler_driven_scalping_backtest.py",
            "--candidate-group",
            "discovered",
            "--candidate-id",
            "discovered-global-up-reversal-hold60",
            "--include-deferred",
            "--list-candidates",
        ],
    )

    module.main()

    payload = json.loads(capsys.readouterr().out)
    assert [candidate["candidate_id"] for candidate in payload["candidates"]] == [
        "discovered-global-up-reversal-hold60"
    ]


def test_programmatic_backtest_requires_opt_in_for_deferred_candidate() -> None:
    candidate = discovered_metrics_candidates()[0]
    market = _flat_market()

    with pytest.raises(ValueError, match="candidate 'discovered-global-up-reversal-hold15' is deferred"):
        run_scheduler_driven_backtest(
            market,
            start_at=market.candles[0].opened_at,
            end_at=market.candles[-1].closed_at,
            candidate=candidate,
        )

    result = run_scheduler_driven_backtest(
        market,
        start_at=market.candles[0].opened_at,
        end_at=market.candles[-1].closed_at,
        candidate=candidate,
        include_deferred=True,
    )

    assert result["candidate_id"] == candidate.candidate_id


def test_programmatic_search_paths_require_opt_in_for_deferred_candidates() -> None:
    from scripts.scheduler_driven_scalping_backtest import run_train_test_search

    candidate = microstructure_alpha_candidates()[0]

    with pytest.raises(ValueError, match="candidate 'micro-mtf-balanced-tight' is deferred"):
        run_walk_forward_search(_flat_market(), (candidate,), folds=())
    with pytest.raises(ValueError, match="candidate 'micro-mtf-balanced-tight' is deferred"):
        run_train_test_search(_flat_market(), (candidate,))


def test_every_legacy_aggregate_candidate_is_deferred() -> None:
    from scripts.deferred_strategy_registry import ensure_candidate_ids_allowed
    from scripts.scheduler_driven_scalping_backtest import build_scheduler_candidates

    candidates = build_scheduler_candidates()

    for candidate in candidates:
        with pytest.raises(ValueError, match="is deferred"):
            ensure_candidate_ids_allowed((candidate.candidate_id,))


def test_programmatic_default_candidate_requires_deferred_opt_in() -> None:
    market = _flat_market()

    with pytest.raises(ValueError, match="balanced-tp012-sl010-balanced-guard-a"):
        run_scheduler_driven_backtest(
            market,
            start_at=market.candles[0].opened_at,
            end_at=market.candles[-1].closed_at,
        )


def test_scheduler_single_mode_runs_the_selected_candidate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    selected_id = "discovered-global-up-reversal-hold60"
    captured = []
    monkeypatch.setattr(module, "load_period_market", lambda period: _flat_market())
    monkeypatch.setattr(module, "RESULTS_PATH", tmp_path / "results.json")
    monkeypatch.setattr(module, "SUMMARY_PATH", tmp_path / "summary.md")
    monkeypatch.setattr(module, "markdown_summary", lambda payload, limit: "summary")
    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda *args, **kwargs: captured.append(kwargs["candidate"].candidate_id)
        or {"candidate_id": kwargs["candidate"].candidate_id},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "scheduler_driven_scalping_backtest.py",
            "--mode",
            "single",
            "--candidate-group",
            "discovered",
            "--candidate-id",
            selected_id,
            "--include-deferred",
        ],
    )

    module.main()

    assert captured == [selected_id]


def test_maybe_close_position_enforces_max_holding_bars() -> None:
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    symbol = Symbol("BTC", "USDT")
    candles = tuple(
        Candle(
            symbol=symbol,
            timeframe=Timeframe(1, "m"),
            opened_at=opened_at + timedelta(minutes=index),
            closed_at=opened_at + timedelta(minutes=index + 1),
            open_price=Decimal("100"),
            high_price=Decimal("101"),
            low_price=Decimal("99"),
            close_price=Decimal("100"),
            volume=Decimal("1"),
        )
        for index in range(3)
    )
    position = BacktestPosition(
        direction=SignalDirection.LONG,
        entry_price=Decimal("100"),
        quantity=Decimal("1"),
        take_profit=Decimal("110"),
        stop_loss=Decimal("90"),
        opened_index=0,
        entry_fee=Decimal("0.04"),
        margin=Decimal("50"),
    )

    trade = maybe_close_position(
        position,
        MarketSnapshot(candles),
        2,
        max_holding_bars=2,
    )

    assert trade is not None
    assert trade.exit_reason == "max_holding_time"
    assert trade.holding_bars == 2


@pytest.mark.parametrize("value", (0, -1, True))
def test_candidate_rejects_invalid_max_holding_bars(value: object) -> None:
    with pytest.raises(ValueError, match="max_holding_bars"):
        SchedulerBacktestCandidate(
            candidate_id="invalid-holding",
            strategies=(StrategyCandidateSpec("mtf", {}),),
            take_profit_ratio=Decimal("0.01"),
            stop_loss_ratio=Decimal("0.01"),
            equity_ratio=Decimal("0.01"),
            leverage=Decimal("1"),
            max_holding_bars=value,
        )


def test_scheduler_driven_backtest_uses_scheduler_path_without_external_io() -> None:
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    candles = tuple(
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            opened_at=opened_at + timedelta(minutes=index),
            closed_at=opened_at + timedelta(minutes=index + 1),
            open_price=Decimal("100"),
            high_price=Decimal("100"),
            low_price=Decimal("100"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
        )
        for index in range(300)
    )

    result = run_scheduler_driven_backtest(
        MarketSnapshot(candles),
        start_at=candles[0].opened_at,
        end_at=candles[-1].closed_at,
        include_deferred=True,
    )

    assert result["engine"] == "scheduler_driven"
    assert result["scheduler_path"] == "TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute"
    assert result["signal_count"] == 39
    assert result["trade_count"] == 0


def test_scheduler_backtest_default_output_matches_explicit_legacy_options() -> None:
    market = _flat_market()
    kwargs = {
        "start_at": market.candles[0].opened_at,
        "end_at": market.candles[-1].closed_at,
        "include_deferred": True,
    }

    implicit = run_scheduler_driven_backtest(market, **kwargs)
    explicit = run_scheduler_driven_backtest(
        market,
        **kwargs,
        initial_equity=Decimal("10000"),
        include_trade_details=False,
        force_close_at_end=True,
    )

    assert implicit == explicit
    assert "trades" not in implicit


def test_scheduler_backtest_can_emit_forced_close_trade_details(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    class AlwaysLong:
        def evaluate(self, context):
            return StrategyResult(
                name="always-long",
                signal=Signal(SignalDirection.LONG, Decimal("1")),
            )

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysLong(),))
    market = _flat_market()
    candidate = SchedulerBacktestCandidate(
        candidate_id="weekly-test-candidate",
        strategies=(StrategyCandidateSpec("unused", {}),),
        take_profit_ratio=Decimal("0.5"),
        stop_loss_ratio=Decimal("0.5"),
        equity_ratio=Decimal("0.1"),
        leverage=Decimal("2"),
        candle_limit=1,
    )

    forced = run_scheduler_driven_backtest(
        market,
        start_at=market.opened_at,
        end_at=market.closed_at,
        candidate=candidate,
        initial_equity=Decimal("1234"),
        include_trade_details=True,
        force_close_at_end=True,
    )
    left_open = run_scheduler_driven_backtest(
        market,
        start_at=market.opened_at,
        end_at=market.closed_at,
        candidate=candidate,
        initial_equity=Decimal("1234"),
        include_trade_details=True,
        force_close_at_end=False,
    )

    assert forced["scheduler_path"] == "TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute"
    assert forced["trade_count"] == 1
    assert forced["trades"][-1]["exit_reason"] == "end_of_data"
    assert Decimal(forced["trades"][-1]["fee_paid"]) > 0
    assert forced["trades"][-1]["entry_at"] is not None
    assert forced["trades"][-1]["exit_at"] is not None
    assert left_open["trade_count"] == 0
    assert left_open["trades"] == []
    assert left_open["net_pnl"] == "0"
    assert left_open["position_open_at_end"] is True
    assert forced["position_open_at_end"] is False


@pytest.mark.parametrize("initial_equity", (Decimal("0"), Decimal("-1"), Decimal("NaN"), True))
def test_scheduler_backtest_rejects_invalid_initial_equity(initial_equity) -> None:
    market = _flat_market()

    with pytest.raises((TypeError, ValueError), match="initial_equity"):
        run_scheduler_driven_backtest(
            market,
            start_at=market.opened_at,
            end_at=market.closed_at,
            initial_equity=initial_equity,
            include_deferred=True,
        )


def test_scheduler_driven_backtest_accepts_non_btc_symbol() -> None:
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    symbol = Symbol("ETH", "USDT")
    timeframe = Timeframe(1, "m")
    candles = tuple(
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            opened_at=opened_at + timedelta(minutes=index),
            closed_at=opened_at + timedelta(minutes=index + 1),
            open_price=Decimal("100"),
            high_price=Decimal("100"),
            low_price=Decimal("100"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
        )
        for index in range(300)
    )

    result = run_scheduler_driven_backtest(
        MarketSnapshot(candles),
        start_at=candles[0].opened_at,
        end_at=candles[-1].closed_at,
        symbol=symbol,
        include_deferred=True,
    )

    assert result["symbol"] == "ETHUSDT"


def test_summarize_walk_forward_results_averages_candidate_folds() -> None:
    summary = summarize_walk_forward_results(
        {
            "candidate-a": [
                {
                    "return_ratio": "0.10",
                    "daily_return_ratio": "0.002",
                    "trades_per_day": "3",
                    "net_win_rate": "0.60",
                    "average_net_trade_roe": "0.010",
                    "average_net_trade_expectancy_ratio": "0.0008",
                    "max_drawdown_ratio": "0.05",
                    "trade_count": 30,
                },
                {
                    "return_ratio": "-0.02",
                    "daily_return_ratio": "-0.001",
                    "trades_per_day": "1",
                    "net_win_rate": "0.40",
                    "average_net_trade_roe": "-0.004",
                    "average_net_trade_expectancy_ratio": "-0.0002",
                    "max_drawdown_ratio": "0.08",
                    "trade_count": 10,
                },
            ],
            "candidate-b": [
                {
                    "return_ratio": "0.03",
                    "daily_return_ratio": "0.001",
                    "trades_per_day": "2",
                    "net_win_rate": "0.50",
                    "average_net_trade_roe": "0.002",
                    "average_net_trade_expectancy_ratio": "0.0003",
                    "max_drawdown_ratio": "0.03",
                    "trade_count": 20,
                }
            ],
        }
    )

    candidate_a = next(row for row in summary if row["candidate_id"] == "candidate-a")
    assert candidate_a["fold_count"] == 2
    assert candidate_a["positive_fold_count"] == 1
    assert candidate_a["total_trade_count"] == 40
    assert candidate_a["average_return_ratio"] == "0.04"
    assert candidate_a["average_daily_return_ratio"] == "0.0005"
    assert candidate_a["average_net_trade_expectancy_ratio"] == "0.0003"
    assert candidate_a["worst_max_drawdown_ratio"] == "0.08"


def test_build_walk_forward_folds_uses_monthly_oos_tests_with_six_month_train() -> None:
    folds = build_walk_forward_folds(
        test_start=datetime(2021, 1, 1, tzinfo=timezone.utc),
        test_end=datetime(2021, 4, 1, tzinfo=timezone.utc),
    )

    assert folds == (
        (
            datetime(2020, 7, 1, tzinfo=timezone.utc),
            datetime(2021, 1, 1, tzinfo=timezone.utc),
            datetime(2021, 1, 1, tzinfo=timezone.utc),
            datetime(2021, 2, 1, tzinfo=timezone.utc),
        ),
        (
            datetime(2020, 8, 1, tzinfo=timezone.utc),
            datetime(2021, 2, 1, tzinfo=timezone.utc),
            datetime(2021, 2, 1, tzinfo=timezone.utc),
            datetime(2021, 3, 1, tzinfo=timezone.utc),
        ),
        (
            datetime(2020, 9, 1, tzinfo=timezone.utc),
            datetime(2021, 3, 1, tzinfo=timezone.utc),
            datetime(2021, 3, 1, tzinfo=timezone.utc),
            datetime(2021, 4, 1, tzinfo=timezone.utc),
        ),
    )


def test_run_walk_forward_search_exports_flat_candidate_monthly_fold_series(monkeypatch) -> None:
    symbol = Symbol("ETH", "USDT")
    timeframe = Timeframe(1, "m")
    candle = Candle(
        symbol=symbol,
        timeframe=timeframe,
        opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        closed_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        open_price=Decimal("100"),
        high_price=Decimal("100"),
        low_price=Decimal("100"),
        close_price=Decimal("100"),
        volume=Decimal("10"),
    )
    candidate = SchedulerBacktestCandidate(
        candidate_id="candidate-a",
        strategies=(StrategyCandidateSpec("stub", {}),),
        take_profit_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.02"),
        equity_ratio=Decimal("0.1"),
        leverage=Decimal("3"),
    )
    folds = (
        (
            datetime(2025, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 2, 1, tzinfo=timezone.utc),
        ),
    )

    def fake_backtest(*args, **kwargs):
        return {
            "candidate_id": kwargs["candidate"].candidate_id,
            "symbol": kwargs["symbol"].pair,
            "return_ratio": "0.12",
            "daily_return_ratio": "0.004",
            "trade_count": 7,
            "trades_per_day": "0.2258064516129032258064516129",
            "max_drawdown_ratio": "0.03",
            "net_win_rate": "0.57",
            "average_net_trade_roe": "0.015",
            "average_net_trade_expectancy_ratio": "0.001714285714285714285714285714",
            "candidate": {"candidate_id": kwargs["candidate"].candidate_id},
        }

    monkeypatch.setattr(
        "scripts.scheduler_driven_scalping_backtest.run_scheduler_driven_backtest",
        fake_backtest,
    )

    payload = run_walk_forward_search(
        MarketSnapshot((candle,)),
        (candidate,),
        folds=folds,
        symbol=symbol,
    )

    assert payload["candidate_monthly_fold_series"] == [
        {
            "candidate_id": "candidate-a",
            "symbol": "ETHUSDT",
            "fold": 1,
            "test_start_at": "2026-01-01T00:00:00+00:00",
            "test_end_at": "2026-02-01T00:00:00+00:00",
            "return_ratio": "0.12",
            "daily_return_ratio": "0.004",
            "trade_count": 7,
            "trades_per_day": "0.2258064516129032258064516129",
            "max_drawdown_ratio": "0.03",
            "net_win_rate": "0.57",
            "average_net_trade_roe": "0.015",
        }
    ]


def test_alpha_entry_candidates_include_new_ohlcv_alpha_families() -> None:
    candidate_ids = {candidate.candidate_id for candidate in alpha_entry_candidates()}

    assert any(candidate_id.startswith("alpha-sweep-") for candidate_id in candidate_ids)
    assert any(candidate_id.startswith("alpha-dryup-breakout-") for candidate_id in candidate_ids)
    assert any(candidate_id.startswith("alpha-exhaustion-") for candidate_id in candidate_ids)
    assert any(candidate_id.startswith("alpha-router-new-balanced-") for candidate_id in candidate_ids)


def test_microstructure_candidate_universe_is_frozen_at_thirty_six() -> None:
    candidates = microstructure_alpha_candidates()
    ids = [candidate.candidate_id for candidate in candidates]

    assert len(candidates) == 36
    assert len(set(ids)) == 36
    for family in ("mtf", "flow-breakout", "flow-exhaustion", "premium-funding", "session-range", "micro-router"):
        for strength in ("balanced", "strict"):
            for profile in ("tight", "balanced", "wide"):
                assert f"micro-{family}-{strength}-{profile}" in ids
    assert all(candidate.strategies[0].params for candidate in candidates)
    assert len({candidate.guard for candidate in candidates}) == 1


def test_microstructure_candidates_construct_all_six_strategy_classes() -> None:
    candidates = microstructure_alpha_candidates()
    by_kind = {candidate.strategies[0].kind: candidate for candidate in candidates}

    expected = {
        "mtf": MultiTimeframeTrendPullbackStrategy,
        "flow_breakout": FlowConfirmedBreakoutStrategy,
        "flow_exhaustion": FlowExhaustionReversalStrategy,
        "premium_funding": PremiumFundingReversionStrategy,
        "session_range": SessionOpeningRangeStrategy,
        "micro_router": MicrostructureRegimeRouterStrategy,
    }
    assert set(by_kind) == set(expected)
    for kind, strategy_type in expected.items():
        assert isinstance(build_strategies(by_kind[kind])[0], strategy_type)


def test_counter_microstructure_candidate_universe_has_five_families() -> None:
    candidates = counter_microstructure_candidates()
    ids = [candidate.candidate_id for candidate in candidates]

    assert len(candidates) == 30
    assert len(set(ids)) == 30
    for family in (
        "mtf",
        "flow-breakout",
        "flow-exhaustion",
        "session-range",
        "micro-router",
    ):
        for strength in ("balanced", "strict"):
            for profile in ("tight", "balanced", "wide"):
                candidate_id = f"counter-{family}-{strength}-{profile}"
                assert candidate_id in ids
                candidate = next(item for item in candidates if item.candidate_id == candidate_id)
                assert isinstance(build_strategies(candidate)[0], InvertedSignalStrategy)


def test_metrics_positioning_candidate_universe_has_three_families() -> None:
    candidates = metrics_positioning_candidates()
    by_kind = {candidate.strategies[0].kind: candidate for candidate in candidates}

    assert len(candidates) == 18
    assert len({candidate.candidate_id for candidate in candidates}) == 18
    expected = {
        "oi_impulse": OpenInterestImpulseStrategy,
        "positioning_crowding": PositioningCrowdingReversalStrategy,
        "oi_divergence": OpenInterestDivergenceStrategy,
    }
    assert set(by_kind) == set(expected)
    for kind, strategy_type in expected.items():
        assert isinstance(build_strategies(by_kind[kind])[0], strategy_type)


def test_discovered_metrics_candidates_use_time_exit() -> None:
    candidates = discovered_metrics_candidates()

    assert len(candidates) == 5
    assert {candidate.max_holding_bars for candidate in candidates} == {15, 30, 60}
    assert all(candidate.take_profit_ratio == Decimal("0.10") for candidate in candidates)


def _write_feature_cache(
    tmp_path: Path,
    rows: list[dict[str, object]],
    *,
    manifest_override: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    cache_path = tmp_path / "features.jsonl"
    cache_path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    sources = sorted(
        {
            feature["source"]
            for row in rows
            for feature in row["features"].values()
        }
        | {
            source
            for row in rows
            for source in row["unavailable_sources"]
        }
    )
    manifest = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "row_count": len(rows),
        "output_hash": hashlib.sha256(cache_path.read_bytes()).hexdigest(),
        "source_coverage": {
            source: {
                "available_rows": sum(
                    source in {feature["source"] for feature in row["features"].values()}
                    for row in rows
                ),
                "unavailable_rows": sum(source in row["unavailable_sources"] for row in rows),
                "budget_skipped_archives": [],
            }
            for source in sources
        },
        "provenance": {"fixture": {"venue": "binance", "dataset": "historical"}},
    }
    manifest.update(manifest_override or {})
    manifest_path = tmp_path / "features.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return cache_path, manifest_path


def _feature_row(measured_at: str = "2026-01-01T00:01:00+00:00") -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "measured_at": measured_at,
        "features": {
            "taker_imbalance": {
                "value": "0.25",
                "source": "aggTrades",
                "observed_at": measured_at,
                "available_at": measured_at,
            }
        },
        "unavailable_sources": ["fundingRate"],
    }


def test_feature_cache_reconstructs_task3_payload_and_hides_future_rows(tmp_path: Path) -> None:
    cache_path, manifest_path = _write_feature_cache(tmp_path, [_feature_row()])

    loaded = load_market_feature_cache(
        cache_path,
        manifest_path=manifest_path,
        expected_symbol=Symbol("BTC", "USDT"),
        expected_timeframe=Timeframe(1, "m"),
    )

    before = loaded.provider.load_features(
        Symbol("BTC", "USDT"), Timeframe(1, "m"), datetime(2026, 1, 1, 0, 0, 59, 999999, tzinfo=timezone.utc)
    )
    at_time = loaded.provider.load_features(
        Symbol("BTC", "USDT"), Timeframe(1, "m"), datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    )
    assert before.values == ()
    assert at_time.require("taker_imbalance").value == Decimal("0.25")
    assert loaded.source_coverage == {"aggTrades": 1, "fundingRate": 0}
    assert loaded.unavailable_counts == {"aggTrades": 0, "fundingRate": 1}
    assert loaded.provenance == {"fixture": {"venue": "binance", "dataset": "historical"}}


def test_feature_cache_streams_large_jsonl_without_read_text(monkeypatch, tmp_path: Path) -> None:
    rows = [
        _feature_row(
            (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)).isoformat()
        )
        for index in range(1500)
    ]
    cache_path, manifest_path = _write_feature_cache(tmp_path, rows)
    original_read_text = Path.read_text

    def guarded_read_text(path, *args, **kwargs):
        if path == cache_path:
            raise AssertionError("JSONL cache must be streamed")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    loaded = load_market_feature_cache(cache_path, manifest_path=manifest_path)

    assert loaded.source_coverage["aggTrades"] == 1500


def test_empty_feature_cache_is_valid_and_marks_requested_sources_unavailable(tmp_path: Path) -> None:
    coverage = {
        source: {
            "available_rows": 0,
            "unavailable_rows": 0,
            "budget_skipped_archives": [],
        }
        for source in ("aggTrades", "fundingRate")
    }
    cache_path, manifest_path = _write_feature_cache(
        tmp_path,
        [],
        manifest_override={"source_coverage": coverage},
    )

    loaded = load_market_feature_cache(cache_path, manifest_path=manifest_path)
    features = loaded.provider.load_features(
        Symbol("BTC", "USDT"),
        Timeframe(1, "m"),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert loaded.source_coverage == {"aggTrades": 0, "fundingRate": 0}
    assert loaded.unavailable_counts == {"aggTrades": 0, "fundingRate": 0}
    assert features.values == ()
    assert features.unavailable_sources == ("aggTrades", "fundingRate")


@pytest.mark.parametrize(
    "mutate, error",
    [
        (lambda rows: rows + rows, "duplicate"),
        (lambda rows: [{**rows[0], "symbol": "ETHUSDT"}], "symbol"),
        (lambda rows: [{**rows[0], "timeframe": "5m"}], "timeframe"),
        (lambda rows: [{**rows[0], "measured_at": "2026-01-01T09:01:00+09:00"}], "UTC"),
    ],
)
def test_feature_cache_rejects_duplicates_and_identity_conflicts(tmp_path: Path, mutate, error: str) -> None:
    cache_path, manifest_path = _write_feature_cache(tmp_path, mutate([_feature_row()]))

    with pytest.raises(ValueError, match=error):
        load_market_feature_cache(
            cache_path,
            manifest_path=manifest_path,
            expected_symbol=Symbol("BTC", "USDT"),
            expected_timeframe=Timeframe(1, "m"),
        )


def test_feature_cache_never_accepts_corrupt_json_or_hash(tmp_path: Path) -> None:
    cache_path, manifest_path = _write_feature_cache(tmp_path, [_feature_row()])
    cache_path.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cache pair"):
        load_market_feature_cache(cache_path, manifest_path=manifest_path)


@pytest.mark.parametrize("field,value", [("symbol", "ETHUSDT"), ("timeframe", "5m")])
def test_feature_cache_rejects_manifest_identity_conflicts(tmp_path: Path, field: str, value: str) -> None:
    cache_path, manifest_path = _write_feature_cache(
        tmp_path,
        [_feature_row()],
        manifest_override={field: value},
    )

    with pytest.raises(ValueError, match=field):
        load_market_feature_cache(cache_path, manifest_path=manifest_path)


@pytest.mark.parametrize(
    "manifest_override",
    [
        {"source_coverage": []},
        {"source_coverage": {"aggTrades": []}},
        {"source_coverage": {"aggTrades": {"available_rows": "1", "unavailable_rows": 0, "budget_skipped_archives": []}}},
        {"source_coverage": {"aggTrades": {"available_rows": True, "unavailable_rows": 0, "budget_skipped_archives": []}}},
        {"source_coverage": {"aggTrades": {"available_rows": -1, "unavailable_rows": 2, "budget_skipped_archives": []}}},
        {"source_coverage": {"aggTrades": {"available_rows": 1, "unavailable_rows": 0, "budget_skipped_archives": "none"}}},
        {"provenance": []},
        {"provenance": {"source": "not-a-mapping"}},
        {"row_count": "1"},
        {"row_count": True},
    ],
)
def test_feature_cache_rejects_malformed_manifest_metadata(
    tmp_path: Path,
    manifest_override: dict[str, object],
) -> None:
    cache_path, manifest_path = _write_feature_cache(
        tmp_path,
        [_feature_row()],
        manifest_override=manifest_override,
    )

    with pytest.raises(ValueError, match="manifest"):
        load_market_feature_cache(cache_path, manifest_path=manifest_path)


@pytest.mark.parametrize(
    "manifest_override",
    [
        {"row_count": 2},
        {"source_coverage": {"aggTrades": {"available_rows": 0, "unavailable_rows": 1, "budget_skipped_archives": []}, "fundingRate": {"available_rows": 0, "unavailable_rows": 1, "budget_skipped_archives": []}}},
        {"source_coverage": {"aggTrades": {"available_rows": 1, "unavailable_rows": 0, "budget_skipped_archives": []}}},
        {"source_coverage": {"aggTrades": {"available_rows": 1, "unavailable_rows": 0, "budget_skipped_archives": []}, "fundingRate": {"available_rows": 0, "unavailable_rows": 1, "budget_skipped_archives": []}, "extra": {"available_rows": 0, "unavailable_rows": 1, "budget_skipped_archives": []}}},
    ],
)
def test_feature_cache_rejects_manifest_metadata_inconsistent_with_jsonl(
    tmp_path: Path,
    manifest_override: dict[str, object],
) -> None:
    cache_path, manifest_path = _write_feature_cache(
        tmp_path,
        [_feature_row()],
        manifest_override=manifest_override,
    )

    with pytest.raises(ValueError, match="manifest"):
        load_market_feature_cache(cache_path, manifest_path=manifest_path)


def test_backtest_injects_same_feature_provider_and_exports_provenance(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module
    from src.infrastructure.market_feature import EmptyMarketFeatureProvider

    market = _flat_market()
    provider = EmptyMarketFeatureProvider(("fundingRate",))
    provider.feature_cache_hash = "a" * 64
    provider.feature_source_coverage = {"aggTrades": 10}
    provider.feature_unavailable_counts = {"fundingRate": 3}
    provider.feature_provenance = {"venue": "binance"}
    captured = []
    execute_type = module.ExecuteTradeUseCase
    manage_type = module.ManageOpenPositionUseCase

    class CapturingExecute(execute_type):
        def __init__(self, *args, **kwargs):
            captured.append(kwargs["market_feature_provider"])
            super().__init__(*args, **kwargs)

    class CapturingManage(manage_type):
        def __init__(self, *args, **kwargs):
            captured.append(kwargs["market_feature_provider"])
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(module, "ExecuteTradeUseCase", CapturingExecute)
    monkeypatch.setattr(module, "ManageOpenPositionUseCase", CapturingManage)
    result = run_scheduler_driven_backtest(
        market,
        start_at=market.candles[0].opened_at,
        end_at=market.candles[-1].closed_at,
        market_feature_provider=provider,
        include_deferred=True,
    )

    assert captured == [provider, provider]
    assert result["feature_cache_hash"] == "a" * 64
    assert result["feature_source_coverage"] == {"aggTrades": 10}
    assert result["feature_unavailable_counts"] == {"fundingRate": 3}
    assert result["feature_provenance"] == {"venue": "binance"}
    assert result["candidate_definition_hash"] == candidate_definition_hash(result["candidate"])


def test_candidate_manifest_contains_universe_and_stable_sha256(tmp_path: Path) -> None:
    path = tmp_path / "candidate-manifest.json"
    candidates = microstructure_alpha_candidates()

    payload = write_candidate_manifest(candidates, path)
    encoded_universe = json.dumps(payload["candidates"], sort_keys=True, separators=(",", ":")).encode()

    assert payload["candidate_count"] == 36
    assert payload["candidate_universe_hash"] == hashlib.sha256(encoded_universe).hexdigest()
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_candidate_manifest_rejects_duplicate_candidate_ids() -> None:
    candidate = microstructure_alpha_candidates()[0]

    with pytest.raises(ValueError, match="duplicate candidate_id"):
        candidate_manifest((candidate, candidate))


def test_candidate_manifest_is_canonical_for_equivalent_candidate_order() -> None:
    candidates = microstructure_alpha_candidates()[:3]

    forward = candidate_manifest(candidates)
    reverse = candidate_manifest(tuple(reversed(candidates)))

    assert forward == reverse
    assert [row["candidate_id"] for row in forward["candidates"]] == sorted(
        candidate.candidate_id for candidate in candidates
    )


def test_search_paths_reject_duplicate_candidate_ids_before_execution() -> None:
    from scripts.scheduler_driven_scalping_backtest import run_train_test_search

    candidate = microstructure_alpha_candidates()[0]
    duplicates = (candidate, candidate)

    with pytest.raises(ValueError, match="duplicate candidate_id"):
        run_walk_forward_search(_flat_market(), duplicates, folds=())
    with pytest.raises(ValueError, match="duplicate candidate_id"):
        run_train_test_search(_flat_market(), duplicates)


def _flat_market() -> MarketSnapshot:
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    return MarketSnapshot(
        tuple(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                opened_at=opened_at + timedelta(minutes=index),
                closed_at=opened_at + timedelta(minutes=index + 1),
                open_price=Decimal("100"),
                high_price=Decimal("100"),
                low_price=Decimal("100"),
                close_price=Decimal("100"),
                volume=Decimal("10"),
            )
            for index in range(300)
        )
    )
