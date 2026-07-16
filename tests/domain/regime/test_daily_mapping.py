from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext, localcontext
import hashlib

import pytest

from src.domain import regime
from src.domain.regime.mapping import candidate_universe_hash
from src.domain.regime.temporal import UtcInterval
from src.domain.regime.three_day_chart_features import THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
from src.domain.regime.three_day_daily_profile import (
    PROFILE_ID,
    STRICT_RISK_POLICY,
    ThreeDayDailyWalkForwardFold,
)
from src.domain.regime.daily_mapping import (
    DAILY_STRATEGY_MAPPING_ARTIFACT_VERSION,
    DailyCandidateAssessment,
    DailyStrategyEvidence,
    DailyStrategyMappingArtifact,
    DailyStrategyMappingEntry,
    daily_mapping_artifact_hash,
    daily_strategy_evidence_hash,
)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def evidence(**changes) -> DailyStrategyEvidence:
    fields = {
        "component_fingerprint": "component-a",
        "candidate_id": "candidate-a",
        "cluster_anchor_at": dt("2025-07-10"),
        "feature_start_at": dt("2025-07-07"),
        "feature_end_at": dt("2025-07-10"),
        "outcome_start_at": dt("2025-07-10"),
        "outcome_end_at": dt("2025-07-11"),
        "initial_equity": Decimal("1000"),
        "final_equity": Decimal("1005"),
        "gross_pnl": Decimal("6"),
        "net_pnl": Decimal("5"),
        "gross_return_ratio": Decimal("0.006"),
        "net_return_ratio": Decimal("0.005"),
        "fees": Decimal("1"),
        "closed_trade_count": 2,
        "exposure_ratio": Decimal("0.50"),
        "turnover_ratio": Decimal("1.25"),
        "maximum_drawdown_ratio": Decimal("0.02"),
        "maximum_adverse_excursion_ratio": Decimal("0.01"),
        "profit_factor": Decimal("1.5"),
        "downside_deviation_ratio": Decimal("0.003"),
        "expected_shortfall_10_ratio": Decimal("-0.004"),
        "median_daily_return_ratio": Decimal("0.005"),
        "tenth_percentile_daily_return_ratio": Decimal("-0.002"),
        "worst_seven_day_return_ratio": Decimal("-0.01"),
        "return_without_best_episode_ratio": Decimal("0.02"),
        "top_episode_profit_share": Decimal("0.20"),
        "top_five_trade_profit_share": Decimal("0.40"),
        "availability_status": "available",
        "availability_reason": None,
        "candidate_hash": sha("candidate-a"),
        "model_artifact_hash": sha("model"),
        "data_hash": sha("data"),
        "cost_config_hash": sha("costs"),
        "engine_config_hash": sha("engine"),
        "trade_pnls": (Decimal("2"), Decimal("3")),
    }
    fields.update(changes)
    return DailyStrategyEvidence(**fields)


def unavailable_evidence(**changes) -> DailyStrategyEvidence:
    fields = {
        "final_equity": Decimal("1000"),
        "gross_pnl": Decimal(0),
        "net_pnl": Decimal(0),
        "gross_return_ratio": Decimal(0),
        "net_return_ratio": Decimal(0),
        "fees": Decimal(0),
        "closed_trade_count": 0,
        "exposure_ratio": Decimal(0),
        "turnover_ratio": Decimal(0),
        "maximum_drawdown_ratio": Decimal(0),
        "maximum_adverse_excursion_ratio": Decimal(0),
        "profit_factor": Decimal(0),
        "downside_deviation_ratio": Decimal(0),
        "expected_shortfall_10_ratio": Decimal(0),
        "median_daily_return_ratio": Decimal(0),
        "tenth_percentile_daily_return_ratio": Decimal(0),
        "worst_seven_day_return_ratio": Decimal(0),
        "return_without_best_episode_ratio": Decimal(0),
        "top_episode_profit_share": Decimal(0),
        "top_five_trade_profit_share": Decimal(0),
        "availability_status": "unavailable",
        "availability_reason": "feature_unavailable",
        "trade_pnls": None,
    }
    fields.update(changes)
    return evidence(**fields)


