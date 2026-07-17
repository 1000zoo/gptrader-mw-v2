from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import math
from types import MappingProxyType

import pytest

from src.application.services.frozen_k4_failure_decomposition import (
    CauseClassification,
    FrozenK4Decomposition,
    OODComponentRow,
    OODSampleContributionRow,
)
from src.application.services.frozen_k4_diagnosis_completion import (
    ComponentZeroOODAnalysis,
    OODFamilySummaryRow,
    OODFeatureSummaryRow,
    _registry_sha256,
    summarize_component_zero_ood,
)
from src.domain.regime import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)


REGISTRY = THREE_DAY_CHART_FEATURE_REGISTRY_V1
NAMES = tuple(spec.name for spec in REGISTRY)
FINGERPRINT = "a" * 24
SCOPE = "primary-component-0-ood-exceedances"


def _decomposition(
    contributions: tuple[dict[str, float], ...] | None = None,
    *,
    component_row: OODComponentRow | None = None,
    sample_fingerprint: str = FINGERPRINT,
    threshold: float = 0.5,
) -> FrozenK4Decomposition:
    if contributions is None:
        contributions = tuple(
            {name: (1.0 if name == "rv_4h" else 0.0) for name in NAMES}
            for _ in range(24)
        )
    samples = tuple(
        OODSampleContributionRow(
            anchor_at=f"2021-01-{index + 1:02d}T00:00:00Z",
            component_index=0,
            component_fingerprint=sample_fingerprint,
            squared_mahalanobis=sum(row.values()),
            threshold=threshold,
            feature_contributions=row,
        )
        for index, row in enumerate(contributions)
    )
    return FrozenK4Decomposition(
        cluster_summaries=(),
        cause_classification=CauseClassification((), {}),
        feature_contributions=(),
        top_drift_features={},
        location_distances=(),
        clipped_samples=(),
        exclusion_sensitivity=(),
        pooled_mahalanobis=(),
        component_distances=(),
        ood_by_component=(
            component_row or OODComponentRow(0, FINGERPRINT, 409, 24, 24 / 409),
        ),
        ood_samples=samples,
        offset_subsamples=(),
    )


def _rows(*pairs: tuple[str, float]) -> tuple[dict[str, float], ...]:
    row = dict.fromkeys(NAMES, 0.0)
    row.update(pairs)
    return tuple(dict(row) for _ in range(24))


def test_component_zero_summary_aggregates_feature_and_family_statistics() -> None:
    rows = []
    for index in range(24):
        row = dict.fromkeys(NAMES, 0.0)
        row["return_4h"] = 3.0 if index < 12 else 1.0
        row["rv_4h"] = 2.0
        row["rv_1d"] = 1.0
        row["range_ratio_3d"] = 1.0
        row["volume_cv_3d"] = 1.0
        rows.append(row)

    result = summarize_component_zero_ood(_decomposition(tuple(rows)), retained_feature_names=NAMES)

    assert isinstance(result, ComponentZeroOODAnalysis)
    assert result.analysis_scope == SCOPE
    assert result.primary_component_index == 0
    assert result.primary_component_fingerprint == FINGERPRINT
    assert (result.assigned_sample_count, result.ood_sample_count) == (409, 24)
    assert result.registry_schema_version == THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
    assert len(result.registry_sha256) == 64
    by_name = {row.feature_name: row for row in result.feature_rows}
    assert by_name["return_4h"].contribution_sum == 48.0
    assert by_name["return_4h"].contribution_mean == 2.0
    assert by_name["return_4h"].contribution_median == 2.0
    assert by_name["return_4h"].top1_count == 12
    assert by_name["return_4h"].top1_ratio == 0.5
    assert by_name["rv_4h"].top1_count == 12  # ties use registry order
    assert by_name["return_4h"].top5_count == 24
    assert sum(row.contribution_sum for row in result.feature_rows) == 168.0
    assert sum(row.contribution_ratio for row in result.feature_rows) == pytest.approx(1.0)
    assert result.top_five_features == (
        "return_4h", "rv_4h", "rv_1d", "range_ratio_3d", "volume_cv_3d"
    )
    assert [row.rank for row in result.feature_rows[:5]] == [1, 2, 3, 4, 5]

    families = {row.family_name: row for row in result.family_rows}
    assert tuple(families) == tuple(dict.fromkeys(spec.family for spec in REGISTRY))
    assert families["volatility"].family_feature_names == (
        "rv_4h", "rv_1d", "rv_3d", "rv_ratio_1d_3d"
    )
    assert "range_ratio_3d" not in families["volatility"].family_feature_names
    assert "volume_cv_3d" not in families["volatility"].family_feature_names
    assert families["volatility"].contribution_sum == 72.0
    assert families["volatility"].contribution_ratio == pytest.approx(72 / 168)
    assert all(row.concentration_threshold == 0.70 for row in result.family_rows)
    assert families["volatility"].concentration_rule_applies is True
    assert families["range"].concentration_rule_applies is False
    assert families["range"].concentration_result is False
    assert result.single_feature_concentration is False
    assert result.volatility_family_concentration is False
    assert result.recurrent_feature_dominance is True
    assert result.diagnostic_only is True


