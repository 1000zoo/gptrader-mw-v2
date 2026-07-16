from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext, localcontext
import hashlib
import json
import math

import numpy as np
import pytest

import src.application.usecases.regime.build_daily_strategy_mapping_usecase as module
from src.application.usecases.regime.build_daily_strategy_mapping_usecase import (
    BuildDailyStrategyMappingCommand,
    BuildDailyStrategyMappingUseCase,
    _aligned_component_corrected_lower_bounds,
    _circular_moving_block_indices,
    _winner_order_key,
    compounded_return_without_best_episode,
    expected_shortfall_10,
    maximum_drawdown,
    positive_profit_concentration_shares,
    rejection_reasons,
    worst_seven_calendar_day_return,
)
from src.domain.regime import (
    DailyCandidateAssessment,
    DailyStrategyEvidence,
    daily_mapping_artifact_hash,
)
from src.domain.regime.mapping import candidate_universe_hash
from src.domain.regime.three_day_daily_profile import ThreeDayDailyWalkForwardFold


ZERO = Decimal("0")
MODEL_HASH = hashlib.sha256(b"model").hexdigest()
DATA_HASH = hashlib.sha256(b"data").hexdigest()
COST_HASH = hashlib.sha256(b"cost").hexdigest()
ENGINE_HASH = hashlib.sha256(b"engine").hexdigest()
COMPONENTS = tuple(f"component-{index}" for index in range(4))


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def mapping_calendar() -> tuple[datetime, ...]:
    fold = ThreeDayDailyWalkForwardFold.default()
    count = (fold.mapping_fit.end_at - fold.mapping_fit.start_at).days
    return tuple(fold.mapping_fit.start_at + timedelta(days=index) for index in range(count))


def evidence(
    *,
    day: datetime,
    component: str,
    candidate: str,
    candidate_hash: str,
    daily_return: Decimal = Decimal("0.001"),
    available: bool = True,
    trades: tuple[Decimal, ...] | None = None,
) -> DailyStrategyEvidence:
    initial = Decimal("100")
    net_pnl = initial * daily_return if available else ZERO
    if trades is None:
        trades = (net_pnl,) if available else None
    return DailyStrategyEvidence(
        component_fingerprint=component,
        candidate_id=candidate,
        cluster_anchor_at=day,
        feature_start_at=day - timedelta(days=3),
        feature_end_at=day,
        outcome_start_at=day,
        outcome_end_at=day + timedelta(days=1),
        initial_equity=initial,
        final_equity=initial + net_pnl,
        gross_pnl=net_pnl,
        net_pnl=net_pnl,
        gross_return_ratio=daily_return if available else ZERO,
        net_return_ratio=daily_return if available else ZERO,
        fees=ZERO,
        closed_trade_count=len(trades) if trades is not None else 0,
        exposure_ratio=Decimal("0.5") if available else ZERO,
        turnover_ratio=Decimal("0.1") if available else ZERO,
        maximum_drawdown_ratio=ZERO,
        maximum_adverse_excursion_ratio=ZERO,
        profit_factor=Decimal("1") if available else ZERO,
        downside_deviation_ratio=ZERO,
        expected_shortfall_10_ratio=daily_return if available else ZERO,
        median_daily_return_ratio=daily_return if available else ZERO,
        tenth_percentile_daily_return_ratio=daily_return if available else ZERO,
        worst_seven_day_return_ratio=daily_return if available else ZERO,
        return_without_best_episode_ratio=daily_return if available else ZERO,
        top_episode_profit_share=Decimal("0.1") if available else ZERO,
        top_five_trade_profit_share=Decimal("0.1") if available else ZERO,
        availability_status="available" if available else "unavailable",
        availability_reason=None if available else "feature_unavailable",
        candidate_hash=candidate_hash,
        model_artifact_hash=MODEL_HASH,
        data_hash=DATA_HASH,
        cost_config_hash=COST_HASH,
        engine_config_hash=ENGINE_HASH,
        trade_pnls=trades,
    )


