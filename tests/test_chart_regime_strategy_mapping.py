from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from scripts.chart_regime_strategy_mapping import (
    run_mapping_episodes,
    run_scheduler_driven_regime_backtest,
)
from scripts.chart_regime_strategy_mapping import _canonical_hash
from scripts.scheduler_driven_scalping_backtest import (
    FEE_RATE,
    SchedulerBacktestCandidate,
    StrategyCandidateSpec,
    feature_provider_config_hash,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe


def test_mapping_module_exposes_scheduler_driven_regime_replay() -> None:
    from scripts.scheduler_driven_scalping_backtest import (
        run_scheduler_driven_regime_backtest as canonical_replay,
    )

    assert run_scheduler_driven_regime_backtest is canonical_replay
from src.domain.regime import build_weekly_episodes


def _minute_market(
    start: datetime,
    weeks: int = 2,
    price: Decimal = Decimal("100"),
    symbol: Symbol | None = None,
    warmup_minutes: int = 300,
) -> MarketSnapshot:
    symbol = symbol or Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    return MarketSnapshot(tuple(
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            opened_at=start + timedelta(minutes=index),
            closed_at=start + timedelta(minutes=index + 1),
            open_price=price,
            high_price=price,
            low_price=price,
            close_price=price,
            volume=Decimal("10"),
        )
        for index in range(-warmup_minutes, weeks * 7 * 24 * 60)
    ))


def _evidence_result(kwargs, **overrides):
    initial = kwargs["initial_equity"]
    result = {
        "candidate_id": kwargs["candidate"].candidate_id,
        "initial_equity": str(initial),
        "final_equity": str(initial),
        "trade_count": 0,
        "trades_per_day": "0",
        "gross_pnl": "0",
        "net_pnl": "0",
        "fee_paid": "0",
        "return_ratio": "0",
        "daily_return_ratio": "0",
        "max_drawdown_ratio": "0",
        "net_win_rate": "0",
        "average_net_trade_roe": "0",
        "average_net_trade_expectancy_ratio": "0",
        "trades": [],
        "feature_cache_hash": None,
        "feature_provenance": {},
        "feature_config_hash": None,
    }
    result.update(overrides)
    return result


