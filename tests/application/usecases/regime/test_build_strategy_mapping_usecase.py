from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.application.usecases.regime.build_strategy_mapping_usecase import (
    BuildStrategyMappingCommand,
    BuildStrategyMappingUseCase,
    corrected_lower_bound,
)


UTC = timezone.utc


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
                    "candidate_hash": f"hash-{candidate_id}",
                    "market_context_hash": f"market-{index}",
                    "data_hash": f"data-{index}",
                    "feature_config_hash": "feature-config",
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


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda rows: rows.append(dict(rows[0])), "duplicate"),
        (lambda rows: rows.pop(), "rectangular"),
        (lambda rows: rows[0].__setitem__("episode_end_at", "2026-01-13T00:00:00+00:00"), "seven days"),
        (lambda rows: rows[0].__setitem__("data_hash", "mismatch"), "data hash"),
    ],
)
def test_malformed_or_nonrectangular_evidence_is_rejected(mutation, message: str) -> None:
    rows = _rows({"a": [".01"] * 8, "b": [".02"] * 8}, trades_per_week=4)
    mutation(rows)
    with pytest.raises(ValueError, match=message):
        _build(rows)
