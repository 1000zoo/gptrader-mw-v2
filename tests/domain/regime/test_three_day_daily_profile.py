from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

import pytest

import src.domain.regime.three_day_daily_profile as profile_module
from src.domain import regime
from src.domain.regime import RegimeWalkForwardFold, UtcInterval
from src.domain.regime.three_day_daily_profile import (
    BOOTSTRAP_BLOCK_DAYS,
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_RESAMPLES,
    CLUSTER_COUNT,
    COVARIANCE_TYPE,
    MIN_CALENDAR_MONTHS,
    MIN_CLOSED_TRADES,
    MIN_EPISODES,
    MODEL_TYPE,
    PROFILE_ID,
    RANDOM_SEED,
    REGULARIZATION,
    SENSITIVITY_POLICIES,
    STRICT_RISK_POLICY,
    DailyRiskPolicy,
    ThreeDayDailyResearchProfile,
    ThreeDayDailyWalkForwardFold,
)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def malformed_interval(start_at: datetime, end_at: datetime) -> UtcInterval:
    interval = object.__new__(UtcInterval)
    object.__setattr__(interval, "start_at", start_at)
    object.__setattr__(interval, "end_at", end_at)
    return interval


def test_default_fold_has_approved_half_open_intervals_and_purges():
    fold = ThreeDayDailyWalkForwardFold.default()

    assert fold.cluster_fit == UtcInterval(dt("2021-01-01"), dt("2025-06-30"))
    assert fold.mapping_fit == UtcInterval(dt("2025-07-07"), dt("2026-01-01"))
    assert fold.validation == UtcInterval(dt("2026-01-04"), dt("2026-04-01"))
    assert fold.test == UtcInterval(dt("2026-04-04"), dt("2026-07-01"))
    assert fold.mapping_fit.start_at - fold.cluster_fit.end_at == timedelta(days=7)
    assert fold.validation.start_at - fold.mapping_fit.end_at == timedelta(days=3)
    assert fold.test.start_at - fold.validation.end_at == timedelta(days=3)


def test_three_day_daily_research_contracts_are_exported_from_regime_api():
    expected = {
        "DailyRiskPolicy": DailyRiskPolicy,
        "ThreeDayDailyResearchProfile": ThreeDayDailyResearchProfile,
        "ThreeDayDailyWalkForwardFold": ThreeDayDailyWalkForwardFold,
    }

    assert {name: getattr(regime, name) for name in expected} == expected
    assert set(expected) <= set(regime.__all__)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "cluster_fit",
            malformed_interval(
                datetime(2021, 1, 1, 1, tzinfo=timezone.utc),
                dt("2025-06-30"),
            ),
            "midnight UTC",
        ),
        (
            "mapping_fit",
            malformed_interval(
                datetime(2025, 7, 7, tzinfo=ZoneInfo("Europe/London")),
                dt("2026-01-01"),
            ),
            "midnight UTC",
        ),
        (
            "mapping_fit",
            UtcInterval(dt("2025-06-29"), dt("2026-01-01")),
            "non-overlapping",
        ),
    ],
)
def test_fold_rejects_noncanonical_or_overlapping_intervals(field, value, message):
    with pytest.raises(ValueError, match=message):
        replace(ThreeDayDailyWalkForwardFold.default(), **{field: value})


def test_fold_rejects_less_than_seven_day_cluster_fit_purge():
    fold = ThreeDayDailyWalkForwardFold.default()

    with pytest.raises(ValueError, match="seven-day purge"):
        replace(
            fold,
            mapping_fit=UtcInterval(dt("2025-07-06"), fold.mapping_fit.end_at),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("validation", UtcInterval(dt("2026-01-03"), dt("2026-04-01"))),
        ("test", UtcInterval(dt("2026-04-03"), dt("2026-07-01"))),
    ],
)
def test_fold_rejects_less_than_three_day_outcome_purge(field, value):
    with pytest.raises(ValueError, match="three-day purge"):
        replace(ThreeDayDailyWalkForwardFold.default(), **{field: value})


