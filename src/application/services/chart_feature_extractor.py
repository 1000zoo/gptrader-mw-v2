from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import statistics

from src.domain.market.candle import Candle
from src.domain.market.timeframe import Timeframe
from src.domain.regime.chart_features import (
    CHART_FEATURE_REGISTRY_V1,
    CHART_FEATURE_SCHEMA_VERSION,
    ChartFeatureVector,
)
from src.domain.regime.temporal import feature_window


MINUTES_PER_WEEK = 7 * 24 * 60
ZERO = Decimal("0")


class ChartFeatureExtractor:
    def extract(
        self,
        candles: Sequence[Candle] | Iterable[Candle],
        anchor_at: datetime,
    ) -> ChartFeatureVector:
        return extract_chart_feature_vector(candles, anchor_at)


def aggregate_closed_candles(
    candles: Sequence[Candle] | Iterable[Candle],
    *,
    minutes: int,
) -> tuple[Candle, ...]:
    if minutes <= 0:
        raise ValueError("aggregation minutes must be positive")
    source = tuple(candles)
    if not source or len(source) % minutes:
        raise ValueError("incomplete aggregation bucket")

    bars = []
    interval = timedelta(minutes=1)
    for offset in range(0, len(source), minutes):
        bucket = source[offset : offset + minutes]
        expected_closes = tuple(bucket[0].closed_at + interval * index for index in range(minutes))
        if tuple(item.closed_at for item in bucket) != expected_closes:
            raise ValueError("incomplete aggregation bucket")
        symbol = bucket[0].symbol
        if any(item.symbol != symbol for item in bucket):
            raise ValueError("aggregation candles must use the same symbol")
        bars.append(
            Candle(
                symbol=symbol,
                timeframe=Timeframe(minutes, "m"),
                opened_at=bucket[0].closed_at,
                closed_at=bucket[0].closed_at + timedelta(minutes=minutes),
                open_price=bucket[0].open_price,
                high_price=max(item.high_price for item in bucket),
                low_price=min(item.low_price for item in bucket),
                close_price=bucket[-1].close_price,
                volume=sum((item.volume for item in bucket), ZERO),
            )
        )
    return tuple(bars)


def extract_chart_feature_vector(
    candles: Sequence[Candle] | Iterable[Candle],
    anchor_at: datetime,
) -> ChartFeatureVector:
    window_start_at, window_end_at = feature_window(anchor_at)
    window = tuple(
        candle
        for candle in candles
        if window_start_at <= candle.closed_at < window_end_at
    )
    _validate_window(window, window_start_at, window_end_at)
    bars_15m = aggregate_closed_candles(window, minutes=15)
    bars_1h = aggregate_closed_candles(window, minutes=60)
    values = calculate_registry_values(bars_15m, bars_1h)
    return ChartFeatureVector(
        symbol=window[0].symbol.pair,
        anchor_at=anchor_at,
        window_start_at=window_start_at,
        schema_version=CHART_FEATURE_SCHEMA_VERSION,
        values=values,
    )


def _validate_window(
    window: tuple[Candle, ...],
    start_at: datetime,
    end_at: datetime,
) -> None:
    if len(window) != MINUTES_PER_WEEK:
        raise ValueError("complete seven-day one-minute history is required")
    expected_closes = tuple(start_at + timedelta(minutes=index) for index in range(MINUTES_PER_WEEK))
    if tuple(candle.closed_at for candle in window) != expected_closes:
        raise ValueError("complete seven-day one-minute history is required")
    expected_opens = tuple(value - timedelta(minutes=1) for value in expected_closes)
    if tuple(candle.opened_at for candle in window) != expected_opens:
        raise ValueError("complete seven-day one-minute history is required")
    if any(candle.timeframe != Timeframe(1, "m") for candle in window):
        raise ValueError("complete seven-day one-minute history is required")
    if any(candle.opened_at.tzinfo is not timezone.utc or candle.closed_at.tzinfo is not timezone.utc for candle in window):
        raise ValueError("complete seven-day one-minute history is required")
    if any(candle.symbol != window[0].symbol for candle in window):
        raise ValueError("history candles must use the same symbol")
    if expected_closes[-1] >= end_at:
        raise ValueError("selected history must not reach the anchor")
    for candle in window:
        numeric_values = (
            candle.open_price,
            candle.high_price,
            candle.low_price,
            candle.close_price,
            candle.volume,
        )
        if any(not math.isfinite(float(value)) for value in numeric_values):
            raise ValueError("OHLCV values must be finite")


