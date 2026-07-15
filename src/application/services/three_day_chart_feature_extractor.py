from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
import math
import statistics

from src.application.services.chart_feature_extractor import (
    _atr_ratio,
    _candle_ratios,
    _close_location,
    _directional_efficiency,
    _divide,
    _lag_one_correlation,
    _log_returns,
    _max_drawdown,
    _max_runup,
    _period_return,
    _population_stddev,
    _price_path,
    _sign_change_rate,
    _simple_returns,
    _top_decile_share,
    _validate_aggregated_series,
    aggregate_closed_candles,
)
from src.domain.market.candle import Candle
from src.domain.market.timeframe import Timeframe
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    ThreeDayChartFeatureVector,
)


MINUTES_PER_THREE_DAYS = 3 * 24 * 60


def extract_three_day_chart_feature_vector(
    candles: Sequence[Candle] | Iterable[Candle],
    anchor_at: datetime,
) -> ThreeDayChartFeatureVector:
    if not _is_midnight_utc(anchor_at):
        raise ValueError("anchor must be canonical midnight UTC")
    window_start_at = anchor_at - timedelta(days=3)
    try:
        window = tuple(
            candle
            for candle in candles
            if window_start_at <= candle.opened_at < anchor_at
        )
    except TypeError as error:
        raise ValueError("complete three-day one-minute history is required") from error
    _validate_window(window, window_start_at, anchor_at)
    bars_15m = aggregate_closed_candles(window, minutes=15)
    bars_1h = aggregate_closed_candles(window, minutes=60)
    return ThreeDayChartFeatureVector(
        symbol=window[0].symbol.pair,
        anchor_at=anchor_at,
        window_start_at=window_start_at,
        values=calculate_three_day_registry_values(bars_15m, bars_1h),
    )


def calculate_three_day_registry_values(
    bars_15m: tuple[Candle, ...],
    bars_1h: tuple[Candle, ...],
) -> dict[str, float]:
    _validate_aggregated_history(bars_15m, bars_1h)
    path_4h = _price_path(bars_15m[-16:])
    path_12h = _price_path(bars_15m[-48:])
    path_1d = _price_path(bars_15m[-96:])
    path_2d = _price_path(bars_15m[-192:])
    path_3d = _price_path(bars_15m)
    returns_1d = _simple_returns(path_1d)
    returns_3d = _simple_returns(path_3d)
    rv_1d = _population_stddev(_log_returns(path_1d))
    rv_3d = _population_stddev(_log_returns(path_3d))
    closes_1h = [float(bar.close_price) for bar in bars_1h]
    volumes_1h = [float(bar.volume) for bar in bars_1h]

    values = {
        "return_4h": _period_return(path_4h),
        "return_12h": _period_return(path_12h),
        "return_1d": _period_return(path_1d),
        "return_2d": _period_return(path_2d),
        "return_3d": _period_return(path_3d),
        "rv_4h": _population_stddev(_log_returns(path_4h)),
        "rv_1d": rv_1d,
        "rv_3d": rv_3d,
        "rv_ratio_1d_3d": _divide(rv_1d, rv_3d),
        "atr_ratio_1d": _atr_ratio(
            bars_1h[-24:], first_previous_close=float(bars_1h[-25].close_price)
        ),
        "atr_ratio_3d": _atr_ratio(
            bars_1h, first_previous_close=float(bars_1h[0].open_price)
        ),
        "range_ratio_3d": _divide(
            max(float(bar.high_price) for bar in bars_1h)
            - min(float(bar.low_price) for bar in bars_1h),
            closes_1h[-1],
        ),
        "close_location_3d": _close_location(bars_1h),
        "directional_efficiency_1d": _directional_efficiency(path_1d),
        "directional_efficiency_3d": _directional_efficiency(path_3d),
        "sign_change_rate_1d": _sign_change_rate(returns_1d),
        "sign_change_rate_3d": _sign_change_rate(returns_3d),
        "return_autocorr_1d": _lag_one_correlation(returns_1d),
        "return_autocorr_3d": _lag_one_correlation(returns_3d),
        "max_drawdown_3d": _max_drawdown(path_3d),
        "max_runup_3d": _max_runup(path_3d),
        "breakout_rate_3d": _breakout_rate_15m(bars_15m),
        "mean_body_ratio_3d": statistics.fmean(
            _candle_ratios(bar)[0] for bar in bars_1h
        ),
        "mean_upper_wick_ratio_3d": statistics.fmean(
            _candle_ratios(bar)[1] for bar in bars_1h
        ),
        "mean_lower_wick_ratio_3d": statistics.fmean(
            _candle_ratios(bar)[2] for bar in bars_1h
        ),
        "volume_cv_3d": _divide(
            _population_stddev(volumes_1h), statistics.fmean(volumes_1h)
        ),
        "top_decile_volume_share_3d": _top_decile_share(volumes_1h),
        "volume_ratio_1d_3d": _divide(
            statistics.fmean(volumes_1h[-24:]), statistics.fmean(volumes_1h)
        ),
    }
    if tuple(values) != tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1):
        raise RuntimeError("calculated features do not match three-day registry")
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError("calculated features must be finite")
    return values