def test_research_profile_freezes_model_bootstrap_and_coverage_contracts():
    profile = ThreeDayDailyResearchProfile()

    assert (
        profile.profile_id,
        profile.random_seed,
        profile.model_type,
        profile.covariance_type,
        profile.cluster_count,
        profile.regularization,
    ) == (PROFILE_ID, RANDOM_SEED, MODEL_TYPE, COVARIANCE_TYPE, CLUSTER_COUNT, REGULARIZATION)
    assert (profile.feature_window_days, profile.outcome_window_days) == (3, 1)
    assert (profile.bootstrap_block_days, profile.bootstrap_resamples, profile.bootstrap_confidence) == (
        BOOTSTRAP_BLOCK_DAYS,
        BOOTSTRAP_RESAMPLES,
        BOOTSTRAP_CONFIDENCE,
    )
    assert (profile.minimum_episodes, profile.minimum_calendar_months, profile.minimum_closed_trades) == (
        MIN_EPISODES,
        MIN_CALENDAR_MONTHS,
        MIN_CLOSED_TRADES,
    )
    assert profile.strict_risk_policy == STRICT_RISK_POLICY
    assert profile.sensitivity_policies == SENSITIVITY_POLICIES

    with pytest.raises(FrozenInstanceError):
        profile.cluster_count = 5

    with pytest.raises(ValueError, match="normative chronology"):
        replace(
            profile,
            fold=replace(
                profile.fold,
                cluster_fit=UtcInterval(dt("2021-01-01"), dt("2025-06-29")),
            ),
        )


def test_risk_policies_have_exact_frozen_decimal_values():
    assert STRICT_RISK_POLICY == DailyRiskPolicy(
        minimum_worst_seven_day_return_ratio=Decimal("-0.03"),
        minimum_expected_shortfall_10_ratio=Decimal("-0.01"),
        maximum_drawdown_ratio=Decimal("0.10"),
        maximum_top_episode_profit_share=Decimal("0.40"),
        maximum_top_five_trade_profit_share=Decimal("0.60"),
    )
    assert SENSITIVITY_POLICIES == {
        "tighter": DailyRiskPolicy(
            Decimal("-0.02"), Decimal("-0.0075"), Decimal("0.075"), Decimal("0.35"), Decimal("0.55")
        ),
        "looser": DailyRiskPolicy(
            Decimal("-0.04"), Decimal("-0.015"), Decimal("0.125"), Decimal("0.45"), Decimal("0.65")
        ),
    }


def test_research_profile_freezes_decimal_arithmetic_policy():
    profile = ThreeDayDailyResearchProfile()

    assert profile_module.DECIMAL_ARITHMETIC_PRECISION == 50
    assert profile_module.DECIMAL_ARITHMETIC_ROUNDING == "ROUND_HALF_EVEN"
    assert profile.decimal_arithmetic_precision == 50
    assert profile.decimal_arithmetic_rounding == "ROUND_HALF_EVEN"
    assert profile.canonical_payload()["decimal_arithmetic"] == {
        "precision": 50,
        "rounding": "ROUND_HALF_EVEN",
    }


def test_profile_number_serialization_never_uses_ambient_decimal_precision():
    payloads = []
    for precision in (1, 6, 60):
        with localcontext() as context:
            context.prec = precision
            assert profile_module._number_text(0.95) == "0.95"
            payloads.append(ThreeDayDailyResearchProfile().canonical_payload())

    assert payloads[0] == payloads[1] == payloads[2]
    assert payloads[0]["strict_risk_policy"] == STRICT_RISK_POLICY.canonical_payload()
    assert payloads[0]["sensitivity_policies"] == {
        name: policy.canonical_payload() for name, policy in sorted(SENSITIVITY_POLICIES.items())
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"cluster_count": 3}, "exactly four"),
        ({"model_type": "kmeans"}, "GMM"),
        ({"covariance_type": "tied"}, "diagonal"),
        ({"feature_window_days": 7}, "three days"),
        ({"random_seed": 1}, "random seed"),
        ({"bootstrap_resamples": 10}, "bootstrap resamples"),
        ({"regularization": float("nan")}, "finite"),
    ],
)
def test_profile_rejects_drift_from_frozen_contract(changes, message):
    with pytest.raises(ValueError, match=message):
        ThreeDayDailyResearchProfile(**changes)


def test_risk_policy_rejects_nonfinite_values():
    with pytest.raises(ValueError, match="finite Decimal"):
        replace(
            STRICT_RISK_POLICY,
            maximum_drawdown_ratio=Decimal("NaN"),
        )


def test_weekly_regime_fold_retains_original_seven_day_purge_semantics():
    with pytest.raises(ValueError, match="seven-day purge"):
        RegimeWalkForwardFold(
            cluster_fit=UtcInterval(dt("2021-01-01"), dt("2025-06-30")),
            mapping_fit=UtcInterval(dt("2025-07-03"), dt("2026-01-01")),
            validation=UtcInterval(dt("2026-01-08"), dt("2026-04-01")),
            test=UtcInterval(dt("2026-04-08"), dt("2026-07-01")),
        )