def _accounted_trade(
    kwargs,
    *,
    entry_at: datetime,
    exit_at: datetime,
    entry_price: Decimal = Decimal("100"),
    exit_price: Decimal = Decimal("101"),
    quantity: Decimal = Decimal("1"),
    direction: str = "long",
):
    gross = (
        (exit_price - entry_price) * quantity
        if direction == "long"
        else (entry_price - exit_price) * quantity
    )
    fee = (entry_price * quantity + exit_price * quantity) * FEE_RATE
    margin = entry_price * quantity / kwargs["candidate"].leverage
    return {
        "entry_at": entry_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "entry_price": str(entry_price),
        "exit_price": str(exit_price),
        "direction": direction,
        "quantity": str(quantity),
        "margin": str(margin),
        "gross_pnl": str(gross),
        "net_pnl": str(gross - fee),
        "fee_paid": str(fee),
        "exit_reason": "take_profit",
        "holding_bars": int((exit_at - entry_at).total_seconds() // 60),
    }


def _result_for_trades(kwargs, trades, **overrides):
    initial = kwargs["initial_equity"]
    gross = sum((Decimal(item["gross_pnl"]) for item in trades), Decimal("0"))
    net = sum((Decimal(item["net_pnl"]) for item in trades), Decimal("0"))
    fees = sum((Decimal(item["fee_paid"]) for item in trades), Decimal("0"))
    equity = initial
    peak = initial
    max_drawdown = Decimal("0")
    for trade in trades:
        equity += Decimal(trade["net_pnl"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    count = len(trades)
    wins = sum(Decimal(item["net_pnl"]) > 0 for item in trades)
    result = _evidence_result(
        kwargs,
        trade_count=count,
        trades=trades,
        trades_per_day=str(Decimal(count) / Decimal(7)),
        gross_pnl=str(gross),
        net_pnl=str(net),
        fee_paid=str(fees),
        final_equity=str(initial + net),
        return_ratio=str(net / initial),
        daily_return_ratio=str((net / initial) / Decimal(7)),
        net_win_rate=str(Decimal(wins) / Decimal(count) if count else Decimal("0")),
        average_net_trade_roe=str(
            sum(
                (Decimal(item["net_pnl"]) / Decimal(item["margin"]) for item in trades),
                Decimal("0"),
            ) / Decimal(count)
            if count else Decimal("0")
        ),
        average_net_trade_expectancy_ratio=str(
            (net / Decimal(count)) / initial if count else Decimal("0")
        ),
        max_drawdown_ratio=str(max_drawdown),
    )
    result.update(overrides)
    return result


def _candidate(candidate_id: str, *, equity_ratio: str = "0.1") -> SchedulerBacktestCandidate:
    return SchedulerBacktestCandidate(
        candidate_id=candidate_id,
        strategies=(StrategyCandidateSpec("unused", {"threshold": Decimal("2")}),),
        take_profit_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.02"),
        equity_ratio=Decimal(equity_ratio),
        leverage=Decimal("3"),
        candle_limit=1,
    )


def test_mapping_runs_flat_nonoverlapping_weekly_evidence(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    market = _minute_market(start)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=14)))
    assignments = {episodes[0].anchor_at: "cluster-b", episodes[1].anchor_at: "cluster-a"}
    candidates = (_candidate("candidate-b"), _candidate("candidate-a"))
    calls = []

    def fake_backtest(snapshot, **kwargs):
        calls.append((snapshot, kwargs))
        return _evidence_result(kwargs)

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    rows = run_mapping_episodes(
        market,
        episodes=episodes,
        assignments=assignments,
        candidates=candidates,
        initial_equity=Decimal("4321"),
    )

    assert [(row["episode_start_at"], row["candidate_id"]) for row in rows] == [
        ("2026-01-05T00:00:00+00:00", "candidate-a"),
        ("2026-01-05T00:00:00+00:00", "candidate-b"),
        ("2026-01-12T00:00:00+00:00", "candidate-a"),
        ("2026-01-12T00:00:00+00:00", "candidate-b"),
    ]
    assert all(kwargs["initial_equity"] == Decimal("4321") for _, kwargs in calls)
    assert all(kwargs["force_close_at_end"] is True for _, kwargs in calls)
    assert all(kwargs["include_trade_details"] is True for _, kwargs in calls)
    assert [(snapshot.opened_at, snapshot.closed_at) for snapshot, _ in calls] == [
        (episodes[0].start_at - timedelta(minutes=1), episodes[0].end_at),
        (episodes[0].start_at - timedelta(minutes=1), episodes[0].end_at),
        (episodes[1].start_at - timedelta(minutes=1), episodes[1].end_at),
        (episodes[1].start_at - timedelta(minutes=1), episodes[1].end_at),
    ]
    assert all(row["initial_equity"] == "4321" and row["final_equity"] == "4321" for row in rows)


def test_mapping_hashes_are_canonical_and_bind_data_and_candidate(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episode = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    assignments = {start: "cluster-a"}

    first = run_mapping_episodes(_minute_market(start, 1), episodes=episode, assignments=assignments, candidates=(_candidate("a"),))
    same = run_mapping_episodes(_minute_market(start, 1, Decimal("100.0")), episodes=episode, assignments=assignments, candidates=(_candidate("a", equity_ratio="0.10"),), initial_equity=Decimal("1E4"))
    repriced = run_mapping_episodes(_minute_market(start, 1, Decimal("101")), episodes=episode, assignments=assignments, candidates=(_candidate("a"),))
    reconfigured = run_mapping_episodes(_minute_market(start, 1), episodes=episode, assignments=assignments, candidates=(_candidate("a", equity_ratio="0.2"),))

    assert first[0]["data_hash"] == same[0]["data_hash"]
    assert first[0]["candidate_hash"] == same[0]["candidate_hash"]
    assert first[0]["data_hash"] != repriced[0]["data_hash"]
    assert first[0]["candidate_hash"] != reconfigured[0]["candidate_hash"]


@pytest.mark.parametrize("case", ("gap", "assignment", "duplicate_candidate", "non_utc", "missing_data"))
def test_mapping_fails_closed_on_invalid_evidence_inputs(case) -> None:
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=14)))
    assignments = {episode.anchor_at: "cluster" for episode in episodes}
    candidates = (_candidate("a"),)
    market = _minute_market(start)

    if case == "gap":
        broken = list(episodes)
        broken[1] = type(broken[1])(
            anchor_at=broken[1].anchor_at + timedelta(days=7),
            feature_start_at=broken[1].feature_start_at + timedelta(days=7),
            start_at=broken[1].start_at + timedelta(days=7),
            end_at=broken[1].end_at + timedelta(days=7),
        )
        episodes = tuple(broken)
    elif case == "assignment":
        assignments = {episodes[0].anchor_at: "cluster"}
    elif case == "duplicate_candidate":
        candidates = (_candidate("a"), _candidate("a"))
    elif case == "non_utc":
        bad = episodes[0]
        naive = bad.start_at.replace(tzinfo=None)
        episodes = (type(bad)(naive, naive - timedelta(days=7), naive, naive + timedelta(days=7)),)
        assignments = {naive: "cluster"}
    elif case == "missing_data":
        market = _minute_market(start, 1)

    with pytest.raises(ValueError):
        run_mapping_episodes(market, episodes=episodes, assignments=assignments, candidates=candidates)


