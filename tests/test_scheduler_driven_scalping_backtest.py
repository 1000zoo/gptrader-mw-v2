import hashlib
import json
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.scheduler_driven_scalping_backtest import (
    BacktestPosition,
    BacktestTrade,
    PositionExitPolicy,
    BacktestMarketSnapshot,
    _maximum_adverse_excursion_ratio,
    _trade_payload,
    close_trade,
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
    run_scheduler_driven_daily_regime_backtest,
    run_scheduler_driven_regime_backtest,
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


@pytest.mark.parametrize(
    ("direction", "lows", "highs", "expected"),
    (
        (SignalDirection.LONG, (Decimal("100"), Decimal("95")), (Decimal("103"), Decimal("102")), Decimal("0.05")),
        (SignalDirection.SHORT, (Decimal("98"), Decimal("99")), (Decimal("100"), Decimal("106")), Decimal("0.06")),
        (SignalDirection.LONG, (Decimal("100"), Decimal("100")), (Decimal("102"), Decimal("103")), Decimal("0")),
    ),
)
def test_maximum_adverse_excursion_is_directional_and_includes_exit_candle(direction, lows, highs, expected):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    market = BacktestMarketSnapshot(tuple(
        Candle(symbol, timeframe, start + timedelta(minutes=index),
               start + timedelta(minutes=index + 1), Decimal("100"), highs[index],
               lows[index], Decimal("100"), Decimal("1"))
        for index in range(2)
    ))
    position = BacktestPosition(direction, Decimal("100"), Decimal("1"), Decimal("120"),
                                Decimal("80"), 0, Decimal("0"), Decimal("100"))

    assert _maximum_adverse_excursion_ratio(position, market, 1) == expected


def test_maximum_adverse_excursion_excludes_entry_candle_giant_wick():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    market = BacktestMarketSnapshot(tuple(
        Candle(symbol, timeframe, start + timedelta(minutes=index),
               start + timedelta(minutes=index + 1), Decimal("100"), high,
               low, Decimal("100"), Decimal("1"))
        for index, (high, low) in enumerate(((Decimal("200"), Decimal("1")), (Decimal("101"), Decimal("99"))))
    ))
    long = BacktestPosition(SignalDirection.LONG, Decimal("100"), Decimal("1"), Decimal("120"),
                            Decimal("80"), 0, Decimal("0"), Decimal("100"))
    short = replace(long, direction=SignalDirection.SHORT)
    assert _maximum_adverse_excursion_ratio(long, market, 1) == Decimal("0.01")
    assert _maximum_adverse_excursion_ratio(short, market, 1) == Decimal("0.01")


def test_trade_detail_serialization_rejects_missing_mae_audit() -> None:
    trade = BacktestTrade(
        entry_price=Decimal("100"), exit_price=Decimal("101"),
        direction=SignalDirection.LONG, quantity=Decimal("1"), margin=Decimal("50"),
        gross_pnl=Decimal("1"), net_pnl=Decimal("0.9"), fee_paid=Decimal("0.1"),
        exit_reason="test", holding_bars=1, maximum_adverse_excursion_ratio=None,
    )
    with pytest.raises(ValueError, match="adverse excursion"):
        _trade_payload(trade)


def test_close_trade_without_market_keeps_mae_missing_and_cannot_serialize() -> None:
    position = BacktestPosition(
        SignalDirection.LONG, Decimal("100"), Decimal("1"), Decimal("110"),
        Decimal("90"), 0, Decimal("0.04"), Decimal("50"),
    )
    trade = close_trade(position, Decimal("101"), "unit", 1)
    assert trade.maximum_adverse_excursion_ratio is None
    with pytest.raises(ValueError, match="adverse excursion"):
        _trade_payload(trade)
from scripts.chart_regime_strategy_mapping import _validation_replay_metrics
from src.domain.strategy import StrategyResult
from src.domain.signal import Signal
from src.domain.regime.model import ClusterAssignment
from src.domain.regime.selection import (
    SelectionArtifactSnapshot,
    SelectionConfidenceThresholds,
)
from src.infrastructure.market_feature import EmptyMarketFeatureProvider


class _ScriptedAssignments:
    def __init__(self, assignments):
        self.assignments = assignments
        self.calls = []

    def assignment_at(self, boundary_at, candles):
        self.calls.append(boundary_at)
        return ClusterAssignment(
            fingerprint=self.assignments[boundary_at],
            dominant_probability=1.0,
            second_probability=0.0,
            distance=0.0,
        )


def _selection_snapshot(mapping):
    return SelectionArtifactSnapshot(
        model_artifact_hash="a" * 64,
        mapping_artifact_hash="b" * 64,
        cluster_strategy_mapping=mapping,
        model_type="kmeans",
        confidence_thresholds=SelectionConfidenceThresholds(
            model_type="kmeans",
            kmeans_max_standardized_distances={key: 1.0 for key in mapping},
        ),
    )


def _regime_market(
    start, hours=9, *, profit_at=None, context_minutes=1, close_at=None, vary=False
):
    candles = []
    for index in range(-context_minutes, hours * 60):
        opened = start + timedelta(minutes=index)
        profit = profit_at is not None and opened == profit_at
        base = Decimal("100") + (Decimal(index % 60) / Decimal("100") if vary else Decimal("0"))
        final_close = close_at if close_at is not None and index == hours * 60 - 1 else base
        candles.append(Candle(
            symbol=Symbol("BTC", "USDT"), timeframe=Timeframe(1, "m"),
            opened_at=opened, closed_at=opened + timedelta(minutes=1),
            open_price=base,
            high_price=Decimal("102") if profit else max(base, final_close) + (Decimal("0.01") if vary else Decimal("0")),
            low_price=min(base, final_close) - (Decimal("0.01") if vary else Decimal("0")),
            close_price=final_close, volume=Decimal("1") + Decimal(index % 17) / Decimal("10") if vary else Decimal("1"),
        ))
    return MarketSnapshot(tuple(candles))


def _regime_candidate(candidate_id="strategy-x"):
    return SchedulerBacktestCandidate(
        candidate_id=candidate_id,
        strategies=(StrategyCandidateSpec("unused", {}),),
        take_profit_ratio=Decimal("0.01"), stop_loss_ratio=Decimal("0.5"),
        equity_ratio=Decimal("0.1"), leverage=Decimal("2"), candle_limit=1,
    )


@pytest.mark.parametrize(
    "policy",
    (
        None,
        1,
        "opposite",
        "ACTIVE_STRATEGY_OPPOSITE",
        "entry_owner_only",
        "active_strategy_opposite",
    ),
)
def test_daily_regime_replay_rejects_noncanonical_exit_policy(policy) -> None:
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="position_exit_policy"):
        run_scheduler_driven_daily_regime_backtest(
            _regime_market(start, hours=1),
            start_at=start,
            end_at=start + timedelta(hours=1),
            candidates=(_regime_candidate(),),
            model_artifact=object(),
            mapping_artifact=object(),
            position_exit_policy=policy,
        )