def assessment(component: str = "component-a", candidate: str = "candidate-a", **changes):
    fields = {
        "component_fingerprint": component,
        "candidate_id": candidate,
        "candidate_hash": sha(candidate),
        "assigned_day_count": 40,
        "episode_count": 35,
        "unavailable_day_count": 5,
        "unavailable_reason_counts": (("feature_unavailable", 5),),
        "calendar_month_count": 4,
        "closed_trade_count": 40,
        "mean_daily_return_ratio": Decimal("0.003"),
        "median_daily_return_ratio": Decimal("0.002"),
        "corrected_lower_bound_ratio": Decimal("0.001"),
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


def test_assessment_binds_assigned_available_and_unavailable_audit_counts():
    item = assessment()

    assert item.assigned_day_count == 40
    assert item.episode_count == 35
    assert item.unavailable_day_count == 5
    assert item.unavailable_reason_counts == (("feature_unavailable", 5),)

    with pytest.raises(ValueError, match="assigned day count"):
        assessment(assigned_day_count=39)
    with pytest.raises(ValueError, match="unavailable reason counts"):
        assessment(unavailable_reason_counts=(("feature_unavailable", 4),))
    with pytest.raises(ValueError, match="canonical sorted"):
        assessment(
            unavailable_reason_counts=(("warmup_missing", 2), ("feature_unavailable", 3))
        )


def artifact(**changes) -> DailyStrategyMappingArtifact:
    components = ("component-a", "component-b", "component-c", "component-d")
    candidates = ("candidate-a", "candidate-b")
    entries = (
        DailyStrategyMappingEntry("component-a", "strategy", "candidate-a"),
        DailyStrategyMappingEntry("component-b", "cash", None, ("no_eligible_candidate",)),
        DailyStrategyMappingEntry("component-c", "cash", None, ("insufficient_evidence",)),
        DailyStrategyMappingEntry("component-d", "strategy", "candidate-b"),
    )
    candidate_hashes = {candidate: sha(candidate) for candidate in candidates}
    assessments = tuple(
        assessment(
            component,
            candidate,
            eligible=(component, candidate)
            in {("component-a", "candidate-a"), ("component-d", "candidate-b")},
            rejection_reasons=()
            if (component, candidate)
            in {("component-a", "candidate-a"), ("component-d", "candidate-b")}
            else ("not_eligible",),
        )
        for component in components
        for candidate in candidates
    )
    fold = ThreeDayDailyWalkForwardFold.default()
    fields = {
        "artifact_version": DAILY_STRATEGY_MAPPING_ARTIFACT_VERSION,
        "profile_id": PROFILE_ID,
        "feature_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        "model_artifact_hash": sha("model"),
        "candidate_universe_hash": candidate_universe_hash(candidates),
        "candidate_ids": candidates,
        "candidate_hashes": candidate_hashes,
        "component_fingerprints": components,
        "entries": entries,
        "candidate_assessments": assessments,
        "risk_policy": STRICT_RISK_POLICY,
        "cluster_fit": fold.cluster_fit,
        "mapping_fit": fold.mapping_fit,
    }
    fields.update(changes)
    return DailyStrategyMappingArtifact(**fields)


def test_daily_evidence_binds_three_day_anchor_to_exact_one_day_outcome():
    item = evidence()

    assert (item.feature_start_at, item.feature_end_at) == (
        item.cluster_anchor_at - timedelta(days=3),
        item.cluster_anchor_at,
    )
    assert item.outcome_start_at == item.cluster_anchor_at
    assert item.outcome_end_at - item.outcome_start_at == timedelta(days=1)
    assert item.trade_pnls == (Decimal("2"), Decimal("3"))
    with pytest.raises(FrozenInstanceError):
        item.candidate_id = "changed"


def test_available_evidence_requires_an_exact_tuple_trade_ledger():
    with pytest.raises(ValueError, match="available evidence requires trade PnLs"):
        evidence(trade_pnls=None)
    with pytest.raises(ValueError, match="tuple"):
        evidence(trade_pnls=[Decimal("2"), Decimal("3")])

    zero_trade = evidence(
        final_equity=Decimal("1000"),
        gross_pnl=Decimal(0),
        net_pnl=Decimal(0),
        gross_return_ratio=Decimal(0),
        net_return_ratio=Decimal(0),
        fees=Decimal(0),
        closed_trade_count=0,
        trade_pnls=(),
    )
    assert zero_trade.trade_pnls == ()


def test_unavailable_evidence_requires_zero_performance_and_no_trade_ledger():
    item = unavailable_evidence()
    assert item.trade_pnls is None

    with pytest.raises(ValueError, match="unavailable evidence cannot contain performance"):
        unavailable_evidence(exposure_ratio=Decimal("0.1"))
    with pytest.raises(ValueError, match="unavailable evidence cannot contain a trade ledger"):
        unavailable_evidence(trade_pnls=())


def test_daily_evidence_consistency_is_independent_of_ambient_decimal_context():
    value = Decimal("0.1234567890123456789012345678901234567890123456789")
    changes = {
        "initial_equity": Decimal("1"),
        "final_equity": Decimal("1.1234567890123456789012345678901234567890123456789"),
        "gross_pnl": value,
        "net_pnl": value,
        "gross_return_ratio": value,
        "net_return_ratio": value,
        "fees": Decimal(0),
        "closed_trade_count": 1,
        "trade_pnls": (value,),
    }

    with localcontext() as context:
        context.prec = 6
        low = evidence(**changes)
        assert getcontext().prec == 6
    with localcontext() as context:
        context.prec = 60
        high = evidence(**changes)
        assert getcontext().prec == 60

    assert low == high


def test_daily_mapping_contracts_are_exported_from_regime_api():
    expected = {
        "DailyCandidateAssessment": DailyCandidateAssessment,
        "DailyStrategyEvidence": DailyStrategyEvidence,
        "DailyStrategyMappingArtifact": DailyStrategyMappingArtifact,
        "DailyStrategyMappingEntry": DailyStrategyMappingEntry,
        "daily_mapping_artifact_hash": daily_mapping_artifact_hash,
        "daily_strategy_evidence_hash": daily_strategy_evidence_hash,
    }

    assert {name: getattr(regime, name) for name in expected} == expected
    assert set(expected) <= set(regime.__all__)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"cluster_anchor_at": dt("2025-07-09")}, "cluster anchor"),
        ({"feature_start_at": dt("2025-07-08")}, "exactly three days"),
        ({"feature_end_at": dt("2025-07-09")}, "feature end"),
        ({"feature_start_at": datetime(2025, 7, 7)}, "canonical midnight UTC"),
        ({"feature_end_at": dt("2025-07-10") + timedelta(hours=1)}, "canonical midnight UTC"),
        ({"outcome_end_at": dt("2025-07-12")}, "exactly one day"),
        ({"outcome_start_at": datetime(2025, 7, 10)}, "canonical midnight UTC"),
        ({"outcome_start_at": dt("2025-07-10") + timedelta(hours=1)}, "canonical midnight UTC"),
        ({"model_artifact_hash": "bad"}, "SHA256"),
        ({"net_return_ratio": Decimal("NaN")}, "finite Decimal"),
        ({"availability_status": "available", "availability_reason": "gap"}, "availability"),
        ({"availability_status": "unavailable", "availability_reason": None}, "availability"),
    ],
)
def test_daily_evidence_rejects_interval_identity_and_availability_drift(changes, message):
    with pytest.raises(ValueError, match=message):
        evidence(**changes)