def _validate_window(
    window: tuple[Candle, ...], start_at: datetime, end_at: datetime
) -> None:
    if len(window) != MINUTES_PER_THREE_DAYS:
        raise ValueError("complete three-day one-minute history is required")
    if any(candle.symbol != window[0].symbol for candle in window):
        raise ValueError("history candles must use the same symbol")
    expected_opens = tuple(
        start_at + timedelta(minutes=index) for index in range(MINUTES_PER_THREE_DAYS)
    )
    expected_closes = tuple(value + timedelta(minutes=1) for value in expected_opens)
    valid = (
        tuple(candle.opened_at for candle in window) == expected_opens
        and tuple(candle.closed_at for candle in window) == expected_closes
        and all(candle.timeframe == Timeframe(1, "m") for candle in window)
        and all(
            candle.opened_at.tzinfo is timezone.utc
            and candle.closed_at.tzinfo is timezone.utc
            for candle in window
        )
        and window[0].opened_at == start_at
        and window[-1].closed_at == end_at
    )
    if not valid:
        raise ValueError("complete three-day one-minute history is required")
    for candle in window:
        if any(
            not math.isfinite(float(value))
            for value in (
                candle.open_price,
                candle.high_price,
                candle.low_price,
                candle.close_price,
                candle.volume,
            )
        ):
            raise ValueError("OHLCV values must be finite")


def _validate_aggregated_history(
    bars_15m: tuple[Candle, ...], bars_1h: tuple[Candle, ...]
) -> None:
    if len(bars_15m) != 288 or len(bars_1h) != 72:
        raise ValueError("complete aligned three-day aggregated history is required")
    symbols_15m = {bar.symbol for bar in bars_15m}
    symbols_1h = {bar.symbol for bar in bars_1h}
    if len(symbols_15m) != 1 or len(symbols_1h) != 1 or symbols_15m != symbols_1h:
        raise ValueError("aggregated histories must use the same symbol")
    try:
        _validate_aggregated_series(bars_15m, minutes=15)
        _validate_aggregated_series(bars_1h, minutes=60)
    except ValueError as error:
        raise ValueError(
            "complete aligned three-day aggregated history is required"
        ) from error
    if (
        bars_15m[0].opened_at != bars_1h[0].opened_at
        or bars_15m[-1].closed_at != bars_1h[-1].closed_at
    ):
        raise ValueError("complete aligned three-day aggregated history is required")
    for bar in (*bars_15m, *bars_1h):
        if any(
            not math.isfinite(float(value))
            for value in (
                bar.open_price,
                bar.high_price,
                bar.low_price,
                bar.close_price,
                bar.volume,
            )
        ):
            raise ValueError("OHLCV values must be finite")


def _breakout_rate_15m(bars: tuple[Candle, ...]) -> float:
    breakouts = 0
    for index in range(96, len(bars)):
        preceding = bars[index - 96 : index]
        close = float(bars[index].close_price)
        prior_high = max(float(bar.high_price) for bar in preceding)
        prior_low = min(float(bar.low_price) for bar in preceding)
        breakouts += close > prior_high or close < prior_low
    return _divide(breakouts, len(bars) - 96)


def _is_midnight_utc(value: datetime) -> bool:
    return (
        value.tzinfo is timezone.utc
        and value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
    )


__all__ = [
    "calculate_three_day_registry_values",
    "extract_three_day_chart_feature_vector",
]
