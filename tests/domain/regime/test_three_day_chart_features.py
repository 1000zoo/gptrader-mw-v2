from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pytest

from src.domain.regime.chart_features import ChartFeatureSpec
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
    ThreeDayChartFeatureVector,
)


EXPECTED_NAMES = (
    "return_4h",
    "return_12h",
    "return_1d",
    "return_2d",
    "return_3d",
    "rv_4h",
    "rv_1d",
    "rv_3d",
    "rv_ratio_1d_3d",
    "atr_ratio_1d",
    "atr_ratio_3d",
    "range_ratio_3d",
    "close_location_3d",
    "directional_efficiency_1d",
    "directional_efficiency_3d",
    "sign_change_rate_1d",
    "sign_change_rate_3d",
    "return_autocorr_1d",
    "return_autocorr_3d",
    "max_drawdown_3d",
    "max_runup_3d",
    "breakout_rate_3d",
    "mean_body_ratio_3d",
    "mean_upper_wick_ratio_3d",
    "mean_lower_wick_ratio_3d",
    "volume_cv_3d",
    "top_decile_volume_share_3d",
    "volume_ratio_1d_3d",
)


def _expected_spec(name, family, aggregation_minutes, lookback_minutes, formula):
    return (
        name,
        family,
        aggregation_minutes,
        lookback_minutes,
        formula,
        "reject_window",
        "train_quantile_0.005_0.995",
        True,
    )


EXPECTED_REGISTRY_SNAPSHOT = (
    _expected_spec("return_4h", "returns", 15, 240, "last close / first bar open - 1 over 4h"),
    _expected_spec("return_12h", "returns", 15, 720, "last close / first bar open - 1 over 12h"),
    _expected_spec("return_1d", "returns", 15, 1440, "last close / first bar open - 1 over 1d"),
    _expected_spec("return_2d", "returns", 15, 2880, "last close / first bar open - 1 over 2d"),
    _expected_spec("return_3d", "returns", 15, 4320, "last close / first bar open - 1 over 3d"),
    _expected_spec("rv_4h", "volatility", 15, 240, "population stddev of 15m interval log returns including first bar open-to-close over 4h"),
    _expected_spec("rv_1d", "volatility", 15, 1440, "population stddev of 15m interval log returns including first bar open-to-close over 1d"),
    _expected_spec("rv_3d", "volatility", 15, 4320, "population stddev of 15m interval log returns including first bar open-to-close over 3d"),
    _expected_spec("rv_ratio_1d_3d", "volatility", 15, 4320, "1d realized volatility / 3d realized volatility"),
    _expected_spec("atr_ratio_1d", "range", 60, 1440, "mean 1h true range over 1d / last close"),
    _expected_spec("atr_ratio_3d", "range", 60, 4320, "mean 1h true range over 3d / last close"),
    _expected_spec("range_ratio_3d", "range", 60, 4320, "3d high-low range / last close"),
    _expected_spec("close_location_3d", "range", 60, 4320, "(last close - 3d low) / 3d high-low range"),
    _expected_spec("directional_efficiency_1d", "path", 15, 1440, "absolute net movement on path [first bar open, closes] / sum absolute movements over 1d"),
    _expected_spec("directional_efficiency_3d", "path", 15, 4320, "absolute net movement on path [first bar open, closes] / sum absolute movements over 3d"),
    _expected_spec("sign_change_rate_1d", "reversal", 15, 1440, "opposite-sign original adjacent nonzero 15m interval-return pairs / eligible pairs over 1d; includes first bar open-to-close return"),
    _expected_spec("sign_change_rate_3d", "reversal", 15, 4320, "opposite-sign original adjacent nonzero 15m interval-return pairs / eligible pairs over 3d; includes first bar open-to-close return"),
    _expected_spec("return_autocorr_1d", "reversal", 15, 1440, "lag-one population correlation of 15m interval returns including first bar open-to-close over 1d"),
    _expected_spec("return_autocorr_3d", "reversal", 15, 4320, "lag-one population correlation of 15m interval returns including first bar open-to-close over 3d"),
    _expected_spec("max_drawdown_3d", "excursion", 15, 4320, "minimum price / running peak price - 1 on path [first bar open, closes] over 3d"),
    _expected_spec("max_runup_3d", "excursion", 15, 4320, "maximum price / running trough price - 1 on path [first bar open, closes] over 3d"),
    _expected_spec("breakout_rate_3d", "structure", 15, 4320, "fraction of 15m closes outside the preceding 24h high-low range"),
    _expected_spec("mean_body_ratio_3d", "structure", 60, 4320, "mean absolute 1h candle body / candle range; zero-range hour contributes 0"),
    _expected_spec("mean_upper_wick_ratio_3d", "structure", 60, 4320, "mean 1h upper wick / candle range; zero-range hour contributes 0"),
    _expected_spec("mean_lower_wick_ratio_3d", "structure", 60, 4320, "mean 1h lower wick / candle range; zero-range hour contributes 0"),
    _expected_spec("volume_cv_3d", "volume", 60, 4320, "population stddev of 1h volume / mean 1h volume"),
    _expected_spec("top_decile_volume_share_3d", "volume", 60, 4320, "largest ceiling ten percent 1h volumes / total 1h volume"),
    _expected_spec("volume_ratio_1d_3d", "volume", 60, 4320, "mean last-1d 1h volume / mean 3d 1h volume"),
)
ANCHOR = datetime(2026, 4, 6, tzinfo=timezone.utc)


def values():
    return {name: float(index) for index, name in enumerate(EXPECTED_NAMES)}