def test_daily_evidence_canonical_payload_and_hash_bind_feature_interval():
    first = evidence()
    shifted = evidence(
        cluster_anchor_at=dt("2025-07-11"),
        feature_start_at=dt("2025-07-08"),
        feature_end_at=dt("2025-07-11"),
        outcome_start_at=dt("2025-07-11"),
        outcome_end_at=dt("2025-07-12"),
    )

    assert first.canonical_payload()["feature_interval"] == {
        "start_at": "2025-07-07T00:00:00Z",
        "end_at": "2025-07-10T00:00:00Z",
    }
    assert len(daily_strategy_evidence_hash(first)) == 64
    assert daily_strategy_evidence_hash(first) != daily_strategy_evidence_hash(shifted)


def test_evidence_hash_preserves_adjacent_high_precision_decimals():
    first = evidence(
        turnover_ratio=Decimal("1.1234567890123456789012345678901234567890")
    )
    adjacent = evidence(
        turnover_ratio=Decimal("1.1234567890123456789012345678901234567891")
    )

    assert daily_strategy_evidence_hash(first) != daily_strategy_evidence_hash(adjacent)


def test_evidence_hash_is_independent_of_decimal_context_precision():
    item = evidence(
        turnover_ratio=Decimal("1.1234567890123456789012345678901234567890")
    )

    with localcontext() as context:
        context.prec = 6
        low_precision_hash = daily_strategy_evidence_hash(item)
    with localcontext() as context:
        context.prec = 60
        high_precision_hash = daily_strategy_evidence_hash(item)

    assert low_precision_hash == high_precision_hash