def test_regime_candidate_bundle_retains_exact_entry_signal_generator(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    class AlwaysWait:
        def evaluate(self, context):
            return StrategyResult("wait", Signal.wait())

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysWait(),))
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    selected = module.BacktestMarketSnapshot(_regime_market(start).candles)
    market_data = module.CursorMarketData(selected)
    signal_log = module.InMemorySignalLogRepository()
    execution = module.BacktestOrderExecution(market_data)
    bundle = module._build_regime_bundle(
        _regime_candidate(),
        market_data=market_data,
        signal_log=signal_log,
        order_execution=execution,
        feature_provider=EmptyMarketFeatureProvider(),
        initial_equity=Decimal("10000"),
        audited_candidate_definition_hash="a" * 64,
    )

    assert bundle.signal_generator is bundle.scheduler._execute_trade_usecase._signal_generator


def test_daily_regime_active_opposite_exits_without_same_candle_reversal(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module
    from src.domain.regime.model import ClusterAssignment
    from src.domain.regime.mapping import candidate_universe_hash
    from tests.application.usecases.regime.test_select_daily_strategy_usecase import (
        COMPONENTS,
        _FrozenModel,
        _candles,
        _mapping,
    )

    class Scripted:
        def __init__(self):
            self.calls = 0

        def evaluate(self, context):
            self.calls += 1
            direction = SignalDirection.LONG if self.calls != 2 else SignalDirection.SHORT
            return StrategyResult("scripted", Signal(direction, Decimal("1")))

    monkeypatch.setattr(
        module,
        "build_strategies",
        lambda candidate: (Scripted(),),
    )
    start = datetime(2026, 4, 6, tzinfo=timezone.utc)
    candidates = (
        _regime_candidate("candidate-a"),
        _regime_candidate("candidate-b"),
    )
    hashes = {
        item.candidate_id: module._audited_candidate_hash(
            item, symbol=Symbol("BTC", "USDT"), initial_equity=Decimal("10000")
        )
        for item in candidates
    }
    mapping = _mapping()
    mapping = replace(
        mapping,
        candidate_hashes=hashes,
        candidate_universe_hash=candidate_universe_hash(tuple(sorted(hashes))),
        candidate_assessments=tuple(
            replace(item, candidate_hash=hashes[item.candidate_id])
            for item in mapping.candidate_assessments
        ),
    )
    candles = _candles(count=4325, start=start - timedelta(days=3))

    result = run_scheduler_driven_daily_regime_backtest(
        MarketSnapshot(candles),
        start_at=start,
        end_at=start + timedelta(minutes=5),
        candidates=candidates,
        model_artifact=_FrozenModel(
            ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)
        ),
        mapping_artifact=mapping,
        candidate_manifest=tuple(sorted(hashes.items())),
        position_exit_policy=PositionExitPolicy.ACTIVE_STRATEGY_OPPOSITE,
    )

    opposite = next(
        trade
        for trade in result["trades"]
        if trade["exit_reason"] == "active_strategy_opposite_signal"
    )
    assert opposite["exit_audit_hash"]
    next_entries = [
        trade for trade in result["trades"] if trade["entry_at"] > opposite["exit_at"]
    ]
    assert next_entries[0]["entry_at"] >= (
        datetime.fromisoformat(opposite["exit_at"]) + timedelta(minutes=1)
    ).isoformat()
    assert result["active_opposite_exit_count"] == 1

    repeated = run_scheduler_driven_daily_regime_backtest(
        MarketSnapshot(candles),
        start_at=start,
        end_at=start + timedelta(minutes=5),
        candidates=candidates,
        model_artifact=_FrozenModel(
            ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)
        ),
        mapping_artifact=mapping,
        candidate_manifest=tuple(sorted(hashes.items())),
        position_exit_policy=PositionExitPolicy.ACTIVE_STRATEGY_OPPOSITE,
    )
    assert repeated == result
    assert repeated["result_hash"] == result["result_hash"]


