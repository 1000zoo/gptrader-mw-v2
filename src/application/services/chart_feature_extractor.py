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
    if not source:
        raise ValueError("incomplete aggregation bucket")
    _validate_one_minute_source(source, aggregation_minutes=minutes)
    if len(source) % minutes:
        raise ValueError("incomplete aggregation bucket")

    bars = []
    for offset in range(0, len(source), minutes):
        bucket = source[offset : offset + minutes]
        if bucket[-1].closed_at - bucket[0].opened_at != timedelta(minutes=minutes):
            raise ValueError("incomplete aggregation bucket")
        bars.append(
            Candle(
                symbol=bucket[0].symbol,
                timeframe=Timeframe(minutes, "m"),
                opened_at=bucket[0].opened_at,
                closed_at=bucket[-1].closed_at,
                open_price=bucket[0].open_price,
                high_price=max(item.high_price for item in bucket),
                low_price=min(item.low_price for item in bucket),
                close_price=bucket[-1].close_price,
                volume=sum((item.volume for item in bucket), ZERO),
            )
        )
    return tuple(bars)


def _validate_one_minute_source(
    source: tuple[Candle, ...],
    *,
    aggregation_minutes: int,
) -> None:
    one_minute = timedelta(minutes=1)
    first = source[0]
    minute_of_day = first.opened_at.hour * 60 + first.opened_at.minute
    valid = (
        first.opened_at.tzinfo is timezone.utc
        and first.opened_at.second == 0
        and first.opened_at.microsecond == 0
        and minute_of_day % aggregation_minutes == 0
        and all(candle.symbol == first.symbol for candle in source)
        and all(candle.timeframe == Timeframe(1, "m") for candle in source)
        and all(candle.opened_at.tzinfo is timezone.utc for candle in source)
        and all(candle.closed_at.tzinfo is timezone.utc for candle in source)
        and all(candle.closed_at - candle.opened_at == one_minute for candle in source)
        and all(
            current.opened_at == previous.closed_at
            for previous, current in zip(source, source[1:])
        )
    )
    if not valid:
        raise ValueError("aggregation requires aligned contiguous one-minute UTC candles")