def assessment(candidate_id: str = "candidate-a", **changes) -> DailyCandidateAssessment:
    fields = {
        "component_fingerprint": COMPONENTS[0],
        "candidate_id": candidate_id,
        "candidate_hash": sha(candidate_id),
        "assigned_day_count": 30,
        "episode_count": 30,
        "unavailable_day_count": 0,
        "unavailable_reason_counts": (),
        "calendar_month_count": 3,
        "closed_trade_count": 30,
        "mean_daily_return_ratio": Decimal("0.002"),
        "median_daily_return_ratio": Decimal("0.001"),
        "corrected_lower_bound_ratio": Decimal("0.0005"),
        "worst_seven_day_return_ratio": Decimal("-0.02"),
        "expected_shortfall_10_ratio": Decimal("-0.005"),
        "maximum_drawdown_ratio": Decimal("0.05"),
        "return_without_best_episode_ratio": Decimal("0.03"),
        "top_episode_profit_share": Decimal("0.20"),
        "top_five_trade_profit_share": Decimal("0.40"),
        "eligible": True,
        "rejection_reasons": (),
    }
    fields.update(changes)
    return DailyCandidateAssessment(**fields)


def valid_gate_values() -> dict[str, object]:
    return {
        "episode_count": 30,
        "calendar_month_count": 3,
        "closed_trade_count": 30,
        "net_compounded_return": Decimal("0.04"),
        "corrected_lower_bound": Decimal("0.001"),
        "worst_seven_day_return": Decimal("-0.02"),
        "expected_shortfall": Decimal("-0.005"),
        "drawdown": Decimal("0.08"),
        "return_without_best": Decimal("0.01"),
        "top_episode_share": Decimal("0.3"),
        "top_five_trade_share": Decimal("0.5"),
        "has_positive_episode_profit": True,
        "has_positive_trade_profit": True,
        "has_complete_seven_day_block": True,
    }


def test_bootstrap_blocks_are_seven_consecutive_full_calendar_days() -> None:
    indices = _circular_moving_block_indices(20, random_seed=20260714)

    assert len(indices) == 20
    for offset in range(0, len(indices), 7):
        block = indices[offset : offset + 7]
        assert all(right == (left + 1) % 20 for left, right in zip(block, block[1:]))
    labels = tuple("target" if index % 2 == 0 else "other" for index in range(20))
    filtered = tuple(index for index in indices if labels[index] == "target")
    assert any(right != (left + 1) % 20 for left, right in zip(filtered, filtered[1:]))


def test_max_stat_correction_includes_every_coverage_eligible_candidate() -> None:
    n = 140
    labels = ("target",) * n
    steady = tuple(Decimal(str(0.002 + 0.01 * math.sin(index))) for index in range(n))
    challenger = tuple(Decimal(str(0.002 + 0.01 * math.cos(index * 1.7))) for index in range(n))

    alone = _aligned_component_corrected_lower_bounds(
        {"steady": steady}, labels, "target", resamples=5000
    )
    family = _aligned_component_corrected_lower_bounds(
        {"steady": steady, "challenger": challenger}, labels, "target", resamples=5000
    )

    assert family["steady"] < alone["steady"]


def test_corrected_lower_bounds_are_byte_deterministic() -> None:
    labels = ("target",) * 70
    matrix = {
        "a": tuple(Decimal(str(0.003 + 0.01 * math.sin(index))) for index in range(70)),
        "b": tuple(Decimal(str(0.002 + 0.009 * math.cos(index))) for index in range(70)),
    }

    first = _aligned_component_corrected_lower_bounds(matrix, labels, "target", resamples=5000)
    second = _aligned_component_corrected_lower_bounds(matrix, labels, "target", resamples=5000)

    encode = lambda value: json.dumps({key: str(item) for key, item in value.items()}, sort_keys=True).encode()
    assert encode(first) == encode(second)


def test_positive_naive_lower_bound_can_fail_after_max_stat_correction() -> None:
    n = 140
    labels = ("target",) * n
    rng = np.random.default_rng(2)
    matrix = {
        f"candidate-{candidate}": tuple(
            Decimal(str(value))
            for value in 0.0022 + 0.012 * rng.standard_normal(n)
        )
        for candidate in range(20)
    }
    values = np.asarray([float(value) for value in matrix["candidate-0"]], dtype=np.float64)
    naive_lcb = values.mean() - 1.645 * values.std(ddof=1) / math.sqrt(n)

    corrected = _aligned_component_corrected_lower_bounds(matrix, labels, "target", resamples=5000)

    assert naive_lcb > 0
    assert corrected["candidate-0"] <= 0