def test_evidence_hash_canonicalizes_trailing_fractional_zeros_and_signed_zero():
    assert daily_strategy_evidence_hash(
        evidence(turnover_ratio=Decimal("1.2300"))
    ) == daily_strategy_evidence_hash(evidence(turnover_ratio=Decimal("1.23")))
    assert daily_strategy_evidence_hash(
        evidence(turnover_ratio=Decimal("-0E-100"))
    ) == daily_strategy_evidence_hash(evidence(turnover_ratio=Decimal("0")))


def test_cash_mapping_entry_is_explicit_and_requires_a_rejection_reason():
    entry = DailyStrategyMappingEntry(
        component_fingerprint="component-a",
        decision="cash",
        strategy_candidate_id=None,
        rejection_reasons=("no_eligible_candidate",),
    )

    assert entry.decision == "cash"
    with pytest.raises(ValueError, match="cannot contain a strategy candidate"):
        replace(entry, strategy_candidate_id="candidate-a")
    with pytest.raises(ValueError, match="rejection reason"):
        replace(entry, rejection_reasons=())


def test_artifact_requires_exactly_four_unique_component_entries_and_freezes_collections():
    result = artifact()

    assert tuple(entry.component_fingerprint for entry in result.entries) == result.component_fingerprints
    assert len(result.entries) == 4
    with pytest.raises(FrozenInstanceError):
        result.entries = ()

    with pytest.raises(ValueError, match="exactly four unique"):
        artifact(component_fingerprints=("component-a",) * 4)
    with pytest.raises(ValueError, match="component coverage"):
        artifact(entries=result.entries[:-1])
    with pytest.raises(ValueError, match="component coverage"):
        artifact(
            entries=(
                replace(result.entries[0], component_fingerprint="component-b"),
                *result.entries[1:],
            )
        )


def test_artifact_enforces_model_and_candidate_universe_compatibility():
    result = artifact()

    with pytest.raises(ValueError, match="candidate universe hash"):
        replace(result, candidate_universe_hash=sha("wrong"))
    with pytest.raises(ValueError, match="candidate universe"):
        replace(result, candidate_ids=("candidate-a",))
    with pytest.raises(ValueError, match="candidate universe"):
        replace(
            result,
            entries=(
                replace(result.entries[0], strategy_candidate_id="candidate-unknown"),
                *result.entries[1:],
            ),
        )
    with pytest.raises(ValueError, match="model artifact hash"):
        replace(result, model_artifact_hash="A" * 64)
    with pytest.raises(ValueError, match="candidate assessment hash"):
        replace(
            result,
            candidate_hashes={**result.candidate_hashes, "candidate-a": sha("drift")},
        )
    with pytest.raises(ValueError, match="assessment coverage"):
        replace(result, candidate_assessments=result.candidate_assessments[:-1])


@pytest.mark.parametrize(
    "field",
    [
        "mean_daily_return_ratio",
        "corrected_lower_bound_ratio",
        "expected_shortfall_10_ratio",
        "maximum_drawdown_ratio",
        "top_episode_profit_share",
    ],
)
def test_assessment_rejects_nonfinite_statistics(field):
    with pytest.raises(ValueError, match="finite Decimal"):
        assessment(**{field: Decimal("NaN")})


