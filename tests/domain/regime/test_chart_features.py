from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from src.domain.regime.chart_features import (
    CHART_FEATURE_REGISTRY_V1,
    CHART_FEATURE_SCHEMA_VERSION,
    ChartFeatureVector,
)


EXPECTED_NAMES = (
    "return_4h",
    "return_12h",
    "return_1d",
    "return_3d",
    "return_7d",
    "rv_4h",
    "rv_1d",
    "rv_7d",
    "rv_ratio_1d_7d",
    "atr_ratio_1d",
    "atr_ratio_7d",
    "range_ratio_7d",
    "close_location_7d",
    "directional_efficiency_1d",
    "directional_efficiency_7d",
    "sign_change_rate_1d",
    "sign_change_rate_7d",
    "return_autocorr_1d",
    "return_autocorr_7d",
    "max_drawdown_7d",
    "max_runup_7d",
    "breakout_rate_7d",
    "mean_body_ratio_7d",
    "mean_upper_wick_ratio_7d",
    "mean_lower_wick_ratio_7d",
    "volume_cv_7d",
    "top_decile_volume_share_7d",
    "volume_ratio_1d_7d",
)


def test_feature_registry_has_frozen_v1_names_and_metadata():
    assert CHART_FEATURE_SCHEMA_VERSION == "btc-chart-regime-ohclv-v1"
    assert tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1) == EXPECTED_NAMES
    assert len(CHART_FEATURE_REGISTRY_V1) == 28
    assert all(spec.family for spec in CHART_FEATURE_REGISTRY_V1)
    assert all(spec.aggregation_minutes in {15, 60} for spec in CHART_FEATURE_REGISTRY_V1)
    assert all(spec.lookback_minutes in {240, 720, 1440, 4320, 10080} for spec in CHART_FEATURE_REGISTRY_V1)
    assert all(spec.formula for spec in CHART_FEATURE_REGISTRY_V1)
    assert all(spec.null_policy == "reject_window" for spec in CHART_FEATURE_REGISTRY_V1)
    assert all(spec.clipping_policy == "train_quantile_0.005_0.995" for spec in CHART_FEATURE_REGISTRY_V1)
    assert all(spec.scale_invariant for spec in CHART_FEATURE_REGISTRY_V1)


def test_feature_registry_freezes_interval_path_formula_metadata():
    expected_formulas = {
        "return_4h": "last close / first bar open - 1 over 4h",
        "return_12h": "last close / first bar open - 1 over 12h",
        "return_1d": "last close / first bar open - 1 over 1d",
        "return_3d": "last close / first bar open - 1 over 3d",
        "return_7d": "last close / first bar open - 1 over 7d",
        "rv_4h": "population stddev of 15m interval log returns including first bar open-to-close over 4h",
        "rv_1d": "population stddev of 15m interval log returns including first bar open-to-close over 1d",
        "rv_7d": "population stddev of 15m interval log returns including first bar open-to-close over 7d",
        "directional_efficiency_1d": "absolute net movement on path [first bar open, closes] / sum absolute movements over 1d",
        "directional_efficiency_7d": "absolute net movement on path [first bar open, closes] / sum absolute movements over 7d",
        "sign_change_rate_1d": "opposite-sign original adjacent nonzero 15m interval-return pairs / eligible pairs over 1d; includes first bar open-to-close return",
        "sign_change_rate_7d": "opposite-sign original adjacent nonzero 15m interval-return pairs / eligible pairs over 7d; includes first bar open-to-close return",
        "return_autocorr_1d": "lag-one population correlation of 15m interval returns including first bar open-to-close over 1d",
        "return_autocorr_7d": "lag-one population correlation of 15m interval returns including first bar open-to-close over 7d",
        "max_drawdown_7d": "minimum price / running peak price - 1 on path [first bar open, closes] over 7d",
        "max_runup_7d": "maximum price / running trough price - 1 on path [first bar open, closes] over 7d",
    }
    actual_formulas = {spec.name: spec.formula for spec in CHART_FEATURE_REGISTRY_V1}

    assert {name: actual_formulas[name] for name in expected_formulas} == expected_formulas


def test_feature_vector_requires_registry_order_and_freezes_values():
    values = {name: float(index) for index, name in enumerate(EXPECTED_NAMES)}
    vector = ChartFeatureVector(
        symbol="BTCUSDT",
        anchor_at=datetime(2026, 4, 6, tzinfo=timezone.utc),
        window_start_at=datetime(2026, 3, 30, tzinfo=timezone.utc),
        schema_version=CHART_FEATURE_SCHEMA_VERSION,
        values=values,
    )

    values[EXPECTED_NAMES[0]] = 999.0
    assert vector.values[EXPECTED_NAMES[0]] == 0.0
    assert isinstance(vector.values, MappingProxyType)
    with pytest.raises(TypeError):
        vector.values[EXPECTED_NAMES[0]] = 1.0

    wrong_order = dict(reversed(tuple(vector.values.items())))
    with pytest.raises(ValueError, match="registry order"):
        ChartFeatureVector(
            symbol="BTCUSDT",
            anchor_at=vector.anchor_at,
            window_start_at=vector.window_start_at,
            schema_version=CHART_FEATURE_SCHEMA_VERSION,
            values=wrong_order,
        )


def test_feature_vector_rejects_nonfinite_values():
    values = {name: 0.0 for name in EXPECTED_NAMES}
    values["return_4h"] = float("nan")

    with pytest.raises(ValueError, match="finite"):
        ChartFeatureVector(
            symbol="BTCUSDT",
            anchor_at=datetime(2026, 4, 6, tzinfo=timezone.utc),
            window_start_at=datetime(2026, 3, 30, tzinfo=timezone.utc),
            schema_version=CHART_FEATURE_SCHEMA_VERSION,
            values=values,
        )


@pytest.mark.parametrize(
    ("schema_version", "anchor_at", "window_start_at", "message"),
    [
        (
            "other-version",
            datetime(2026, 4, 6, tzinfo=timezone.utc),
            datetime(2026, 3, 30, tzinfo=timezone.utc),
            "schema version",
        ),
        (
            CHART_FEATURE_SCHEMA_VERSION,
            datetime(2026, 4, 6, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 30, 1, tzinfo=timezone.utc),
            "four-hour UTC boundary",
        ),
        (
            CHART_FEATURE_SCHEMA_VERSION,
            datetime(2026, 4, 6, tzinfo=timezone(timedelta(hours=9))),
            datetime(2026, 3, 30, tzinfo=timezone(timedelta(hours=9))),
            "four-hour UTC boundary",
        ),
        (
            CHART_FEATURE_SCHEMA_VERSION,
            datetime(2026, 4, 6, tzinfo=timezone.utc),
            datetime(2026, 3, 30, 9, tzinfo=timezone(timedelta(hours=9))),
            "window start must be UTC",
        ),
        (
            CHART_FEATURE_SCHEMA_VERSION,
            datetime(2026, 4, 6, tzinfo=timezone.utc),
            datetime(2026, 3, 29, tzinfo=timezone.utc),
            "seven days before anchor",
        ),
    ],
)
def test_feature_vector_rejects_incompatible_temporal_contract(
    schema_version,
    anchor_at,
    window_start_at,
    message,
):
    values = {name: 0.0 for name in EXPECTED_NAMES}

    with pytest.raises(ValueError, match=message):
        ChartFeatureVector(
            symbol="BTCUSDT",
            anchor_at=anchor_at,
            window_start_at=window_start_at,
            schema_version=schema_version,
            values=values,
        )