def test_zero_variance_streams_never_emit_nan() -> None:
    labels = ("target",) * 30
    result = _aligned_component_corrected_lower_bounds(
        {
            "positive": (Decimal("0.001"),) * 30,
            "zero": (ZERO,) * 30,
            "negative": (Decimal("-0.001"),) * 30,
        },
        labels,
        "target",
        resamples=100,
    )

    assert result["positive"] == Decimal("0.001")
    assert result["zero"] <= 0
    assert result["negative"] <= 0
    assert all(value.is_finite() for value in result.values())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"random_seed": True},
        {"random_seed": -1},
        {"random_seed": 2**64},
        {"block_days": True},
        {"block_days": 0},
    ],
)
def test_circular_bootstrap_rejects_invalid_private_controls(kwargs) -> None:
    with pytest.raises(ValueError, match="random seed|block days"):
        _circular_moving_block_indices(30, **kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"random_seed": True},
        {"random_seed": -1},
        {"random_seed": 2**64},
        {"block_days": True},
        {"block_days": 0},
        {"maximum_attempts": True},
        {"maximum_attempts": 0},
    ],
)
def test_corrected_bounds_reject_invalid_private_bootstrap_controls(kwargs) -> None:
    with pytest.raises(ValueError, match="random seed|block days|maximum attempts"):
        _aligned_component_corrected_lower_bounds(
            {"candidate": (Decimal("0.001"),) * 30},
            ("target",) * 30,
            "target",
            resamples=1,
            **kwargs,
        )


@pytest.mark.parametrize(
    "confidence",
    [
        Decimal("0.95"),
        "0.95",
        1,
        True,
        float("nan"),
        float("inf"),
        0.0,
        1.0,
        -0.1,
    ],
)
def test_corrected_bounds_require_strict_finite_float_confidence(confidence) -> None:
    with pytest.raises(ValueError, match="confidence"):
        _aligned_component_corrected_lower_bounds(
            {"candidate": (Decimal("0.001"),) * 30},
            ("target",) * 30,
            "target",
            resamples=1,
            confidence=confidence,
        )


def test_expected_shortfall_is_mean_of_exact_worst_ceiling_ten_percent() -> None:
    values = tuple(map(Decimal, ["-0.20", "-0.10", *(["0.01"] * 9)]))
    assert expected_shortfall_10(values) == Decimal("-0.15")


def test_worst_seven_day_return_compounds_and_does_not_bridge_unavailable_gaps() -> None:
    values = (Decimal("-0.01"),) * 7 + (None,) + (Decimal("-0.02"),) * 6
    assert worst_seven_calendar_day_return(values) == (Decimal("0.99") ** 7) - 1


def test_compounding_helpers_reject_total_loss_or_worse() -> None:
    with pytest.raises(ValueError, match="greater than -1"):
        worst_seven_calendar_day_return((Decimal("-1"),) * 7)
    with pytest.raises(ValueError, match="greater than -1"):
        maximum_drawdown((Decimal("-1.01"),))


def test_maximum_drawdown_uses_compounded_equity() -> None:
    assert maximum_drawdown((Decimal("0.10"), Decimal("-0.20"), Decimal("0.05"))) == Decimal("0.20")


def test_return_without_best_episode_compounds_all_remaining_days() -> None:
    assert compounded_return_without_best_episode(
        (Decimal("0.10"), Decimal("0.02"), Decimal("-0.01"))
    ) == Decimal("1.02") * Decimal("0.99") - 1


def test_positive_profit_concentration_uses_positive_denominators_only() -> None:
    shares = positive_profit_concentration_shares(
        (Decimal("5"), Decimal("3"), Decimal("-100")),
        (Decimal("4"), Decimal("3"), Decimal("2"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("-20")),
    )
    assert shares == (
        Decimal("0.625"),
        Decimal("0.91666666666666666666666666666666666666666666666667"),
        True,
        True,
    )
    assert positive_profit_concentration_shares((ZERO,), (Decimal("-1"),)) == (ZERO, ZERO, False, False)


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"episode_count": 29}, "insufficient_daily_episodes"),
        ({"calendar_month_count": 2}, "insufficient_calendar_months"),
        ({"closed_trade_count": 29}, "insufficient_closed_trades"),
        ({"net_compounded_return": ZERO}, "non_positive_net_performance_after_costs"),
        ({"corrected_lower_bound": ZERO}, "non_positive_corrected_lower_bound"),
        ({"worst_seven_day_return": Decimal("-0.031")}, "worst_seven_day_return_below_limit"),
        ({"expected_shortfall": Decimal("-0.011")}, "expected_shortfall_below_limit"),
        ({"drawdown": Decimal("0.101")}, "maximum_drawdown_above_limit"),
        ({"return_without_best": ZERO}, "non_positive_return_without_best_episode"),
        ({"top_episode_share": Decimal("0.401")}, "top_episode_profit_share_above_limit"),
        ({"top_five_trade_share": Decimal("0.601")}, "top_five_trade_profit_share_above_limit"),
        ({"has_positive_episode_profit": False}, "no_positive_episode_profit"),
        ({"has_positive_trade_profit": False}, "no_positive_trade_profit"),
        ({"has_complete_seven_day_block": False}, "insufficient_complete_seven_day_blocks"),
    ],
)
def test_each_strict_eligibility_gate_is_auditable(change, reason) -> None:
    values = valid_gate_values()
    values.update(change)
    reasons = rejection_reasons(**values)
    assert reason in reasons
    assert rejection_reasons(**valid_gate_values()) == ()


