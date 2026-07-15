from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType
from typing import Mapping

from src.domain.regime.chart_features import ChartFeatureSpec


THREE_DAY_CHART_FEATURE_SCHEMA_VERSION = "btc-chart-regime-ohlcv-3d-v1"


def _spec(
    name: str,
    family: str,
    aggregation_minutes: int,
    lookback_minutes: int,
    formula: str,
) -> ChartFeatureSpec:
    return ChartFeatureSpec(name, family, aggregation_minutes, lookback_minutes, formula)


THREE_DAY_CHART_FEATURE_REGISTRY_V1 = (
    _spec("return_4h", "returns", 15, 240, "last close / first bar open - 1 over 4h"),
    _spec("return_12h", "returns", 15, 720, "last close / first bar open - 1 over 12h"),
    _spec("return_1d", "returns", 15, 1440, "last close / first bar open - 1 over 1d"),
    _spec("return_2d", "returns", 15, 2880, "last close / first bar open - 1 over 2d"),
    _spec("return_3d", "returns", 15, 4320, "last close / first bar open - 1 over 3d"),
    _spec("rv_4h", "volatility", 15, 240, "population stddev of 15m interval log returns including first bar open-to-close over 4h"),
    _spec("rv_1d", "volatility", 15, 1440, "population stddev of 15m interval log returns including first bar open-to-close over 1d"),
    _spec("rv_3d", "volatility", 15, 4320, "population stddev of 15m interval log returns including first bar open-to-close over 3d"),
    _spec("rv_ratio_1d_3d", "volatility", 15, 4320, "1d realized volatility / 3d realized volatility"),
    _spec("atr_ratio_1d", "range", 60, 1440, "mean 1h true range over 1d / last close"),
    _spec("atr_ratio_3d", "range", 60, 4320, "mean 1h true range over 3d / last close"),
    _spec("range_ratio_3d", "range", 60, 4320, "3d high-low range / last close"),
    _spec("close_location_3d", "range", 60, 4320, "(last close - 3d low) / 3d high-low range"),
    _spec("directional_efficiency_1d", "path", 15, 1440, "absolute net movement on path [first bar open, closes] / sum absolute movements over 1d"),
    _spec("directional_efficiency_3d", "path", 15, 4320, "absolute net movement on path [first bar open, closes] / sum absolute movements over 3d"),
    _spec("sign_change_rate_1d", "reversal", 15, 1440, "opposite-sign original adjacent nonzero 15m interval-return pairs / eligible pairs over 1d; includes first bar open-to-close return"),
    _spec("sign_change_rate_3d", "reversal", 15, 4320, "opposite-sign original adjacent nonzero 15m interval-return pairs / eligible pairs over 3d; includes first bar open-to-close return"),
    _spec("return_autocorr_1d", "reversal", 15, 1440, "lag-one population correlation of 15m interval returns including first bar open-to-close over 1d"),
    _spec("return_autocorr_3d", "reversal", 15, 4320, "lag-one population correlation of 15m interval returns including first bar open-to-close over 3d"),
    _spec("max_drawdown_3d", "excursion", 15, 4320, "minimum price / running peak price - 1 on path [first bar open, closes] over 3d"),
    _spec("max_runup_3d", "excursion", 15, 4320, "maximum price / running trough price - 1 on path [first bar open, closes] over 3d"),
    _spec("breakout_rate_3d", "excursion", 15, 4320, "fraction of 15m closes outside the preceding 24h high-low range"),
    _spec("mean_body_ratio_3d", "candle_shape", 60, 4320, "mean absolute 1h candle body / candle range; zero-range hour contributes 0"),
    _spec("mean_upper_wick_ratio_3d", "candle_shape", 60, 4320, "mean 1h upper wick / candle range; zero-range hour contributes 0"),
    _spec("mean_lower_wick_ratio_3d", "candle_shape", 60, 4320, "mean 1h lower wick / candle range; zero-range hour contributes 0"),
    _spec("volume_cv_3d", "volume", 60, 4320, "population stddev of 1h volume / mean 1h volume"),
    _spec("top_decile_volume_share_3d", "volume", 60, 4320, "largest ceiling ten percent 1h volumes / total 1h volume"),
    _spec("volume_ratio_1d_3d", "volume", 60, 4320, "mean last-1d 1h volume / mean 3d 1h volume"),
)


@dataclass(frozen=True)
class ThreeDayChartFeatureVector:
    symbol: str
    anchor_at: datetime
    window_start_at: datetime
    values: Mapping[str, float]
    schema_version: str = field(
        default=THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        init=False,
    )

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip() or self.symbol != self.symbol.upper():
            raise ValueError("feature vector symbol must be nonblank canonical uppercase")
        if not _is_midnight_utc(self.anchor_at):
            raise ValueError("anchor must be canonical midnight UTC")
        if self.window_start_at.tzinfo is not timezone.utc:
            raise ValueError("window start must be UTC")
        if self.window_start_at != self.anchor_at - timedelta(days=3):
            raise ValueError("window start must be three days before anchor")

        expected_names = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
        if tuple(self.values) != expected_names:
            raise ValueError("feature vector does not match registry order")
        copied_values = dict(self.values)
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in copied_values.values()
        ):
            raise ValueError("feature vector values must be finite numeric values")
        object.__setattr__(self, "values", MappingProxyType(copied_values))


def _is_midnight_utc(value: datetime) -> bool:
    return (
        value.tzinfo is timezone.utc
        and value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
    )


__all__ = [
    "THREE_DAY_CHART_FEATURE_REGISTRY_V1",
    "THREE_DAY_CHART_FEATURE_SCHEMA_VERSION",
    "ThreeDayChartFeatureVector",
]
