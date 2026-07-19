from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from types import MappingProxyType
from typing import Mapping

from src.domain.regime.temporal import is_regime_boundary


CHART_FEATURE_SCHEMA_VERSION = "btc-chart-regime-ohclv-v1"


@dataclass(frozen=True)
class ChartFeatureSpec:
    name: str
    family: str
    aggregation_minutes: int
    lookback_minutes: int
    formula: str
    null_policy: str = "reject_window"
    clipping_policy: str = "train_quantile_0.005_0.995"
    scale_invariant: bool = True


def _spec(
    name: str,
    family: str,
    aggregation_minutes: int,
    lookback_minutes: int,
    formula: str,
) -> ChartFeatureSpec:
    return ChartFeatureSpec(name, family, aggregation_minutes, lookback_minutes, formula)


CHART_FEATURE_REGISTRY_V1 = (
    _spec("return_4h", "returns", 15, 240, "last close / first bar open - 1 over 4h"),
    _spec("return_12h", "returns", 15, 720, "last close / first bar open - 1 over 12h"),
    _spec("return_1d", "returns", 15, 1440, "last close / first bar open - 1 over 1d"),
    _spec("return_3d", "returns", 15, 4320, "last close / first bar open - 1 over 3d"),
    _spec("return_7d", "returns", 15, 10080, "last close / first bar open - 1 over 7d"),
    _spec("rv_4h", "volatility", 15, 240, "population stddev of 15m interval log returns including first bar open-to-close over 4h"),
    _spec("rv_1d", "volatility", 15, 1440, "population stddev of 15m interval log returns including first bar open-to-close over 1d"),
    _spec("rv_7d", "volatility", 15, 10080, "population stddev of 15m interval log returns including first bar open-to-close over 7d"),
    _spec("rv_ratio_1d_7d", "volatility", 15, 10080, "1d realized volatility / 7d realized volatility"),
    _spec("atr_ratio_1d", "range", 60, 1440, "mean 1h true range over 1d / last close"),
    _spec("atr_ratio_7d", "range", 60, 10080, "mean 1h true range over 7d / last close"),
    _spec("range_ratio_7d", "range", 60, 10080, "7d high-low range / last close"),
    _spec("close_location_7d", "range", 60, 10080, "(last close - 7d low) / 7d high-low range"),
    _spec("directional_efficiency_1d", "path", 15, 1440, "absolute net movement on path [first bar open, closes] / sum absolute movements over 1d"),
    _spec("directional_efficiency_7d", "path", 15, 10080, "absolute net movement on path [first bar open, closes] / sum absolute movements over 7d"),
    _spec("sign_change_rate_1d", "path", 15, 1440, "opposite-sign original adjacent nonzero 15m interval-return pairs / eligible pairs over 1d; includes first bar open-to-close return"),
    _spec("sign_change_rate_7d", "path", 15, 10080, "opposite-sign original adjacent nonzero 15m interval-return pairs / eligible pairs over 7d; includes first bar open-to-close return"),
    _spec("return_autocorr_1d", "path", 15, 1440, "lag-one population correlation of 15m interval returns including first bar open-to-close over 1d"),
    _spec("return_autocorr_7d", "path", 15, 10080, "lag-one population correlation of 15m interval returns including first bar open-to-close over 7d"),
    _spec("max_drawdown_7d", "path", 15, 10080, "minimum price / running peak price - 1 on path [first bar open, closes] over 7d"),
    _spec("max_runup_7d", "path", 15, 10080, "maximum price / running trough price - 1 on path [first bar open, closes] over 7d"),
    _spec("breakout_rate_7d", "breakout", 60, 10080, "fraction of 1h closes outside the preceding 24h high-low range"),
    _spec("mean_body_ratio_7d", "candle_shape", 60, 10080, "mean absolute 1h candle body / candle range; zero-range hour contributes 0"),
    _spec("mean_upper_wick_ratio_7d", "candle_shape", 60, 10080, "mean 1h upper wick / candle range; zero-range hour contributes 0"),
    _spec("mean_lower_wick_ratio_7d", "candle_shape", 60, 10080, "mean 1h lower wick / candle range; zero-range hour contributes 0"),
    _spec("volume_cv_7d", "volume", 60, 10080, "population stddev of 1h volume / mean 1h volume"),
    _spec("top_decile_volume_share_7d", "volume", 60, 10080, "largest ceiling ten percent 1h volumes / total 1h volume"),
    _spec("volume_ratio_1d_7d", "volume", 60, 10080, "mean last-1d 1h volume / mean 7d 1h volume"),
)


@dataclass(frozen=True)
class ChartFeatureVector:
    symbol: str
    anchor_at: datetime
    window_start_at: datetime
    schema_version: str
    values: Mapping[str, float]

    def __post_init__(self) -> None:
        if self.schema_version != CHART_FEATURE_SCHEMA_VERSION:
            raise ValueError("feature vector schema version is incompatible")
        if not is_regime_boundary(self.anchor_at):
            raise ValueError("anchor must be a four-hour UTC boundary")
        if self.window_start_at.tzinfo is not timezone.utc:
            raise ValueError("window start must be UTC")
        if self.window_start_at != self.anchor_at - timedelta(days=7):
            raise ValueError("window start must be seven days before anchor")
        expected_names = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)
        if tuple(self.values) != expected_names:
            raise ValueError("feature vector does not match registry order")
        copied_values = dict(self.values)
        if any(not math.isfinite(value) for value in copied_values.values()):
            raise ValueError("feature vector values must be finite")
        object.__setattr__(self, "values", MappingProxyType(copied_values))


__all__ = [
    "CHART_FEATURE_REGISTRY_V1",
    "CHART_FEATURE_SCHEMA_VERSION",
    "ChartFeatureSpec",
    "ChartFeatureVector",
]
