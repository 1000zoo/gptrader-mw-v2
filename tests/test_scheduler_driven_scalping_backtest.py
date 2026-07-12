import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.scheduler_driven_scalping_backtest import (
    SchedulerBacktestCandidate,
    StrategyCandidateSpec,
    alpha_entry_candidates,
    build_strategies,
    build_walk_forward_folds,
    candidate_definition_hash,
    candidate_manifest,
    load_market_feature_cache,
    microstructure_alpha_candidates,
    run_walk_forward_search,
    summarize_walk_forward_results,
    run_scheduler_driven_backtest,
    write_candidate_manifest,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.strategy.implementations.microstructure_alpha_strategy import (
    FlowConfirmedBreakoutStrategy,
    FlowExhaustionReversalStrategy,
    MicrostructureRegimeRouterStrategy,
    MultiTimeframeTrendPullbackStrategy,
    PremiumFundingReversionStrategy,
    SessionOpeningRangeStrategy,
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
    )

    assert result["engine"] == "scheduler_driven"
    assert result["scheduler_path"] == "TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute"
    assert result["signal_count"] == 39
    assert result["trade_count"] == 0


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