def _daily_test_artifacts(candidates):
    import scripts.scheduler_driven_scalping_backtest as module
    from src.domain.regime.mapping import candidate_universe_hash
    from tests.application.usecases.regime.test_select_daily_strategy_usecase import _mapping

    hashes = {
        item.candidate_id: module._audited_candidate_hash(
            item, symbol=Symbol("BTC", "USDT"), initial_equity=Decimal("10000")
        )
        for item in candidates
    }
    mapping = _mapping()
    return hashes, replace(
        mapping,
        candidate_hashes=hashes,
        candidate_universe_hash=candidate_universe_hash(tuple(sorted(hashes))),
        candidate_assessments=tuple(
            replace(item, candidate_hash=hashes[item.candidate_id])
            for item in mapping.candidate_assessments
        ),
    )


def test_daily_regime_switch_exit_audit_binds_previous_candidate_hash(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module
    from src.domain.regime.model import ClusterAssignment
    from tests.application.usecases.regime.test_select_daily_strategy_usecase import (
        COMPONENTS,
        _FrozenModel,
        _candles,
    )

    class Directional:
        def __init__(self, direction):
            self.direction = direction

        def evaluate(self, context):
            return StrategyResult("directional", Signal(self.direction, Decimal("1")))

    monkeypatch.setattr(
        module,
        "build_strategies",
        lambda candidate: (
            Directional(
                SignalDirection.LONG
                if candidate.candidate_id == "candidate-a"
                else SignalDirection.SHORT
            ),
        ),
    )
    start = datetime(2026, 4, 6, tzinfo=timezone.utc)
    candidates = tuple(
        replace(
            _regime_candidate(candidate_id),
            take_profit_ratio=Decimal("0.8"),
            stop_loss_ratio=Decimal("0.9"),
        )
        for candidate_id in ("candidate-a", "candidate-b")
    )
    hashes, mapping = _daily_test_artifacts(candidates)
    base_model = _FrozenModel(ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0))

    class SwitchingModel:
        def __init__(self):
            self.calls = 0

        def __getattr__(self, name):
            return getattr(base_model, name)

        def assign(self, vector):
            component = COMPONENTS[0] if self.calls == 0 else COMPONENTS[3]
            self.calls += 1
            return ClusterAssignment(component, 0.9, 0.05, 1.0)

    result = run_scheduler_driven_daily_regime_backtest(
        MarketSnapshot(_candles(count=4320 + 1442, start=start - timedelta(days=3))),
        start_at=start,
        end_at=start + timedelta(days=1, minutes=2),
        candidates=candidates,
        model_artifact=SwitchingModel(),
        mapping_artifact=mapping,
        candidate_manifest=tuple(sorted(hashes.items())),
        position_exit_policy=PositionExitPolicy.ACTIVE_STRATEGY_OPPOSITE,
    )

    trade = next(
        item for item in result["trades"]
        if item["exit_reason"] == "active_strategy_opposite_signal"
    )
    audit = trade["exit_audit"]["payload"]
    assert audit["previous_candidate_id"] == "candidate-a"
    assert audit["previous_candidate_definition_hash"] == hashes["candidate-a"]
    assert audit["active_candidate_id"] == "candidate-b"
    assert audit["active_candidate_definition_hash"] == hashes["candidate-b"]
    assert result["exposure_candle_count"] == sum(
        item["holding_bars"] for item in result["trades"]
    )