@pytest.mark.parametrize(
    ("share", "expected"),
    ((0.49, False), (0.50, True), (0.51, True)),
)
def test_single_feature_concentration_uses_inclusive_half_boundary(share: float, expected: bool) -> None:
    result = summarize_component_zero_ood(
        _decomposition(
            _rows(
                ("return_4h", share),
                ("rv_4h", (1 - share) / 2),
                ("range_ratio_3d", (1 - share) / 2),
            )
        ),
        retained_feature_names=NAMES,
    )
    assert result.single_feature_concentration is expected


@pytest.mark.parametrize(
    ("share", "expected"),
    ((0.69, False), (0.70, True), (0.71, True)),
)
def test_volatility_family_concentration_uses_registry_and_inclusive_boundary(share: float, expected: bool) -> None:
    result = summarize_component_zero_ood(
        _decomposition(_rows(("rv_4h", share), ("range_ratio_3d", 1 - share))),
        retained_feature_names=NAMES,
    )
    assert result.volatility_family_concentration is expected


@pytest.mark.parametrize(("top1_count", "expected"), ((11, False), (12, True), (13, True)))
def test_recurrent_dominance_uses_inclusive_half_boundary(top1_count: int, expected: bool) -> None:
    rows = []
    for index in range(24):
        row = dict.fromkeys(NAMES, 0.0)
        winner = "return_4h" if index < top1_count else f"return_{['12h', '1d', '2d', '3d'][(index-top1_count) % 4]}"
        row[winner] = 2.0
        row["rv_4h"] = 1.0
        rows.append(row)
    result = summarize_component_zero_ood(_decomposition(tuple(rows)), retained_feature_names=NAMES)
    assert result.recurrent_feature_dominance is expected


@pytest.mark.parametrize(
    "decomposition",
    [
        _decomposition(_rows(("rv_4h", 1.0))[:23]),
        _decomposition(_rows(("rv_4h", 1.0)) + _rows(("rv_4h", 1.0))[:1]),
        _decomposition(component_row=OODComponentRow(0, FINGERPRINT, 408, 24, 24 / 408)),
        _decomposition(component_row=OODComponentRow(0, FINGERPRINT, 409, 23, 23 / 409)),
        _decomposition(component_row=OODComponentRow(0, FINGERPRINT, 409, 24, 0.1)),
        _decomposition(sample_fingerprint="b" * 24),
        _decomposition(threshold=1.0),
    ],
)
def test_rejects_noncanonical_component_zero_population(decomposition: FrozenK4Decomposition) -> None:
    with pytest.raises(ValueError):
        summarize_component_zero_ood(decomposition, retained_feature_names=NAMES)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0])
def test_rejects_invalid_contributions_and_distance_reconciliation(bad: float) -> None:
    rows = list(_rows(("rv_4h", 1.0)))
    rows[0]["rv_4h"] = bad
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(tuple(rows)), retained_feature_names=NAMES)

    valid = _decomposition()
    bad_sample = replace(valid.ood_samples[0], squared_mahalanobis=2.0)
    with pytest.raises(ValueError):
        summarize_component_zero_ood(replace(valid, ood_samples=(bad_sample,) + valid.ood_samples[1:]), retained_feature_names=NAMES)