def test_mapping_requires_explicit_deferred_group_opt_in() -> None:
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    with pytest.raises(ValueError, match="deferred"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidate_groups=("microstructure",),
        )


def test_mapping_resolves_explicit_candidate_from_opted_in_factory(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    rows = run_mapping_episodes(
        _minute_market(start, 1),
        episodes=episodes,
        assignments={start: "cluster"},
        candidate_groups=("microstructure",),
        candidate_ids=("micro-mtf-balanced-tight",),
        include_deferred_groups=("microstructure",),
    )

    assert [row["candidate_id"] for row in rows] == ["micro-mtf-balanced-tight"]

    with pytest.raises(ValueError, match="unknown candidate_id"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidate_groups=("microstructure",),
            candidate_ids=("does-not-exist",),
            include_deferred_groups=("microstructure",),
        )


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"net_pnl": None}, "net_pnl"),
        ({"candidate_id": "wrong"}, "candidate_id"),
        ({"trade_count": True}, "trade_count"),
        ({"fee_paid": "NaN"}, "fee_paid"),
        ({"trades": [{}]}, "trade"),
    ),
)
def test_mapping_rejects_partial_or_malformed_backtest_evidence(
    monkeypatch, override, message
) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs, **override),
    )

    with pytest.raises(ValueError, match=message):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


def test_mapping_rejects_missing_backtest_evidence_field(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    def missing_field(snapshot, **kwargs):
        result = _evidence_result(kwargs)
        del result["net_pnl"]
        return result

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", missing_field)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    with pytest.raises(ValueError, match="missing required fields: net_pnl"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


def test_mapping_data_hash_binds_feature_cache_identity(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    class Provider:
        def __init__(self, cache_hash, config_hash):
            self.feature_cache_hash = cache_hash
            self.feature_provenance = {"provider": "fixture", "config": config_hash}
            self.feature_config_hash = config_hash

    def fake_backtest(snapshot, **kwargs):
        provider = kwargs["market_feature_provider"]
        return _evidence_result(
            kwargs,
            feature_cache_hash=provider.feature_cache_hash,
            feature_provenance=provider.feature_provenance,
            feature_config_hash=feature_provider_config_hash(provider),
        )

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    kwargs = {
        "episodes": episodes,
        "assignments": {start: "cluster"},
        "candidates": (_candidate("a"),),
    }
    first = run_mapping_episodes(
        _minute_market(start, 1),
        **kwargs,
        market_feature_provider=Provider("cache-a", "config-a"),
    )
    changed = run_mapping_episodes(
        _minute_market(start, 1),
        **kwargs,
        market_feature_provider=Provider("cache-b", "config-b"),
    )

    assert first[0]["feature_cache_hash"] == "cache-a"
    assert len(first[0]["feature_config_hash"]) == 64
    assert first[0]["data_hash"] != changed[0]["data_hash"]


def test_mapping_rejects_symbol_mismatch_and_non_minute_market(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    kwargs = {
        "episodes": episodes,
        "assignments": {start: "cluster"},
        "candidates": (_candidate("a"),),
    }

    with pytest.raises(ValueError, match="symbol"):
        run_mapping_episodes(
            _minute_market(start, 1),
            **kwargs,
            symbol=Symbol("ETH", "USDT"),
        )

    daily = MarketSnapshot(tuple(
        Candle(
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "d"),
            opened_at=start + timedelta(days=index),
            closed_at=start + timedelta(days=index + 1),
            open_price=Decimal("100"),
            high_price=Decimal("100"),
            low_price=Decimal("100"),
            close_price=Decimal("100"),
            volume=Decimal("1"),
        )
        for index in range(7)
    ))
    with pytest.raises(ValueError, match="1m"):
        run_mapping_episodes(daily, **kwargs)


def test_mapping_supplies_identical_max_candidate_warmup_to_every_candidate(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    calls = []

    def fake_backtest(snapshot, **kwargs):
        calls.append((snapshot, kwargs))
        return _evidence_result(kwargs)

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    short = _candidate("short")
    long = SchedulerBacktestCandidate(
        candidate_id="long",
        strategies=short.strategies,
        take_profit_ratio=short.take_profit_ratio,
        stop_loss_ratio=short.stop_loss_ratio,
        equity_ratio=short.equity_ratio,
        leverage=short.leverage,
        candle_limit=5,
    )

    run_mapping_episodes(
        _minute_market(start, 1),
        episodes=episodes,
        assignments={start: "cluster"},
        candidates=(short, long),
    )

    expected_context_start = start - timedelta(minutes=5)
    assert len(calls) == 2
    assert all(snapshot.opened_at == expected_context_start for snapshot, _ in calls)
    assert calls[0][0].candles == calls[1][0].candles
    assert all(kwargs["context_start_at"] == expected_context_start for _, kwargs in calls)


def test_canonical_hash_type_tags_decimals_without_spelling_differences() -> None:
    assert _canonical_hash({"value": Decimal("100")}) == _canonical_hash(
        {"value": Decimal("1E2")}
    )
    assert _canonical_hash({"value": Decimal("1")}) != _canonical_hash({"value": "1"})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("return_ratio", "0.1"),
        ("daily_return_ratio", "0.1"),
        ("trades_per_day", "1"),
        ("net_win_rate", "2"),
        ("max_drawdown_ratio", "2"),
        ("average_net_trade_expectancy_ratio", "0.1"),
        ("profit_factor", "1"),
    ),
)
def test_mapping_rejects_tampered_derived_summary(monkeypatch, field, value) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs, **{field: value}),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    with pytest.raises(ValueError, match=field):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("entry_price", "0", "entry_price"),
        ("quantity", "0", "quantity"),
        ("margin", "0", "margin"),
        ("fee_paid", "-0.1", "fee_paid"),
        ("net_pnl", "2", "net_pnl"),
        ("entry_at", "2026-01-04T23:59:00+00:00", "entry_at"),
        ("exit_at", "2026-01-05T00:00:00+00:00", "exit_at"),
        ("holding_bars", 2, "holding_bars"),
    ),
)
def test_mapping_rejects_invalid_trade_accounting_or_bounds(
    monkeypatch, field, value, message
) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def fake_backtest(snapshot, **kwargs):
        trade = _accounted_trade(
            kwargs,
            entry_at=start,
            exit_at=start + timedelta(minutes=1),
        )
        result = _result_for_trades(kwargs, [trade])
        result["trades"][0][field] = value
        return result

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    with pytest.raises(ValueError, match=message):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