def test_non_positive_lcb_records_distinct_cash_dominance_reason(monkeypatch) -> None:
    values = valid_gate_values()
    values["corrected_lower_bound"] = ZERO
    assert "non_positive_corrected_lower_bound" in rejection_reasons(**values)
    assert "statistically_not_better_than_cash" in rejection_reasons(**values)

    monkeypatch.setattr(
        module,
        "_aligned_component_corrected_lower_bounds",
        lambda returns_by_candidate, *args, **kwargs: {
            candidate: ZERO for candidate in returns_by_candidate
        },
    )
    result = BuildDailyStrategyMappingUseCase().execute(valid_command())

    assert all(entry.decision == "cash" for entry in result.artifact.entries)
    assert all(
        "statistically_not_better_than_cash" in entry.rejection_reasons
        for entry in result.artifact.entries
    )


@pytest.mark.parametrize(
    ("left_changes", "right_changes"),
    [
        ({"corrected_lower_bound_ratio": Decimal("0.002")}, {}),
        ({}, {"return_without_best_episode_ratio": Decimal("0.02")}),
        ({}, {"expected_shortfall_10_ratio": Decimal("-0.009")}),
        ({}, {"maximum_drawdown_ratio": Decimal("0.06")}),
        ({}, {"median_daily_return_ratio": Decimal("0.0009")}),
        ({}, {}),
    ],
)
def test_winner_order_uses_each_exact_tie_break(left_changes, right_changes) -> None:
    left = assessment("candidate-a", **left_changes)
    right = assessment("candidate-b", **right_changes)
    assert _winner_order_key(left) < _winner_order_key(right)


def valid_command(*, candidates: tuple[str, ...] = ("candidate-a",)) -> BuildDailyStrategyMappingCommand:
    calendar = mapping_calendar()
    assignments = tuple(COMPONENTS[index % 4] for index in range(len(calendar)))
    manifest = tuple((candidate, sha(candidate)) for candidate in candidates)
    rows = tuple(
        evidence(
            day=day,
            component=component,
            candidate=candidate,
            candidate_hash=sha(candidate),
        )
        for day, component in zip(calendar, assignments)
        for candidate in candidates
    )
    return BuildDailyStrategyMappingCommand(
        model_artifact_hash=MODEL_HASH,
        candidate_manifest=manifest,
        calendar=calendar,
        component_assignments=assignments,
        evidence_rows=rows,
    )


def precise_command() -> BuildDailyStrategyMappingCommand:
    command = valid_command()
    daily_return = Decimal(
        "0.0012345678901234567890123456789012345678901234567"
    )
    final_equity = Decimal(
        "1.0012345678901234567890123456789012345678901234567"
    )
    rows = tuple(
        replace(
            row,
            initial_equity=Decimal(1),
            final_equity=final_equity,
            gross_pnl=daily_return,
            net_pnl=daily_return,
            gross_return_ratio=daily_return,
            net_return_ratio=daily_return,
            fees=Decimal(0),
            closed_trade_count=1,
            trade_pnls=(daily_return,),
        )
        for row in command.evidence_rows
    )
    return replace(command, evidence_rows=rows)


def test_full_mapping_is_independent_of_ambient_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 6
        low_command = precise_command()
        low = BuildDailyStrategyMappingUseCase().execute(low_command).artifact
        assert getcontext().prec == 6
    with localcontext() as context:
        context.prec = 60
        high_command = precise_command()
        high = BuildDailyStrategyMappingUseCase().execute(high_command).artifact
        assert getcontext().prec == 60

    assert low_command == high_command
    assert low.candidate_assessments == high.candidate_assessments
    assert low.entries == high.entries
    assert low.canonical_payload() == high.canonical_payload()
    assert daily_mapping_artifact_hash(low) == daily_mapping_artifact_hash(high)