def test_daily_regime_feature_unavailable_holds_are_canonical_and_hashed(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module
    from src.domain.regime.model import ClusterAssignment
    from tests.application.usecases.regime.test_select_daily_strategy_usecase import (
        COMPONENTS,
        _FrozenModel,
        _candles,
    )

    class EnterThenWait:
        def __init__(self):
            self.calls = 0

        def evaluate(self, context):
            self.calls += 1
            signal = (
                Signal(SignalDirection.LONG, Decimal("1"))
                if self.calls == 1
                else Signal.wait()
            )
            return StrategyResult("enter-then-wait", signal)

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (EnterThenWait(),))
    start = datetime(2026, 4, 6, tzinfo=timezone.utc)
    candidates = (
        _regime_candidate("candidate-a"),
        _regime_candidate("candidate-b"),
    )
    hashes, mapping = _daily_test_artifacts(candidates)

    def replay():
        return run_scheduler_driven_daily_regime_backtest(
            MarketSnapshot(_candles(count=4322, start=start - timedelta(days=3))),
            start_at=start,
            end_at=start + timedelta(minutes=2),
            candidates=candidates,
            model_artifact=_FrozenModel(
                ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)
            ),
            mapping_artifact=mapping,
            candidate_manifest=tuple(sorted(hashes.items())),
            market_feature_provider=EmptyMarketFeatureProvider(("z-source", "a-source")),
            position_exit_policy=PositionExitPolicy.ACTIVE_STRATEGY_OPPOSITE,
        )

    result = replay()
    holds = result["feature_unavailable_hold_audits"]
    assert len(holds) == 2
    assert [item["payload"]["candle_at"] for item in holds] == sorted(
        item["payload"]["candle_at"] for item in holds
    )
    assert all(
        item["payload"]["boundary_at"] == item["payload"]["candle_at"]
        for item in holds
    )
    assert all(item["audit_hash"] for item in holds)
    assert all(item["payload"]["unavailable_sources"] == ["a-source", "z-source"] for item in holds)
    assert replay() == result
    assert result["exposure_candle_count"] == 2
    assert result["eligible_replay_interval_count"] == 2
    assert result["exposure_ratio"] == "1"
    assert sum(item["holding_bars"] for item in result["trades"]) == 2


def test_daily_regime_no_trade_exposure_is_zero(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module
    from src.domain.regime.model import ClusterAssignment
    from tests.application.usecases.regime.test_select_daily_strategy_usecase import (
        COMPONENTS,
        _FrozenModel,
        _candles,
    )

    class AlwaysWait:
        def evaluate(self, context):
            return StrategyResult("wait", Signal.wait())

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysWait(),))
    start = datetime(2026, 4, 6, tzinfo=timezone.utc)
    candidates = (
        _regime_candidate("candidate-a"),
        _regime_candidate("candidate-b"),
    )
    hashes, mapping = _daily_test_artifacts(candidates)
    result = run_scheduler_driven_daily_regime_backtest(
        MarketSnapshot(_candles(count=4323, start=start - timedelta(days=3))),
        start_at=start,
        end_at=start + timedelta(minutes=3),
        candidates=candidates,
        model_artifact=_FrozenModel(
            ClusterAssignment(COMPONENTS[0], 0.9, 0.05, 1.0)
        ),
        mapping_artifact=mapping,
        candidate_manifest=tuple(sorted(hashes.items())),
        position_exit_policy=PositionExitPolicy.ENTRY_OWNER_ONLY,
    )

    assert result["trade_count"] == 0
    assert result["exposure_candle_count"] == 0
    assert result["eligible_replay_interval_count"] == 3
    assert result["exposure_ratio"] == "0"


def _actual_artifact_pair(candidates):
    import scripts.scheduler_driven_scalping_backtest as module
    from tests.infrastructure.regime.test_json_regime_artifact_repository import (
        _canonical_hash,
        _mapping,
        _model,
    )

    model = replace(_model(), distance_thresholds=(100.0, 100.0, 100.0))
    mapping = _mapping(model)
    hashes = {
        candidate.candidate_id: module._audited_candidate_hash(
            candidate, symbol=Symbol("BTC", "USDT"), initial_equity=Decimal("10000")
        )
        for candidate in candidates
    }
    first_cluster = model.fingerprints[0]
    winner = mapping.candidate_assessments[first_cluster]["alpha"]
    winner_entry = mapping.entries[first_cluster]
    assessments = {}
    entries = {}
    for cluster, rows in mapping.candidate_assessments.items():
        assessments[cluster] = {
            "alpha": replace(
                winner, cluster_fingerprint=cluster, candidate_hash=hashes["alpha"]
            ),
            "beta": replace(rows["beta"], candidate_hash=hashes["beta"]),
        }
        entries[cluster] = replace(winner_entry, cluster_fingerprint=cluster)
    mapping = replace(
        mapping,
        candidate_hashes=hashes,
        candidate_universe_hash=_canonical_hash(
            {"candidate_ids": tuple(sorted(hashes))}
        ),
        candidate_definition_hash=_canonical_hash(
            {"candidate_hashes": dict(sorted(hashes.items()))}
        ),
        candidate_assessments=assessments,
        entries=entries,
    )
    return model, mapping


def test_regime_replay_confirms_cluster_before_switching_strategy(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    class AlwaysWait:
        def evaluate(self, context):
            return StrategyResult("wait", Signal.wait())

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysWait(),))
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    provider = _ScriptedAssignments({
        start: "cluster-a",
        start + timedelta(hours=4): "cluster-b",
        start + timedelta(hours=8): "cluster-b",
    })
    result = run_scheduler_driven_regime_backtest(
        _regime_market(start), start_at=start, end_at=start + timedelta(hours=9),
        candidates=(_regime_candidate("strategy-x"), _regime_candidate("strategy-y")),
        model=provider,
        mapping=_selection_snapshot({"cluster-a": "strategy-x", "cluster-b": "strategy-y"}),
    )

    assert [row["type"] for row in result["selection_events"]] == [
        "classification", "classification", "cluster_transition", "strategy_transition"
    ]
    assert result["selection_events"][1]["active_strategy_profile_id"] == "strategy-x"
    assert result["selection_events"][-1]["active_strategy_profile_id"] == "strategy-y"
    assert provider.calls == [start, start + timedelta(hours=4), start + timedelta(hours=8)]
    assert result["signal_discontinuity_count"] == 1
    assert result["signal_discontinuity_definition"] == "active_signal_generator_identity_changes_v1"