@pytest.mark.parametrize(
    ("forgery", "message"),
    (("gross", "gross_pnl"), ("fee", "fee_paid"), ("margin", "margin")),
)
def test_mapping_rejects_coherent_reported_trade_forgery(monkeypatch, forgery, message) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def fake_backtest(snapshot, **kwargs):
        trade = _accounted_trade(kwargs, entry_at=start, exit_at=start + timedelta(minutes=1))
        if forgery == "gross":
            trade["gross_pnl"] = "2"
            trade["fee_paid"] = "0.2"
            trade["net_pnl"] = "1.8"
        elif forgery == "fee":
            trade["fee_paid"] = "0.2"
            trade["net_pnl"] = "0.8"
        else:
            trade["margin"] = "34"
        return _result_for_trades(kwargs, [trade])

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    with pytest.raises(ValueError, match=message):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


@pytest.mark.parametrize("mode", ("overlap", "reordered"))
def test_mapping_rejects_non_chronological_single_position_trades(monkeypatch, mode) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def fake_backtest(snapshot, **kwargs):
        first = _accounted_trade(
            kwargs, entry_at=start, exit_at=start + timedelta(minutes=2)
        )
        second = _accounted_trade(
            kwargs,
            entry_at=start + timedelta(minutes=1 if mode == "overlap" else 2),
            exit_at=start + timedelta(minutes=3),
        )
        trades = [first, second] if mode == "overlap" else [second, first]
        return _result_for_trades(kwargs, trades)

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    with pytest.raises(ValueError, match="chronological|overlap"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


def test_mapping_reconstructs_drawdown_and_allows_equity_below_zero(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    forged = {"enabled": True}

    def fake_backtest(snapshot, **kwargs):
        trade = _accounted_trade(
            kwargs,
            entry_at=start,
            exit_at=start + timedelta(minutes=1),
            entry_price=Decimal("100"),
            exit_price=Decimal("1"),
            quantity=Decimal("200"),
        )
        result = _result_for_trades(kwargs, [trade])
        if forged["enabled"]:
            result["max_drawdown_ratio"] = "0"
        return result

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    kwargs = {
        "episodes": episodes,
        "assignments": {start: "cluster"},
        "candidates": (_candidate("a"),),
    }
    with pytest.raises(ValueError, match="max_drawdown_ratio"):
        run_mapping_episodes(_minute_market(start, 1), **kwargs)

    forged["enabled"] = False
    rows = run_mapping_episodes(_minute_market(start, 1), **kwargs)
    assert Decimal(rows[0]["max_drawdown_ratio"]) > Decimal("1")