def test_three_day_registry_has_frozen_schema_names_and_family_cap():
    assert THREE_DAY_CHART_FEATURE_SCHEMA_VERSION == "btc-chart-regime-ohlcv-3d-v1"
    assert tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1) == EXPECTED_NAMES
    assert len(THREE_DAY_CHART_FEATURE_REGISTRY_V1) == 28
    assert all(isinstance(spec, ChartFeatureSpec) for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    assert all(spec.aggregation_minutes in {15, 60} for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    assert all(spec.lookback_minutes in {240, 720, 1440, 2880, 4320} for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    assert all(spec.formula for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    family_counts = {
        family: sum(spec.family == family for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
        for family in {spec.family for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
    }
    assert max(family_counts.values()) <= 5


def test_three_day_registry_has_exact_feature_families():
    expected_families = {
        "return_4h": "returns",
        "return_12h": "returns",
        "return_1d": "returns",
        "return_2d": "returns",
        "return_3d": "returns",
        "rv_4h": "volatility",
        "rv_1d": "volatility",
        "rv_3d": "volatility",
        "rv_ratio_1d_3d": "volatility",
        "atr_ratio_1d": "range",
        "atr_ratio_3d": "range",
        "range_ratio_3d": "range",
        "close_location_3d": "range",
        "directional_efficiency_1d": "path",
        "directional_efficiency_3d": "path",
        "sign_change_rate_1d": "reversal",
        "sign_change_rate_3d": "reversal",
        "return_autocorr_1d": "reversal",
        "return_autocorr_3d": "reversal",
        "max_drawdown_3d": "excursion",
        "max_runup_3d": "excursion",
        "breakout_rate_3d": "structure",
        "mean_body_ratio_3d": "structure",
        "mean_upper_wick_ratio_3d": "structure",
        "mean_lower_wick_ratio_3d": "structure",
        "volume_cv_3d": "volume",
        "top_decile_volume_share_3d": "volume",
        "volume_ratio_1d_3d": "volume",
    }

    assert {
        spec.name: spec.family for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1
    } == expected_families


def test_three_day_registry_has_exact_ordered_metadata_snapshot():
    assert tuple(
        (
            spec.name,
            spec.family,
            spec.aggregation_minutes,
            spec.lookback_minutes,
            spec.formula,
            spec.null_policy,
            spec.clipping_policy,
            spec.scale_invariant,
        )
        for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1
    ) == EXPECTED_REGISTRY_SNAPSHOT


def test_three_day_vector_fixes_schema_and_copies_values_immutably():
    original = values()
    vector = ThreeDayChartFeatureVector(
        symbol="BTCUSDT",
        anchor_at=ANCHOR,
        window_start_at=ANCHOR - timedelta(days=3),
        values=original,
    )

    assert vector.schema_version == THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
    original[EXPECTED_NAMES[0]] = 999.0
    assert vector.values[EXPECTED_NAMES[0]] == 0.0
    assert isinstance(vector.values, MappingProxyType)
    with pytest.raises(TypeError):
        vector.values[EXPECTED_NAMES[0]] = 1.0
    with pytest.raises(FrozenInstanceError):
        vector.symbol = "ETHUSDT"


@pytest.mark.parametrize("symbol", ["", " ", " BTCUSDT", "BTCUSDT ", "btcusdt"])
def test_three_day_vector_requires_nonblank_canonical_symbol(symbol):
    with pytest.raises(ValueError, match="symbol"):
        ThreeDayChartFeatureVector(
            symbol=symbol,
            anchor_at=ANCHOR,
            window_start_at=ANCHOR - timedelta(days=3),
            values=values(),
        )


@pytest.mark.parametrize(
    ("anchor_at", "window_start_at", "message"),
    [
        (datetime(2026, 4, 6), datetime(2026, 4, 3), "midnight UTC"),
        (
            datetime(2026, 4, 6, tzinfo=ZoneInfo("Europe/London")),
            datetime(2026, 4, 3, tzinfo=ZoneInfo("Europe/London")),
            "midnight UTC",
        ),
        (
            datetime(2026, 4, 6, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 3, 1, tzinfo=timezone.utc),
            "midnight UTC",
        ),
        (ANCHOR, datetime(2026, 4, 3), "window start must be UTC"),
        (ANCHOR, ANCHOR - timedelta(days=2), "three days before anchor"),
    ],
)
def test_three_day_vector_rejects_invalid_temporal_contract(
    anchor_at, window_start_at, message
):
    with pytest.raises(ValueError, match=message):
        ThreeDayChartFeatureVector(
            symbol="BTCUSDT",
            anchor_at=anchor_at,
            window_start_at=window_start_at,
            values=values(),
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "reordered"])
def test_three_day_vector_requires_exact_registry_keys_in_order(mutation):
    vector_values = values()
    if mutation == "missing":
        vector_values.pop(EXPECTED_NAMES[-1])
    elif mutation == "extra":
        vector_values["unexpected"] = 0.0
    else:
        vector_values = dict(reversed(tuple(vector_values.items())))

    with pytest.raises(ValueError, match="registry order"):
        ThreeDayChartFeatureVector(
            symbol="BTCUSDT",
            anchor_at=ANCHOR,
            window_start_at=ANCHOR - timedelta(days=3),
            values=vector_values,
        )


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_three_day_vector_rejects_nonfinite_values(nonfinite):
    vector_values = values()
    vector_values[EXPECTED_NAMES[0]] = nonfinite

    with pytest.raises(ValueError, match="finite"):
        ThreeDayChartFeatureVector(
            symbol="BTCUSDT",
            anchor_at=ANCHOR,
            window_start_at=ANCHOR - timedelta(days=3),
            values=vector_values,
        )