def test_regime_replay_cash_blocks_entries_but_owner_position_still_exits(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    class AlwaysLong:
        def evaluate(self, context):
            return StrategyResult("long", Signal(SignalDirection.LONG, Decimal("1")))

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysLong(),))
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    result = run_scheduler_driven_regime_backtest(
        _regime_market(start, profit_at=start + timedelta(hours=8)),
        start_at=start, end_at=start + timedelta(hours=9),
        candidates=(_regime_candidate(),),
        assignment_provider=_ScriptedAssignments({
            start: "cluster-a", start + timedelta(hours=4): "cluster-b",
            start + timedelta(hours=8): "cluster-b",
        }),
        artifact_snapshot=_selection_snapshot({"cluster-a": "strategy-x", "cluster-b": None}),
    )

    assert result["entries_while_cash"] == 0
    assert result["trade_count"] == 1
    assert result["trades"][0]["entry_at"] == start.isoformat()
    assert result["trades"][0]["exit_reason"] == "take_profit"
    assert result["trades"][0]["owner_strategy_profile_id"] == "strategy-x"
    assert result["transition_counts"]["cash"] == 1
    assert result["signal_discontinuity_count"] == 1


def test_regime_replay_same_strategy_cluster_transition_reuses_bundle(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    class AlwaysWait:
        def evaluate(self, context):
            return StrategyResult("wait", Signal.wait())

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysWait(),))
    original = module._build_regime_bundle
    builds = []
    monkeypatch.setattr(
        module, "_build_regime_bundle",
        lambda candidate, **kwargs: builds.append(candidate.candidate_id) or original(candidate, **kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    result = run_scheduler_driven_regime_backtest(
        _regime_market(start), start_at=start, end_at=start + timedelta(hours=9),
        candidates=(_regime_candidate(),),
        assignment_provider=_ScriptedAssignments({
            start: "cluster-a", start + timedelta(hours=4): "cluster-b",
            start + timedelta(hours=8): "cluster-b",
        }),
        artifact_snapshot=_selection_snapshot({"cluster-a": "strategy-x", "cluster-b": "strategy-x"}),
    )

    assert builds == ["strategy-x"]
    assert result["transition_counts"]["cluster"] == 1
    assert result["transition_counts"]["strategy"] == 0
    assert result["signal_discontinuity_count"] == 0


def test_regime_replay_requires_start_on_four_hour_boundary() -> None:
    start = datetime(2026, 1, 5, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="four-hour"):
        run_scheduler_driven_regime_backtest(
            _regime_market(start), start_at=start, end_at=start + timedelta(hours=1),
            candidates=(_regime_candidate(),),
            model=_ScriptedAssignments({}),
            mapping=_selection_snapshot({"cluster-a": "strategy-x"}),
        )


@pytest.mark.parametrize("terminal_kind", ("take_profit", "losing_force_close"))
def test_regime_replay_terminal_equity_and_drawdown_include_end_candle(
    monkeypatch, terminal_kind
) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    class AlwaysLong:
        def evaluate(self, context):
            return StrategyResult("long", Signal(SignalDirection.LONG, Decimal("1")))

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysLong(),))
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    end = start + timedelta(hours=1)
    market = _regime_market(
        start,
        hours=1,
        profit_at=end - timedelta(minutes=1) if terminal_kind == "take_profit" else None,
        close_at=Decimal("90") if terminal_kind == "losing_force_close" else None,
    )
    result = run_scheduler_driven_regime_backtest(
        market, start_at=start, end_at=end, candidates=(_regime_candidate(),),
        model=_ScriptedAssignments({start: "cluster-a"}),
        mapping=_selection_snapshot({"cluster-a": "strategy-x"}),
    )

    assert _validation_replay_metrics(result) == (
        Decimal(result["return_ratio"]),
        Decimal(result["portfolio_max_drawdown_ratio"]),
        Decimal(result["actual_turnover_notional"]),
    )

    assert result["trades"][0]["exit_reason"] == (
        "take_profit" if terminal_kind == "take_profit" else "end_of_data"
    )
    assert result["equity_curve"][-1] == {
        "timestamp": end.isoformat(), "equity": result["final_equity"]
    }
    assert sum(row["timestamp"] == end.isoformat() for row in result["equity_curve"]) == 1
    if terminal_kind == "losing_force_close":
        assert Decimal(result["portfolio_max_drawdown_ratio"]) > 0


