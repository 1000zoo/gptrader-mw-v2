from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.application.usecases.regime.build_strategy_mapping_usecase import (
    BuildStrategyMappingCommand,
    BuildStrategyMappingUseCase,
    corrected_lower_bound,
)
from src.domain.regime.mapping import WeeklyStrategyEvidence


UTC = timezone.utc


def _sha(label: str) -> str:
    import hashlib
    return hashlib.sha256(label.encode()).hexdigest()


def _rows(
    returns_by_candidate: dict[str, list[str]],
    *,
    trades_per_week: int = 4,
    cluster: str = "cluster-a",
    start: datetime = datetime(2026, 1, 5, tzinfo=UTC),
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for candidate_id, values in returns_by_candidate.items():
        for index, text in enumerate(values):
            episode_start = start + timedelta(days=7 * index)
            value = Decimal(text)
            initial = Decimal("10000")
            net = initial * value
            trade_values = [net / trades_per_week] * trades_per_week if trades_per_week else []
            rows.append(
                {
                    "cluster_fingerprint": cluster,
                    "candidate_id": candidate_id,
                    "episode_start_at": episode_start.isoformat(),
                    "episode_end_at": (episode_start + timedelta(days=7)).isoformat(),
                    "initial_equity": str(initial),
                    "final_equity": str(initial + net),
                    "net_pnl": str(net),
                    "return_ratio": str(value),
                    "trade_count": trades_per_week,
                    "trades": [
                        {"net_pnl": str(pnl), "holding_bars": 10}
                        for pnl in trade_values
                    ],
                    "candidate_hash": _sha(f"candidate-{candidate_id}"),
                    "market_context_hash": _sha(f"market-{index}"),
                    "data_hash": _sha(f"data-{index}"),
                    "feature_cache_hash": _sha(f"cache-{index}"),
                    "feature_provenance": {"source": "test"},
                    "feature_config_hash": _sha("feature-config"),
                }
            )
    return rows


def _build(rows: list[dict[str, object]], **overrides: object):
    command = BuildStrategyMappingCommand(
        evidence_rows=tuple(rows),
        regime_model_artifact_hash="model-artifact-hash",
        regime_model_fingerprint_hash="model-fingerprint-hash",
        random_seed=20260714,
        bootstrap_resamples=200,
        **overrides,
    )
    return BuildStrategyMappingUseCase().execute(command).artifact


def test_cluster_maps_to_cash_when_no_candidate_has_positive_corrected_lcb() -> None:
    artifact = _build(_rows({"bad": ["-0.01"] * 12}, trades_per_week=3))
    entry = artifact.entries["cluster-a"]
    assert entry.strategy_profile_id is None
    assert entry.decision == "cash"
    assert "non_positive_corrected_lower_bound" in entry.rejection_reasons


def test_candidate_with_fewer_than_thirty_closed_trades_is_ineligible() -> None:
    rows = _rows({"positive": ["0.01"] * 8}, trades_per_week=4)
    rows[-1]["trade_count"] = 1
    rows[-1]["trades"] = [{"net_pnl": rows[-1]["net_pnl"], "holding_bars": 10}]
    artifact = _build(rows)
    entry = artifact.entries["cluster-a"]
    assert entry.decision == "cash"
    assert "minimum_trade_count" in entry.rejection_reasons


def test_fourteen_day_moving_block_bootstrap_is_deterministic() -> None:
    values = tuple(Decimal(value) for value in (".01", ".02", "-.01", ".03", ".01"))
    first = corrected_lower_bound(values, random_seed=20260714, resamples=2000)
    second = corrected_lower_bound(values, random_seed=20260714, resamples=2000)
    assert first == second


def test_eligibility_accumulates_reasons_in_stable_order() -> None:
    artifact = _build(_rows({"bad": ["-0.01"] * 7}, trades_per_week=1))
    assessment = artifact.candidate_assessments["cluster-a"]["bad"]
    assert assessment.rejection_reasons == (
        "minimum_weekly_episodes",
        "minimum_distinct_months",
        "minimum_trade_count",
        "non_positive_corrected_lower_bound",
        "cash_dominance",
    )


def test_metrics_use_documented_conservative_rules() -> None:
    values = ["-.02", ".01", ".02", ".03", ".04", ".05", ".06", ".07", ".08"]
    artifact = _build(_rows({"winner": values}, trades_per_week=4))
    metrics = artifact.candidate_assessments["cluster-a"]["winner"].metrics
    assert metrics["mean_weekly_return"] == sum(map(Decimal, values)) / Decimal(9)
    assert metrics["median_weekly_return"] == Decimal(".04")
    assert metrics["conservative_10th_percentile"] == Decimal("-.02")
    assert metrics["worst_14_day_block_return"] == Decimal("-.0102")
    assert metrics["expected_shortfall"] == Decimal("-.02")
    assert metrics["time_in_market"] == Decimal(360) / Decimal(10080 * 9)
    assert metrics["profit_factor"] == Decimal("18")
    assert metrics["top_5_trade_pnl_share"] == Decimal(13) / Decimal(48)
    assert metrics["top_1_episode_pnl_share"] == Decimal(2) / Decimal(9)
    assert metrics["exposure_adjusted_return"] == metrics["mean_weekly_return"] / metrics["time_in_market"]
    assert metrics["return_without_best_episode"] == sum(map(Decimal, values[:-1])) / Decimal(8)


def test_exact_minimum_episode_month_and_trade_boundaries_are_eligible() -> None:
    rows = _rows(
        {"boundary": [".01"] * 8},
        trades_per_week=4,
        start=datetime(2026, 1, 26, tzinfo=UTC),
    )
    artifact = _build(rows)
    assessment = artifact.candidate_assessments["cluster-a"]["boundary"]
    assert assessment.weekly_episode_count == 8
    assert assessment.distinct_month_count == 3
    assert assessment.closed_trade_count == 32
    assert assessment.eligible
    assert artifact.entries["cluster-a"].decision == "strategy"


def test_command_hash_expectations_reject_silent_merges() -> None:
    rows = _rows({"candidate": [".01"] * 8}, trades_per_week=4)
    for field, message in (
        ("candidate_definition_hash", "candidate definition hash"),
        ("candidate_universe_hash", "candidate universe hash"),
        ("data_provenance_hash", "data provenance hash"),
    ):
        with pytest.raises(ValueError, match=message):
            _build(rows, **{field: "wrong"})


def test_winner_uses_lcb_then_median_mean_and_candidate_id(monkeypatch) -> None:
    import src.application.usecases.regime.build_strategy_mapping_usecase as module

    monkeypatch.setattr(module, "_family_corrected_lower_bounds", lambda *a, **k: {"a": Decimal(".01"), "b": Decimal(".01")})
    artifact = _build(_rows({"b": [".02"] * 12, "a": [".02"] * 12}, trades_per_week=3))
    assert artifact.entries["cluster-a"].strategy_profile_id == "a"


def test_noisy_extra_candidate_cannot_improve_existing_corrected_lcb() -> None:
    base = _build(_rows({"steady": [".02", ".01"] * 6}, trades_per_week=3))
    family = _build(_rows({"steady": [".02", ".01"] * 6, "noisy": [".2", "-.2"] * 6}, trades_per_week=3))
    assert family.candidate_assessments["cluster-a"]["steady"].corrected_lower_bound <= base.candidate_assessments["cluster-a"]["steady"].corrected_lower_bound


def test_input_order_does_not_change_artifact() -> None:
    rows = _rows({"a": [".01"] * 12, "b": [".02"] * 12}, trades_per_week=3)
    assert _build(rows) == _build(list(reversed(rows)))


def test_globally_consecutive_weeks_may_be_assigned_to_alternating_clusters() -> None:
    rows = _rows({"candidate": [".01"] * 4}, trades_per_week=4)
    for index, row in enumerate(rows):
        row["cluster_fingerprint"] = f"cluster-{index % 2}"
    artifact = _build(rows)
    assert set(artifact.entries) == {"cluster-0", "cluster-1"}
    assert all(entry.decision == "cash" for entry in artifact.entries.values())
    assert all(
        "insufficient_consecutive_blocks" in entry.rejection_reasons
        for entry in artifact.entries.values()
    )


def test_multi_run_calendar_blocks_are_deterministic_without_gap_spanning() -> None:
    rows = _rows({"candidate": [".01", ".02", "-.9", ".03", ".04"]}, trades_per_week=5)
    # The middle week belongs to another cluster. cluster-a has two genuine runs:
    # Jan 5/12 and Jan 26/Feb 2. Jan 12/Jan 26 must never form a 14-day block.
    for index, row in enumerate(rows):
        row["cluster_fingerprint"] = "cluster-b" if index == 2 else "cluster-a"
    # Give cluster-b a second true adjacent observation so the mapping can audit both.
    extra = _rows({"candidate": ["-.8"]}, trades_per_week=5, start=datetime(2026, 2, 9, tzinfo=UTC))[0]
    extra["cluster_fingerprint"] = "cluster-b"
    rows.append(extra)
    first = _build(rows)
    second = _build(list(reversed(rows)))
    a = first.candidate_assessments["cluster-a"]["candidate"]
    assert first == second
    assert a.metrics["worst_14_day_block_return"] == Decimal(".0302")
    assert "insufficient_consecutive_blocks" not in a.rejection_reasons


def test_prebuilt_weekly_evidence_is_revalidated_on_execute() -> None:
    parsed = WeeklyStrategyEvidence.from_row(_rows({"candidate": [".01"] * 2})[0])
    object.__setattr__(parsed, "data_hash", "forged")
    with pytest.raises(ValueError, match="data_hash"):
        _build([parsed])


def test_artifact_rejects_forged_strategy_statistics_and_nonfinite_metric_policy() -> None:
    artifact = _build(_rows({"candidate": [".01"] * 8, "other": [".005"] * 8}, trades_per_week=4, start=datetime(2026, 1, 26, tzinfo=UTC)))
    cluster = "cluster-a"
    entry = artifact.entries[cluster]
    with pytest.raises(ValueError, match="strategy entry"):
        replace(artifact, entries={cluster: replace(entry, closed_trade_count=entry.closed_trade_count + 1)})
    metrics = dict(entry.metrics)
    metrics["mean_weekly_return"] = Decimal("Infinity")
    with pytest.raises(ValueError, match="must be finite"):
        replace(entry, metrics=metrics)
    metrics = dict(entry.metrics)
    metrics["profit_factor"] = Decimal("Infinity")
    assert replace(entry, metrics=metrics).metrics["profit_factor"] == Decimal("Infinity")
    metrics["profit_factor"] = Decimal("NaN")
    with pytest.raises(ValueError, match="non-NaN"):
        replace(entry, metrics=metrics)


def test_artifact_rejects_forged_cash_statistics_and_candidate_universe() -> None:
    rows = _rows({"candidate": ["-.01"] * 4, "other": ["-.02"] * 4}, trades_per_week=4)
    artifact = _build(rows)
    cluster = "cluster-a"
    cash = artifact.entries[cluster]
    with pytest.raises(ValueError, match="cash entry"):
        replace(artifact, entries={cluster: replace(cash, closed_trade_count=1)})
    with pytest.raises(ValueError, match="candidate universe"):
        replace(artifact, candidate_assessments={cluster: {"candidate": artifact.candidate_assessments[cluster]["candidate"]}})


def test_direct_evidence_construction_enforces_interval_and_feature_identity() -> None:
    parsed = WeeklyStrategyEvidence.from_row(_rows({"candidate": [".01"]})[0])
    with pytest.raises(ValueError, match="Monday"):
        replace(parsed, episode_start_at=parsed.episode_start_at + timedelta(days=1))
    with pytest.raises(ValueError, match="all-null or all-present"):
        replace(parsed, feature_cache_hash=None)
    source = {"nested": {"items": [1, 2]}}
    copied = replace(parsed, feature_provenance=source)
    source["nested"]["items"].append(3)
    assert tuple(copied.feature_provenance["nested"]["items"]) == (1, 2)


def test_same_candidate_episode_cannot_be_silently_assigned_to_two_clusters() -> None:
    rows = _rows({"candidate": [".01"] * 2})
    duplicate = dict(rows[0])
    duplicate["cluster_fingerprint"] = "cluster-b"
    with pytest.raises(ValueError, match="conflicting clusters"):
        _build(rows + [duplicate])


def test_task5_no_provider_rows_are_consumed_with_null_feature_identity(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as task5
    from scripts.scheduler_driven_scalping_backtest import SchedulerBacktestCandidate, StrategyCandidateSpec
    from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
    from src.domain.regime import build_weekly_episodes

    start = datetime(2026, 1, 5, tzinfo=UTC)
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    market = MarketSnapshot(tuple(
        Candle(symbol, timeframe, start + timedelta(minutes=i), start + timedelta(minutes=i + 1), Decimal(100), Decimal(100), Decimal(100), Decimal(100), Decimal(1))
        for i in range(-1, 2 * 10080)
    ))
    candidate = SchedulerBacktestCandidate(
        candidate_id="candidate", strategies=(StrategyCandidateSpec("latest-close-moving-average", {}),),
        take_profit_ratio=Decimal(".01"), stop_loss_ratio=Decimal(".01"),
        equity_ratio=Decimal(".1"), leverage=Decimal(1), candle_limit=1,
    )
    def fake_backtest(snapshot, **kwargs):
        initial = kwargs["initial_equity"]
        return {
            "candidate_id": "candidate", "initial_equity": str(initial), "final_equity": str(initial),
            "trade_count": 0, "trades_per_day": "0", "gross_pnl": "0", "net_pnl": "0",
            "fee_paid": "0", "return_ratio": "0", "daily_return_ratio": "0", "max_drawdown_ratio": "0",
            "net_win_rate": "0", "average_net_trade_roe": "0", "average_net_trade_expectancy_ratio": "0",
            "trades": [], "feature_cache_hash": None, "feature_provenance": {}, "feature_config_hash": None,
        }
    monkeypatch.setattr(task5, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=14)))
    rows = task5.run_mapping_episodes(market, episodes=episodes, assignments={e.anchor_at: "cluster-a" for e in episodes}, candidates=(candidate,))
    artifact = _build(rows)
    assert artifact.entries["cluster-a"].decision == "cash"
    assert artifact.data_provenance_hash


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda rows: rows.append(dict(rows[0])), "duplicate"),
        (lambda rows: rows.pop(), "rectangular"),
        (lambda rows: rows[0].__setitem__("episode_end_at", "2026-01-13T00:00:00+00:00"), "seven days"),
        (lambda rows: rows[0].__setitem__("data_hash", "mismatch"), "data[_ ]hash"),
    ],
)
def test_malformed_or_nonrectangular_evidence_is_rejected(mutation, message: str) -> None:
    rows = _rows({"a": [".01"] * 8, "b": [".02"] * 8}, trades_per_week=4)
    mutation(rows)
    with pytest.raises(ValueError, match=message):
        _build(rows)