def test_use_case_assesses_full_frozen_grid_and_emits_exactly_four_entries() -> None:
    result = BuildDailyStrategyMappingUseCase().execute(valid_command())

    assert result.artifact.candidate_universe_hash == candidate_universe_hash(("candidate-a",))
    assert len(result.artifact.entries) == 4
    assert len(result.artifact.candidate_assessments) == 4
    assert {entry.component_fingerprint for entry in result.artifact.entries} == set(COMPONENTS)


def test_max_stat_universe_includes_coverage_eligible_candidate_with_too_few_trades(
    monkeypatch,
) -> None:
    command = valid_command(candidates=("candidate-a", "candidate-b"))
    command = replace(
        command,
        evidence_rows=tuple(
            evidence(
                day=row.outcome_start_at,
                component=row.component_fingerprint,
                candidate=row.candidate_id,
                candidate_hash=row.candidate_hash,
                daily_return=ZERO,
                trades=(),
            )
            if row.candidate_id == "candidate-b"
            else row
            for row in command.evidence_rows
        ),
    )
    tested_families: list[tuple[str, ...]] = []

    def capture_family(returns_by_candidate, *args, **kwargs):
        tested_families.append(tuple(sorted(returns_by_candidate)))
        return {candidate: Decimal("0.001") for candidate in returns_by_candidate}

    monkeypatch.setattr(module, "_aligned_component_corrected_lower_bounds", capture_family)

    BuildDailyStrategyMappingUseCase().execute(command)

    assert tested_families == [("candidate-a", "candidate-b")] * 4


def test_unavailable_days_are_counted_as_exclusions_not_zero_returns() -> None:
    command = valid_command()
    target = command.evidence_rows[0]
    unavailable = evidence(
        day=target.outcome_start_at,
        component=target.component_fingerprint,
        candidate=target.candidate_id,
        candidate_hash=target.candidate_hash,
        available=False,
    )
    rows = (unavailable,) + command.evidence_rows[1:]

    result = BuildDailyStrategyMappingUseCase().execute(replace(command, evidence_rows=rows))
    item = next(
        value for value in result.artifact.candidate_assessments
        if value.component_fingerprint == target.component_fingerprint
    )

    assert item.episode_count == sum(
        component == target.component_fingerprint for component in command.component_assignments
    ) - 1
    assert item.mean_daily_return_ratio == Decimal("0.001")


def test_non_target_component_days_preserve_calendar_windows_as_neutral_days() -> None:
    command = valid_command()
    rows = tuple(
        evidence(
            day=row.outcome_start_at,
            component=row.component_fingerprint,
            candidate=row.candidate_id,
            candidate_hash=row.candidate_hash,
            daily_return=Decimal("-0.01"),
        )
        for row in command.evidence_rows
    )

    result = BuildDailyStrategyMappingUseCase().execute(
        replace(command, evidence_rows=rows)
    )
    item = next(
        value
        for value in result.artifact.candidate_assessments
        if value.component_fingerprint == COMPONENTS[0]
    )

    assert item.worst_seven_day_return_ratio == Decimal("0.99") ** 2 - 1


def test_unavailable_evidence_with_performance_is_rejected() -> None:
    command = valid_command()
    first = command.evidence_rows[0]
    contradictory = first
    object.__setattr__(contradictory, "availability_status", "unavailable")
    object.__setattr__(contradictory, "availability_reason", "feature_unavailable")

    with pytest.raises(ValueError, match="unavailable evidence cannot contain performance"):
        BuildDailyStrategyMappingUseCase().execute(
            replace(command, evidence_rows=(contradictory,) + command.evidence_rows[1:])
        )


def test_available_trades_require_trade_pnls_for_concentration_audit() -> None:
    command = valid_command()
    missing_ledger = command.evidence_rows[0]
    object.__setattr__(missing_ledger, "trade_pnls", None)

    with pytest.raises(ValueError, match="trade PnLs are required"):
        BuildDailyStrategyMappingUseCase().execute(
            replace(command, evidence_rows=(missing_ledger,) + command.evidence_rows[1:])
        )