def test_artifact_hash_is_canonical_and_binds_the_payload():
    first = artifact()
    second = artifact()
    reordered = replace(first, candidate_assessments=tuple(reversed(first.candidate_assessments)))
    permuted = artifact(
        component_fingerprints=tuple(reversed(first.component_fingerprints)),
        entries=tuple(reversed(first.entries)),
        candidate_assessments=tuple(reversed(first.candidate_assessments)),
    )

    assert daily_mapping_artifact_hash(first) == daily_mapping_artifact_hash(second)
    assert daily_mapping_artifact_hash(first) == daily_mapping_artifact_hash(reordered)
    assert permuted.component_fingerprints == first.component_fingerprints
    assert permuted.entries == first.entries
    assert permuted.candidate_assessments == first.candidate_assessments
    assert daily_mapping_artifact_hash(first) == daily_mapping_artifact_hash(permuted)
    assert len(daily_mapping_artifact_hash(first)) == 64
    assert daily_mapping_artifact_hash(first) != daily_mapping_artifact_hash(
        replace(first, model_artifact_hash=sha("different-model"))
    )
    assert first.canonical_payload()["research_profile"] == {
        "profile_id": PROFILE_ID,
        "random_seed": 20260714,
        "model_type": "gmm",
        "covariance_type": "diag",
        "cluster_count": 4,
        "regularization": "0.000001",
        "feature_window_days": 3,
        "outcome_window_days": 1,
        "bootstrap_block_days": 7,
        "bootstrap_resamples": 5000,
        "bootstrap_confidence": "0.95",
        "minimum_episodes": 30,
        "minimum_calendar_months": 3,
        "minimum_closed_trades": 30,
        "decimal_arithmetic": {
            "precision": 50,
            "rounding": "ROUND_HALF_EVEN",
        },
        "fold": {
            "cluster_fit": {"start_at": "2021-01-01T00:00:00Z", "end_at": "2025-06-30T00:00:00Z"},
            "mapping_fit": {"start_at": "2025-07-07T00:00:00Z", "end_at": "2026-01-01T00:00:00Z"},
            "validation": {"start_at": "2026-01-04T00:00:00Z", "end_at": "2026-04-01T00:00:00Z"},
            "test": {"start_at": "2026-04-04T00:00:00Z", "end_at": "2026-07-01T00:00:00Z"},
        },
    }


def test_artifact_hash_preserves_adjacent_high_precision_decimals():
    first = artifact()
    precise = Decimal("0.1234567890123456789012345678901234567890")
    adjacent = Decimal("0.1234567890123456789012345678901234567891")

    first_assessments = (
        replace(first.candidate_assessments[0], mean_daily_return_ratio=precise),
        *first.candidate_assessments[1:],
    )
    adjacent_assessments = (
        replace(first.candidate_assessments[0], mean_daily_return_ratio=adjacent),
        *first.candidate_assessments[1:],
    )

    assert daily_mapping_artifact_hash(
        replace(first, candidate_assessments=first_assessments)
    ) != daily_mapping_artifact_hash(
        replace(first, candidate_assessments=adjacent_assessments)
    )


def test_artifact_hash_binds_unavailable_audit_counts():
    first = artifact()
    changed = replace(
        first,
        candidate_assessments=(
            replace(
                first.candidate_assessments[0],
                unavailable_reason_counts=(("different_reason", 5),),
            ),
            *first.candidate_assessments[1:],
        ),
    )

    assert daily_mapping_artifact_hash(first) != daily_mapping_artifact_hash(changed)


def test_artifact_hash_is_independent_of_decimal_context_precision():
    first = artifact()
    assessments = (
        replace(
            first.candidate_assessments[0],
            mean_daily_return_ratio=Decimal(
                "0.1234567890123456789012345678901234567890"
            ),
        ),
        *first.candidate_assessments[1:],
    )
    precise_artifact = replace(first, candidate_assessments=assessments)

    with localcontext() as context:
        context.prec = 6
        low_precision_hash = daily_mapping_artifact_hash(precise_artifact)
    with localcontext() as context:
        context.prec = 60
        high_precision_hash = daily_mapping_artifact_hash(precise_artifact)

    assert low_precision_hash == high_precision_hash


def test_artifact_profile_payload_and_hash_are_stable_at_extreme_ambient_precisions():
    result = artifact()
    payloads = []
    hashes = []

    for precision in (1, 6, 60):
        with localcontext() as context:
            context.prec = precision
            payloads.append(result.canonical_payload())
            hashes.append(daily_mapping_artifact_hash(result))

    assert payloads[0] == payloads[1] == payloads[2]
    assert hashes[0] == hashes[1] == hashes[2]


def test_artifact_rejects_fit_interval_or_frozen_schema_drift():
    result = artifact()

    with pytest.raises(ValueError, match="profile"):
        replace(result, profile_id="other")
    with pytest.raises(ValueError, match="feature schema"):
        replace(result, feature_schema_version="other")
    with pytest.raises(ValueError, match="Mapping Fit"):
        replace(
            result,
            mapping_fit=UtcInterval(dt("2025-07-08"), result.mapping_fit.end_at),
        )