def test_regime_replay_uses_provider_warmup_and_reports_provenance(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    class AlwaysWait:
        def evaluate(self, context):
            return StrategyResult("wait", Signal.wait())

    class Provider(EmptyMarketFeatureProvider):
        required_warmup_candles = 5
        feature_cache_hash = "cache-hash"
        feature_config_hash = "config-hash"
        feature_source_coverage = {"source": 10}
        feature_unavailable_counts = {"source": 0}
        feature_provenance = {"provider": "fixture"}

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysWait(),))
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    result = run_scheduler_driven_regime_backtest(
        _regime_market(start, hours=1, context_minutes=5),
        start_at=start, end_at=start + timedelta(hours=1),
        candidates=(_regime_candidate(),),
        model=_ScriptedAssignments({start: "cluster-a"}),
        mapping=_selection_snapshot({"cluster-a": "strategy-x"}),
        market_feature_provider=Provider(),
    )

    assert result["required_warmup_candles"] == 5
    assert result["feature_cache_hash"] == "cache-hash"
    assert result["feature_source_coverage"] == {"source": 10}
    assert result["feature_unavailable_counts"] == {"source": 0}
    assert result["feature_provenance"] == {"provider": "fixture"}
    assert len(result["feature_config_hash"]) == 64
    assert result["assignment_source"] == "scripted"


def test_regime_replay_actual_artifacts_extract_exact_prior_week_and_assign(
    monkeypatch,
) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    class AlwaysLong:
        def evaluate(self, context):
            return StrategyResult(
                "long", Signal(SignalDirection.LONG, Decimal("1"))
            )

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysLong(),))
    candidates = (_regime_candidate("alpha"), _regime_candidate("beta"))
    model, mapping = _actual_artifact_pair(candidates)
    start = datetime(2026, 7, 6, tzinfo=timezone.utc)
    extracted = []
    assigned = []
    original_extract = module.ChartFeatureExtractor.extract
    original_assign = module.SklearnRegimeModel.assign

    def spy_extract(self, candles, anchor_at):
        candles = tuple(candles)
        extracted.append((len(candles), candles[0].opened_at, candles[-1].closed_at, anchor_at))
        return original_extract(self, candles, anchor_at)

    def spy_assign(self, artifact, vectors):
        assigned.append((artifact, vectors))
        return original_assign(self, artifact, vectors)

    monkeypatch.setattr(module.ChartFeatureExtractor, "extract", spy_extract)
    monkeypatch.setattr(module.SklearnRegimeModel, "assign", spy_assign)
    result = run_scheduler_driven_regime_backtest(
        _regime_market(start, hours=5, context_minutes=7 * 24 * 60, vary=True),
        start_at=start, end_at=start + timedelta(hours=5), candidates=candidates,
        model=model, mapping=mapping,
    )

    assert extracted == [
        (10080, start - timedelta(days=7), start, start),
        (
            10080,
            start - timedelta(days=7) + timedelta(hours=4),
            start + timedelta(hours=4),
            start + timedelta(hours=4),
        ),
    ]
    assert len(assigned) == 2
    assert result["assignment_source"] == "artifact"
    assert result["selection_events"][0]["boundary_at"] == start.isoformat()
    assert result["candidate_definition_hashes"] == dict(mapping.candidate_hashes)
    assert result["trade_count"] == 1
    trade = result["trades"][0]
    assert trade["owner_candidate_definition_hash"] == result[
        "candidate_definition_hashes"
    ][trade["owner_strategy_profile_id"]]
    assert result["candidate_universe_hash"] == mapping.candidate_universe_hash
    assert result["candidate_definition_hash"] == mapping.candidate_definition_hash


def test_regime_replay_rejects_future_fitted_model() -> None:
    candidates = (_regime_candidate("alpha"), _regime_candidate("beta"))
    model, _ = _actual_artifact_pair(candidates)
    start = datetime(2026, 7, 6, tzinfo=timezone.utc)
    model = replace(model, training_end_at=start + timedelta(days=1))
    from tests.infrastructure.regime.test_json_regime_artifact_repository import _mapping
    mapping = _mapping(model)

    with pytest.raises(ValueError, match="training_end_at"):
        run_scheduler_driven_regime_backtest(
            _regime_market(start, hours=1), start_at=start,
            end_at=start + timedelta(hours=1), candidates=candidates,
            model=model, mapping=mapping,
        )


def test_regime_replay_rejects_mapping_episode_overlapping_start() -> None:
    from tests.infrastructure.regime.test_json_regime_artifact_repository import _mapping, _model

    start = datetime(2026, 1, 12, tzinfo=timezone.utc)
    model = _model()
    mapping = _mapping(model)
    candidates = (_regime_candidate("alpha"), _regime_candidate("beta"))

    with pytest.raises(ValueError, match="evidence episode"):
        run_scheduler_driven_regime_backtest(
            _regime_market(start, hours=1), start_at=start,
            end_at=start + timedelta(hours=1), candidates=candidates,
            model=model, mapping=mapping,
        )