@pytest.mark.parametrize(
    "names",
    [NAMES[:-1], NAMES + (NAMES[0],), tuple(reversed(NAMES)), ("not_registered",)],
)
def test_rejects_missing_duplicate_unknown_or_nonregistry_order_retained_names(names: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(), retained_feature_names=names)


def test_rejects_missing_or_extra_sample_contribution_keys_and_wrong_registry_contract() -> None:
    missing = list(_rows(("rv_4h", 1.0)))
    del missing[0][NAMES[-1]]
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(tuple(missing)), retained_feature_names=NAMES)
    extra = list(_rows(("rv_4h", 1.0)))
    extra[0]["extra"] = 0.0
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(tuple(extra)), retained_feature_names=NAMES)
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(), retained_feature_names=NAMES, registry=tuple(reversed(REGISTRY)))
    with pytest.raises(ValueError):
        summarize_component_zero_ood(_decomposition(), retained_feature_names=NAMES, registry_schema_version="wrong")
    with pytest.raises(ValueError):
        summarize_component_zero_ood(object(), retained_feature_names=NAMES)


def test_registry_hash_is_canonical_stable_and_sensitive_only_to_admitted_payload() -> None:
    first = _registry_sha256(NAMES, REGISTRY, THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)
    second = _registry_sha256(NAMES, REGISTRY, THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)
    assert first == second
    assert first != _registry_sha256(NAMES, tuple(reversed(REGISTRY)), THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)
    mutations = (
        replace(REGISTRY[0], name=REGISTRY[0].name + "_changed"),
        replace(REGISTRY[0], family=REGISTRY[0].family + "_changed"),
        replace(REGISTRY[0], aggregation_minutes=REGISTRY[0].aggregation_minutes + 1),
        replace(REGISTRY[0], lookback_minutes=REGISTRY[0].lookback_minutes + 1),
        replace(REGISTRY[0], formula=REGISTRY[0].formula + " changed"),
    )
    assert all(
        first
        != _registry_sha256(NAMES, (changed,) + REGISTRY[1:], THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)
        for changed in mutations
    )
    unrelated = MappingProxyType({"feature_schema_sha256": "ignored"})
    assert unrelated["feature_schema_sha256"] == "ignored"
    assert first == _registry_sha256(NAMES, REGISTRY, THREE_DAY_CHART_FEATURE_SCHEMA_VERSION)


def test_result_and_nested_contracts_are_frozen_and_validate_invariants() -> None:
    result = summarize_component_zero_ood(_decomposition(), retained_feature_names=NAMES)
    assert isinstance(result.feature_rows, tuple)
    assert isinstance(result.family_rows, tuple)
    assert isinstance(result.feature_rows[0], OODFeatureSummaryRow)
    assert isinstance(result.family_rows[0], OODFamilySummaryRow)
    with pytest.raises(FrozenInstanceError):
        result.ood_sample_count = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.feature_rows[0].rank = 2  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.family_rows[0].family_name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.feature_rows[0] = result.feature_rows[1]  # type: ignore[index]
    with pytest.raises(TypeError):
        result.family_rows[0] = result.family_rows[1]  # type: ignore[index]
    with pytest.raises(ValueError):
        replace(result.feature_rows[0], contribution_ratio=2.0)
    with pytest.raises(ValueError):
        replace(result.feature_rows[0], contribution_mean=2.0)
    with pytest.raises(ValueError):
        replace(result.family_rows[0], family_feature_names=("x", "x"))
    with pytest.raises(ValueError):
        replace(result, analysis_scope="wrong")
    with pytest.raises(ValueError):
        replace(result, top_five_features=("missing",))
    duplicated_family = replace(
        result.family_rows[1],
        family_feature_names=result.family_rows[0].family_feature_names,
    )
    with pytest.raises(ValueError):
        replace(result, family_rows=(result.family_rows[0], duplicated_family) + result.family_rows[2:])