def extract_chart_feature_vector(
    candles: Sequence[Candle] | Iterable[Candle],
    anchor_at: datetime,
) -> ChartFeatureVector:
    window_start_at, window_end_at = feature_window(anchor_at)
    window = tuple(
        candle
        for candle in candles
        if window_start_at <= candle.opened_at < window_end_at
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
    if any(candle.symbol != window[0].symbol for candle in window):
        raise ValueError("history candles must use the same symbol")
    expected_opens = tuple(start_at + timedelta(minutes=index) for index in range(MINUTES_PER_WEEK))
    if tuple(candle.opened_at for candle in window) != expected_opens:
        raise ValueError("complete seven-day one-minute history is required")
    expected_closes = tuple(value + timedelta(minutes=1) for value in expected_opens)
    if tuple(candle.closed_at for candle in window) != expected_closes:
        raise ValueError("complete seven-day one-minute history is required")
    if any(candle.timeframe != Timeframe(1, "m") for candle in window):
        raise ValueError("complete seven-day one-minute history is required")
    if any(candle.opened_at.tzinfo is not timezone.utc or candle.closed_at.tzinfo is not timezone.utc for candle in window):
        raise ValueError("complete seven-day one-minute history is required")
    if window[0].opened_at != start_at or window[-1].closed_at != end_at:
        raise ValueError("complete seven-day one-minute history is required")
    if any(
        current.opened_at != previous.closed_at
        for previous, current in zip(window, window[1:])
    ):
        raise ValueError("complete seven-day one-minute history is required")
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
    _validate_aggregated_history(bars_15m, bars_1h)
    path_4h = _price_path(bars_15m[-16:])
    path_12h = _price_path(bars_15m[-48:])
    path_1d = _price_path(bars_15m[-96:])
    path_3d = _price_path(bars_15m[-288:])
    path_7d = _price_path(bars_15m)
    returns_1d = _simple_returns(path_1d)
    returns_7d = _simple_returns(path_7d)
    log_returns_4h = _log_returns(path_4h)
    log_returns_1d = _log_returns(path_1d)
    log_returns_7d = _log_returns(path_7d)
    closes_1h = [float(bar.close_price) for bar in bars_1h]
    volumes_1h = [float(bar.volume) for bar in bars_1h]

    rv_1d = _population_stddev(log_returns_1d)
    rv_7d = _population_stddev(log_returns_7d)
    values = {
        "return_4h": _period_return(path_4h),
        "return_12h": _period_return(path_12h),
        "return_1d": _period_return(path_1d),
        "return_3d": _period_return(path_3d),
        "return_7d": _period_return(path_7d),
        "rv_4h": _population_stddev(log_returns_4h),
        "rv_1d": rv_1d,
        "rv_7d": rv_7d,
        "rv_ratio_1d_7d": _divide(rv_1d, rv_7d),
        "atr_ratio_1d": _atr_ratio(
            bars_1h[-24:],
            first_previous_close=float(bars_1h[-25].close_price),
        ),
        "atr_ratio_7d": _atr_ratio(
            bars_1h,
            first_previous_close=float(bars_1h[0].open_price),
        ),
        "range_ratio_7d": _divide(max(float(bar.high_price) for bar in bars_1h) - min(float(bar.low_price) for bar in bars_1h), closes_1h[-1]),
        "close_location_7d": _close_location(bars_1h),
        "directional_efficiency_1d": _directional_efficiency(path_1d),
        "directional_efficiency_7d": _directional_efficiency(path_7d),
        "sign_change_rate_1d": _sign_change_rate(returns_1d),
        "sign_change_rate_7d": _sign_change_rate(returns_7d),
        "return_autocorr_1d": _lag_one_correlation(returns_1d),
        "return_autocorr_7d": _lag_one_correlation(returns_7d),
        "max_drawdown_7d": _max_drawdown(path_7d),
        "max_runup_7d": _max_runup(path_7d),
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


def _validate_aggregated_history(
    bars_15m: tuple[Candle, ...],
    bars_1h: tuple[Candle, ...],
) -> None:
    if len(bars_15m) != 672 or len(bars_1h) != 168:
        raise ValueError("complete aligned seven-day aggregated history is required")
    symbols_15m = {bar.symbol for bar in bars_15m}
    symbols_1h = {bar.symbol for bar in bars_1h}
    if len(symbols_15m) != 1 or len(symbols_1h) != 1 or symbols_15m != symbols_1h:
        raise ValueError("aggregated histories must use the same symbol")
    _validate_aggregated_series(bars_15m, minutes=15)
    _validate_aggregated_series(bars_1h, minutes=60)
    if (
        bars_15m[0].opened_at != bars_1h[0].opened_at
        or bars_15m[-1].closed_at != bars_1h[-1].closed_at
    ):
        raise ValueError("complete aligned seven-day aggregated history is required")


def _validate_aggregated_series(
    bars: tuple[Candle, ...],
    *,
    minutes: int,
) -> None:
    duration = timedelta(minutes=minutes)
    first = bars[0]
    minute_of_day = first.opened_at.hour * 60 + first.opened_at.minute
    valid = (
        first.opened_at.tzinfo is timezone.utc
        and first.opened_at.second == 0
        and first.opened_at.microsecond == 0
        and minute_of_day % minutes == 0
        and all(bar.timeframe == Timeframe(minutes, "m") for bar in bars)
        and all(bar.opened_at.tzinfo is timezone.utc for bar in bars)
        and all(bar.closed_at.tzinfo is timezone.utc for bar in bars)
        and all(bar.closed_at - bar.opened_at == duration for bar in bars)
        and all(
            current.opened_at == previous.closed_at
            for previous, current in zip(bars, bars[1:])
        )
    )
    if not valid:
        raise ValueError("complete aligned seven-day aggregated history is required")


def _price_path(bars: tuple[Candle, ...]) -> list[float]:
    return [float(bars[0].open_price), *(float(bar.close_price) for bar in bars)]


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


def _atr_ratio(
    bars: tuple[Candle, ...],
    *,
    first_previous_close: float,
) -> float:
    true_ranges = []
    previous_close = first_previous_close
    for bar in bars:
        high = float(bar.high_price)
        low = float(bar.low_price)
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = float(bar.close_price)
    return _divide(statistics.fmean(true_ranges), float(bars[-1].close_price))


def _close_location(bars: tuple[Candle, ...]) -> float:
    low = min(float(bar.low_price) for bar in bars)
    high = max(float(bar.high_price) for bar in bars)
    return _divide(float(bars[-1].close_price) - low, high - low)


def _directional_efficiency(closes: list[float]) -> float:
    path_length = sum(abs(current - previous) for previous, current in zip(closes, closes[1:]))
    return _divide(abs(closes[-1] - closes[0]), path_length)


def _sign_change_rate(returns: list[float]) -> float:
    pairs = tuple(
        (left, right)
        for left, right in zip(returns, returns[1:])
        if left != 0 and right != 0
    )
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
    # Binance can publish a complete carried-price maintenance hour with zero
    # volume.  Such a candle has no body or wicks; treating all three shape
    # contributions as zero completes the ratio domain without masking a
    # wholly degenerate seven-day window (other path/volatility gates reject it).
    if width == 0:
        return 0.0, 0.0, 0.0
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