def test_regime_replay_accepts_exact_model_mapping_purge_boundary() -> None:
    candidates = (_regime_candidate("alpha"), _regime_candidate("beta"))
    model, mapping = _actual_artifact_pair(candidates)
    assert min(
        start
        for rows in mapping.candidate_assessments.values()
        for assessment in rows.values()
        for start in assessment.effective_episode_starts
    ) == model.training_end_at + timedelta(days=7)


def test_regime_replay_rejects_mapping_one_minute_short_of_purge() -> None:
    from tests.infrastructure.regime.test_json_regime_artifact_repository import _mapping, _model

    start = datetime(2026, 7, 6, tzinfo=timezone.utc)
    model = replace(
        _model(), training_end_at=datetime(2025, 12, 29, 0, 1, tzinfo=timezone.utc)
    )
    mapping = _mapping(model)
    candidates = (_regime_candidate("alpha"), _regime_candidate("beta"))

    with pytest.raises(ValueError, match="purge interval"):
        run_scheduler_driven_regime_backtest(
            _regime_market(start, hours=1), start_at=start,
            end_at=start + timedelta(hours=1), candidates=candidates,
            model=model, mapping=mapping,
        )


def test_regime_replay_rejects_model_symbol_before_replay_work() -> None:
    from tests.infrastructure.regime.test_json_regime_artifact_repository import _mapping, _model

    start = datetime(2026, 7, 6, tzinfo=timezone.utc)
    model = replace(_model(), symbol="ETHUSDT")
    mapping = _mapping(model)
    with pytest.raises(ValueError, match="model symbol"):
        run_scheduler_driven_regime_backtest(
            _regime_market(start, hours=1), start_at=start,
            end_at=start + timedelta(hours=1),
            candidates=(_regime_candidate("alpha"), _regime_candidate("beta")),
            model=model, mapping=mapping,
        )


def test_regime_replay_rejects_candidate_hash_mismatch() -> None:
    candidates = (_regime_candidate("alpha"), _regime_candidate("beta"))
    model, mapping = _actual_artifact_pair(candidates)
    changed = replace(candidates[0], take_profit_ratio=Decimal("0.02"))
    start = datetime(2026, 7, 6, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="candidate definition hash"):
        run_scheduler_driven_regime_backtest(
            _regime_market(start, hours=1), start_at=start,
            end_at=start + timedelta(hours=1), candidates=(changed, candidates[1]),
            model=model, mapping=mapping,
        )


def test_regime_replay_candidate_audit_hash_fields_match_across_modes(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    class AlwaysWait:
        def evaluate(self, context):
            return StrategyResult("wait", Signal.wait())

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysWait(),))
    candidates = (_regime_candidate("alpha"), _regime_candidate("beta"))
    _, mapping = _actual_artifact_pair(candidates)
    start = datetime(2026, 7, 6, tzinfo=timezone.utc)
    scripted = run_scheduler_driven_regime_backtest(
        _regime_market(start, hours=1), start_at=start,
        end_at=start + timedelta(hours=1), candidates=candidates,
        model=_ScriptedAssignments({start: "cluster"}),
        mapping=_selection_snapshot({"cluster": "alpha"}),
    )

    assert scripted["candidate_definition_hashes"] == dict(mapping.candidate_hashes)
    assert scripted["candidate_universe_hash"] == mapping.candidate_universe_hash
    assert scripted["candidate_definition_hash"] == mapping.candidate_definition_hash


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
    # The candle closing exactly at end_at is terminal management context, not an entry decision.
    assert result["signal_count"] == 38
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


def test_scheduler_backtest_default_payload_has_frozen_json_schema() -> None:
    market = _flat_market()
    result = run_scheduler_driven_backtest(
        market,
        start_at=market.opened_at,
        end_at=market.closed_at,
        include_deferred=True,
    )

    assert tuple(result) == (
        "engine",
        "engine_version",
        "candidate_id",
        "symbol",
        "scheduler_path",
        "cost_model",
        "start_at",
        "end_at",
        "trade_count",
        "trades_per_day",
        "daily_return_ratio",
        "net_win_rate",
        "return_ratio",
        "gross_pnl",
        "net_pnl",
        "fee_paid",
        "max_drawdown_ratio",
        "maximum_adverse_excursion_ratio",
        "average_net_trade_roe",
        "average_net_trade_expectancy_ratio",
        "signal_count",
        "skipped_by_guard",
        "candidate",
        "candidate_definition_hash",
        "feature_cache_hash",
        "feature_source_coverage",
        "feature_unavailable_counts",
        "feature_provenance",
        "feature_cache_schema_version",
        "future_feature_access_count",
    )
    assert {key: type(value) for key, value in result.items()} == {
        "engine": str, "engine_version": str, "candidate_id": str, "symbol": str, "scheduler_path": str,
        "cost_model": dict, "start_at": str, "end_at": str, "trade_count": int,
        "trades_per_day": str, "daily_return_ratio": str, "net_win_rate": str,
            "return_ratio": str, "gross_pnl": str, "net_pnl": str, "fee_paid": str,
            "max_drawdown_ratio": str, "maximum_adverse_excursion_ratio": str,
            "average_net_trade_roe": str,
        "average_net_trade_expectancy_ratio": str, "signal_count": int,
        "skipped_by_guard": int, "candidate": dict, "candidate_definition_hash": str,
        "feature_cache_hash": type(None), "feature_source_coverage": dict,
            "feature_unavailable_counts": dict, "feature_provenance": dict,
            "feature_cache_schema_version": str,
        "future_feature_access_count": int,
    }
    assert isinstance(json.dumps(result, sort_keys=True), str)
    assert not ({"trades", "initial_equity", "final_equity", "feature_config_hash"} & result.keys())