def calculate_registry_values(
    bars_15m: tuple[Candle, ...],
    bars_1h: tuple[Candle, ...],
) -> dict[str, float]:
    closes_15m = [float(bar.close_price) for bar in bars_15m]
    returns_15m = _simple_returns(closes_15m)
    log_returns_15m = _log_returns(closes_15m)
    closes_1h = [float(bar.close_price) for bar in bars_1h]
    volumes_1h = [float(bar.volume) for bar in bars_1h]

    rv_1d = _population_stddev(log_returns_15m[-95:])
    rv_7d = _population_stddev(log_returns_15m)
    values = {
        "return_4h": _period_return(closes_15m[-16:]),
        "return_12h": _period_return(closes_15m[-48:]),
        "return_1d": _period_return(closes_15m[-96:]),
        "return_3d": _period_return(closes_15m[-288:]),
        "return_7d": _period_return(closes_15m),
        "rv_4h": _population_stddev(log_returns_15m[-15:]),
        "rv_1d": rv_1d,
        "rv_7d": rv_7d,
        "rv_ratio_1d_7d": _divide(rv_1d, rv_7d),
        "atr_ratio_1d": _atr_ratio(bars_1h[-24:]),
        "atr_ratio_7d": _atr_ratio(bars_1h),
        "range_ratio_7d": _divide(max(float(bar.high_price) for bar in bars_1h) - min(float(bar.low_price) for bar in bars_1h), closes_1h[-1]),
        "close_location_7d": _close_location(bars_1h),
        "directional_efficiency_1d": _directional_efficiency(closes_15m[-96:]),
        "directional_efficiency_7d": _directional_efficiency(closes_15m),
        "sign_change_rate_1d": _sign_change_rate(returns_15m[-95:]),
        "sign_change_rate_7d": _sign_change_rate(returns_15m),
        "return_autocorr_1d": _lag_one_correlation(returns_15m[-95:]),
        "return_autocorr_7d": _lag_one_correlation(returns_15m),
        "max_drawdown_7d": _max_drawdown(closes_15m),
        "max_runup_7d": _max_runup(closes_15m),
        "breakout_rate_7d": _breakout_rate(bars_1h),
        "mean_body_ratio_7d": statistics.fmean(_candle_ratios(bar)[0] for bar in bars_1h),
        "mean_upper_wick_ratio_7d": statistics.fmean(_candle_ratios(bar)[1] for bar in bars_1h),
        "mean_lower_wick_ratio_7d": statistics.fmean(_candle_ratios(bar)[2] for bar in bars_1h),
        "volume_cv_7d": _divide(_population_stddev(volumes_1h), statistics.fmean(volumes_1h)),
        "top_decile_volume_share_7d": _top_decile_share(volumes_1h),
        "volume_ratio_1d_7d": _divide(statistics.fmean(volumes_1h[-24:]), statistics.fmean(volumes_1h)),
    }
    if tuple(values) != tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1):
        raise RuntimeError("calculated features do not match registry")
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError("calculated features must be finite")
    return values


def _divide(numerator: float, denominator: float) -> float:
    if denominator == 0:
        raise ValueError("feature has a zero denominator")
    result = numerator / denominator
    if not math.isfinite(result):
        raise ValueError("calculated features must be finite")
    return result