def test_available_zero_trade_day_requires_explicit_empty_trade_ledger() -> None:
    command = valid_command()
    first = command.evidence_rows[0]
    missing_ledger = evidence(
        day=first.outcome_start_at,
        component=first.component_fingerprint,
        candidate=first.candidate_id,
        candidate_hash=first.candidate_hash,
        daily_return=ZERO,
        trades=(),
    )
    object.__setattr__(missing_ledger, "trade_pnls", None)

    with pytest.raises(ValueError, match="trade PnLs are required"):
        BuildDailyStrategyMappingUseCase().execute(
            replace(command, evidence_rows=(missing_ledger,) + command.evidence_rows[1:])
        )


def test_no_complete_seven_day_window_is_an_explicit_rejection() -> None:
    command = valid_command()
    rows = tuple(
        evidence(
            day=row.outcome_start_at,
            component=row.component_fingerprint,
            candidate=row.candidate_id,
            candidate_hash=row.candidate_hash,
            available=False,
        )
        if row.component_fingerprint == COMPONENTS[0]
        else row
        for row in command.evidence_rows
    )

    result = BuildDailyStrategyMappingUseCase().execute(
        replace(command, evidence_rows=rows)
    )
    item = next(
        value
        for value in result.artifact.candidate_assessments
        if value.component_fingerprint == COMPONENTS[0]
    )

    assert "insufficient_complete_seven_day_blocks" in item.rejection_reasons


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda command: replace(command, calendar=command.calendar[:-1]), "complete Mapping Fit calendar"),
        (lambda command: replace(command, component_assignments=command.component_assignments[:-1]), "component assignment"),
        (lambda command: replace(command, component_assignments=("unknown",) + command.component_assignments[1:]), "exactly four"),
        (lambda command: replace(command, evidence_rows=command.evidence_rows + (command.evidence_rows[0],)), "duplicate"),
        (lambda command: replace(command, evidence_rows=command.evidence_rows[:-1]), "coverage"),
        (lambda command: replace(command, evidence_rows=(replace(command.evidence_rows[0], model_artifact_hash=sha("drift")),) + command.evidence_rows[1:]), "model hash"),
        (lambda command: replace(command, evidence_rows=(replace(command.evidence_rows[0], candidate_hash=sha("drift")),) + command.evidence_rows[1:]), "candidate hash"),
        (lambda command: replace(command, candidate_manifest=command.candidate_manifest + (("candidate-z", sha("candidate-z")),)), "coverage"),
        (lambda command: replace(command, evidence_rows=(replace(command.evidence_rows[0], outcome_start_at=command.calendar[-1] + timedelta(days=1), outcome_end_at=command.calendar[-1] + timedelta(days=2), cluster_anchor_at=command.calendar[-1] + timedelta(days=1), feature_start_at=command.calendar[-1] - timedelta(days=2), feature_end_at=command.calendar[-1] + timedelta(days=1)),) + command.evidence_rows[1:]), "outside"),
        (lambda command: replace(command, evidence_rows=(replace(command.evidence_rows[0], candidate_id="candidate-z", candidate_hash=sha("candidate-z")),) + command.evidence_rows[1:]), "frozen manifest"),
        (lambda command: replace(command, evidence_rows=(replace(command.evidence_rows[0], component_fingerprint=COMPONENTS[1]),) + command.evidence_rows[1:]), "component coverage mismatch"),
        (lambda command: replace(command, evidence_rows=(replace(command.evidence_rows[0], cost_config_hash=sha("cost-drift")),) + command.evidence_rows[1:]), "cost configuration hash"),
        (lambda command: replace(command, evidence_rows=(replace(command.evidence_rows[0], engine_config_hash=sha("engine-drift")),) + command.evidence_rows[1:]), "engine configuration hash"),
    ],
)
def test_use_case_fails_closed_on_grid_or_hash_drift(mutate, message) -> None:
    with pytest.raises(ValueError, match=message):
        BuildDailyStrategyMappingUseCase().execute(mutate(valid_command()))


def test_no_eligible_candidate_produces_explicit_cash_with_all_reasons() -> None:
    command = valid_command()
    rows = tuple(
        replace(
            row,
            final_equity=Decimal("100"),
            gross_pnl=ZERO,
            net_pnl=ZERO,
            gross_return_ratio=ZERO,
            net_return_ratio=ZERO,
            closed_trade_count=0,
            trade_pnls=(),
        )
        for row in command.evidence_rows
    )

    result = BuildDailyStrategyMappingUseCase().execute(replace(command, evidence_rows=rows))

    assert all(entry.decision == "cash" for entry in result.artifact.entries)
    assert all("no_eligible_candidate" in entry.rejection_reasons for entry in result.artifact.entries)
    assert all(entry.rejection_reasons for entry in result.artifact.entries)