def test_scheduler_context_warmup_can_make_first_episode_decision_eligible(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    evaluated = []

    class AlwaysLong:
        def evaluate(self, context):
            evaluated.append(context.market.latest_candle.closed_at)
            return StrategyResult("always-long", Signal(SignalDirection.LONG, Decimal("1")))

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (AlwaysLong(),))
    candles = tuple(
        Candle(
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            opened_at=start + timedelta(minutes=index),
            closed_at=start + timedelta(minutes=index + 1),
            open_price=Decimal("100"), high_price=Decimal("100"),
            low_price=Decimal("100"), close_price=Decimal("100"), volume=Decimal("1"),
        )
        for index in range(-3, 2)
    )
    candidate = SchedulerBacktestCandidate(
        candidate_id="context-candidate",
        strategies=(StrategyCandidateSpec("unused", {}),),
        take_profit_ratio=Decimal("0.5"), stop_loss_ratio=Decimal("0.5"),
        equity_ratio=Decimal("0.1"), leverage=Decimal("2"), candle_limit=3,
    )
    result = run_scheduler_driven_backtest(
        MarketSnapshot(candles),
        context_start_at=start - timedelta(minutes=3),
        start_at=start,
        end_at=start + timedelta(minutes=2),
        candidate=candidate,
        include_trade_details=True,
    )

    assert evaluated[0] == start
    assert result["trades"][0]["entry_at"] == start.isoformat()
    assert all(when >= start for when in evaluated)


def test_scheduler_does_not_open_a_new_position_on_terminal_candle(monkeypatch) -> None:
    import scripts.scheduler_driven_scalping_backtest as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    end = start + timedelta(minutes=2)
    evaluated = []

    class TerminalLong:
        def evaluate(self, context):
            closed_at = context.market.latest_candle.closed_at
            evaluated.append(closed_at)
            signal = Signal(SignalDirection.LONG, Decimal("1")) if closed_at == end else Signal.wait()
            return StrategyResult("terminal-long", signal)

    monkeypatch.setattr(module, "build_strategies", lambda candidate: (TerminalLong(),))
    candles = tuple(
        Candle(
            symbol=Symbol("BTC", "USDT"), timeframe=Timeframe(1, "m"),
            opened_at=start + timedelta(minutes=index),
            closed_at=start + timedelta(minutes=index + 1),
            open_price=Decimal("100"), high_price=Decimal("100"),
            low_price=Decimal("100"), close_price=Decimal("100"), volume=Decimal("1"),
        )
        for index in range(2)
    )
    candidate = SchedulerBacktestCandidate(
        candidate_id="terminal-candidate",
        strategies=(StrategyCandidateSpec("unused", {}),),
        take_profit_ratio=Decimal("0.1"), stop_loss_ratio=Decimal("0.1"),
        equity_ratio=Decimal("0.1"), leverage=Decimal("2"), candle_limit=1,
    )

    result = run_scheduler_driven_backtest(
        MarketSnapshot(candles), start_at=start, end_at=end,
        candidate=candidate, include_trade_details=True,
    )

    assert evaluated == [start + timedelta(minutes=1)]
    assert result["trade_count"] == 0
    assert result["trades"] == []


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
    assert forced["maximum_adverse_excursion_ratio"] == forced["trades"][-1]["maximum_adverse_excursion_ratio"]
    assert Decimal(forced["gross_pnl"]) - Decimal(forced["fee_paid"]) == Decimal(forced["net_pnl"])
    assert left_open["trade_count"] == 0
    assert left_open["trades"] == []
    assert left_open["net_pnl"] == "0"
    assert left_open["position_open_at_end"] is True
    assert forced["position_open_at_end"] is False
    assert Decimal(forced["max_drawdown_ratio"]) > 0
    assert Decimal(forced["max_drawdown_ratio"]) == (
        -Decimal(forced["net_pnl"]) / Decimal(forced["initial_equity"])
    )
    assert Decimal(forced["final_equity"]) == (
        Decimal(forced["initial_equity"]) + Decimal(forced["net_pnl"])
    )
    assert forced["feature_cache_hash"] is None
    assert forced["feature_config_hash"] is None


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
        include_trade_details=True,
    )

    assert captured == [provider, provider]
    assert result["feature_cache_hash"] == "a" * 64
    assert result["feature_source_coverage"] == {"aggTrades": 10}
    assert result["feature_unavailable_counts"] == {"fundingRate": 3}
    assert result["feature_provenance"] == {"venue": "binance"}
    assert len(result["feature_config_hash"]) == 64
    assert result["initial_equity"] == "10000"
    assert result["final_equity"] == "10000"
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