def _period_return(closes: list[float]) -> float:
    return _divide(closes[-1], closes[0]) - 1.0


def _simple_returns(closes: list[float]) -> list[float]:
    return [_divide(current, previous) - 1.0 for previous, current in zip(closes, closes[1:])]


def _log_returns(closes: list[float]) -> list[float]:
    if any(close <= 0 for close in closes):
        raise ValueError("log return requires positive prices")
    return [math.log(current / previous) for previous, current in zip(closes, closes[1:])]


def _population_stddev(values: list[float]) -> float:
    if not values:
        raise ValueError("feature has a zero denominator")
    return statistics.pstdev(values)


def _atr_ratio(bars: tuple[Candle, ...]) -> float:
    true_ranges = []
    for index, bar in enumerate(bars):
        high = float(bar.high_price)
        low = float(bar.low_price)
        previous_close = float(bars[index - 1].close_price) if index else float(bar.open_price)
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    return _divide(statistics.fmean(true_ranges), float(bars[-1].close_price))


def _close_location(bars: tuple[Candle, ...]) -> float:
    low = min(float(bar.low_price) for bar in bars)
    high = max(float(bar.high_price) for bar in bars)
    return _divide(float(bars[-1].close_price) - low, high - low)


def _directional_efficiency(closes: list[float]) -> float:
    path_length = sum(abs(current - previous) for previous, current in zip(closes, closes[1:]))
    return _divide(abs(closes[-1] - closes[0]), path_length)


def _sign_change_rate(returns: list[float]) -> float:
    nonzero = [value for value in returns if value != 0]
    pairs = tuple(zip(nonzero, nonzero[1:]))
    return _divide(sum(left * right < 0 for left, right in pairs), len(pairs))


def _lag_one_correlation(returns: list[float]) -> float:
    left = returns[:-1]
    right = returns[1:]
    if not left:
        raise ValueError("feature has a zero denominator")
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    covariance = statistics.fmean((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_variance = statistics.fmean((x - left_mean) ** 2 for x in left)
    right_variance = statistics.fmean((y - right_mean) ** 2 for y in right)
    return _divide(covariance, math.sqrt(left_variance * right_variance))


def _max_drawdown(closes: list[float]) -> float:
    peak = closes[0]
    worst = 0.0
    for close in closes:
        peak = max(peak, close)
        worst = min(worst, _divide(close, peak) - 1.0)
    return worst


def _max_runup(closes: list[float]) -> float:
    trough = closes[0]
    best = 0.0
    for close in closes:
        trough = min(trough, close)
        best = max(best, _divide(close, trough) - 1.0)
    return best


def _breakout_rate(bars: tuple[Candle, ...]) -> float:
    breakouts = 0
    observations = bars[24:]
    for index, bar in enumerate(observations, start=24):
        preceding = bars[index - 24 : index]
        prior_high = max(float(item.high_price) for item in preceding)
        prior_low = min(float(item.low_price) for item in preceding)
        close = float(bar.close_price)
        breakouts += close > prior_high or close < prior_low
    return _divide(breakouts, len(observations))


def _candle_ratios(bar: Candle) -> tuple[float, float, float]:
    high = float(bar.high_price)
    low = float(bar.low_price)
    opened = float(bar.open_price)
    closed = float(bar.close_price)
    width = high - low
    return (
        _divide(abs(closed - opened), width),
        _divide(high - max(opened, closed), width),
        _divide(min(opened, closed) - low, width),
    )


def _top_decile_share(volumes: list[float]) -> float:
    count = math.ceil(len(volumes) * 0.1)
    return _divide(sum(sorted(volumes, reverse=True)[:count]), sum(volumes))


__all__ = [
    "ChartFeatureExtractor",
    "aggregate_closed_candles",
    "calculate_registry_values",
    "extract_chart_feature_vector",
]
