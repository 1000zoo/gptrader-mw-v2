from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import statistics

import pytest

from src.domain.market.candle import Candle
from src.domain.market.symbol import Symbol
from src.domain.market.timeframe import Timeframe
from src.domain.regime.three_day_chart_features import THREE_DAY_CHART_FEATURE_REGISTRY_V1


ANCHOR = datetime(2026, 4, 6, tzinfo=timezone.utc)
START = ANCHOR - timedelta(days=3)
BTCUSDT = Symbol("BTC", "USDT")
ONE_MINUTE = Timeframe(1, "m")


def _minute_candles(*, count=4320, start_at=START, flat=False):
    candles = []
    previous = Decimal("100")
    for index in range(count):
        opened_at = start_at + timedelta(minutes=index)
        if flat:
            opened = closed = Decimal("100")
        else:
            opened = previous
            closed = opened + (Decimal("0.03") if index % 5 else Decimal("-0.02"))
            previous = closed
        padding = Decimal("0") if flat else Decimal("0.04")
        candles.append(
            Candle(
                symbol=BTCUSDT,
                timeframe=ONE_MINUTE,
                opened_at=opened_at,
                closed_at=opened_at + timedelta(minutes=1),
                open_price=opened,
                high_price=max(opened, closed) + padding,
                low_price=min(opened, closed) - padding,
                close_price=closed,
                volume=Decimal(10 + index % 17),
            )
        )
    return tuple(candles)


def _bars(*, minutes, count):
    bars = []
    previous = Decimal("100")
    for index in range(count):
        opened_at = START + timedelta(minutes=minutes * index)
        opened = previous
        movement = (
            Decimal("1.5")
            if minutes == 15 and index == 200
            else Decimal(str(((index * 17) % 13 - 6) / 100))
        )
        closed = opened + movement
        previous = closed
        upper = Decimal(str(0.08 + (index % 5) / 100))
        lower = Decimal(str(0.07 + (index % 7) / 100))
        bars.append(
            Candle(
                symbol=BTCUSDT,
                timeframe=Timeframe(minutes, "m"),
                opened_at=opened_at,
                closed_at=opened_at + timedelta(minutes=minutes),
                open_price=opened,
                high_price=max(opened, closed) + upper,
                low_price=min(opened, closed) - lower,
                close_price=closed,
                volume=Decimal(100 + (index * 19) % 53),
            )
        )
    return tuple(bars)


def _reference_values(bars_15m, bars_1h):
    def path(bars):
        return [float(bars[0].open_price), *[float(bar.close_price) for bar in bars]]

    def simple_returns(prices):
        return [right / left - 1 for left, right in zip(prices, prices[1:])]

    def log_returns(prices):
        return [math.log(right / left) for left, right in zip(prices, prices[1:])]

    def efficiency(prices):
        return abs(prices[-1] - prices[0]) / sum(
            abs(right - left) for left, right in zip(prices, prices[1:])
        )

    def sign_change(returns):
        pairs = [(left, right) for left, right in zip(returns, returns[1:]) if left and right]
        return sum(left * right < 0 for left, right in pairs) / len(pairs)

    def autocorr(returns):
        left, right = returns[:-1], returns[1:]
        left_mean, right_mean = statistics.fmean(left), statistics.fmean(right)
        covariance = statistics.fmean(
            (x - left_mean) * (y - right_mean) for x, y in zip(left, right)
        )
        left_variance = statistics.fmean((x - left_mean) ** 2 for x in left)
        right_variance = statistics.fmean((y - right_mean) ** 2 for y in right)
        return covariance / math.sqrt(left_variance * right_variance)

    def atr(bars, previous_close):
        true_ranges = []
        for bar in bars:
            high, low = float(bar.high_price), float(bar.low_price)
            true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
            previous_close = float(bar.close_price)
        return statistics.fmean(true_ranges) / float(bars[-1].close_price)

    path_4h, path_12h = path(bars_15m[-16:]), path(bars_15m[-48:])
    path_1d, path_2d = path(bars_15m[-96:]), path(bars_15m[-192:])
    path_3d = path(bars_15m)
    returns_1d, returns_3d = simple_returns(path_1d), simple_returns(path_3d)
    rv_4h = statistics.pstdev(log_returns(path_4h))
    rv_1d = statistics.pstdev(log_returns(path_1d))
    rv_3d = statistics.pstdev(log_returns(path_3d))
    highs = [float(bar.high_price) for bar in bars_1h]
    lows = [float(bar.low_price) for bar in bars_1h]
    volumes = [float(bar.volume) for bar in bars_1h]
    last_close = float(bars_1h[-1].close_price)
    ratios = []
    for bar in bars_1h:
        opened, high = float(bar.open_price), float(bar.high_price)
        low, closed = float(bar.low_price), float(bar.close_price)
        width = high - low
        ratios.append((0.0, 0.0, 0.0) if width == 0 else (
            abs(closed - opened) / width,
            (high - max(opened, closed)) / width,
            (min(opened, closed) - low) / width,
        ))
    peak, drawdown = path_3d[0], 0.0
    trough, runup = path_3d[0], 0.0
    for price in path_3d:
        peak = max(peak, price)
        drawdown = min(drawdown, price / peak - 1)
        trough = min(trough, price)
        runup = max(runup, price / trough - 1)
    breakouts = 0
    for index in range(96, len(bars_15m)):
        preceding = bars_15m[index - 96:index]
        close = float(bars_15m[index].close_price)
        breakouts += close > max(float(bar.high_price) for bar in preceding) or close < min(
            float(bar.low_price) for bar in preceding
        )
    return {
        "return_4h": path_4h[-1] / path_4h[0] - 1,
        "return_12h": path_12h[-1] / path_12h[0] - 1,
        "return_1d": path_1d[-1] / path_1d[0] - 1,
        "return_2d": path_2d[-1] / path_2d[0] - 1,
        "return_3d": path_3d[-1] / path_3d[0] - 1,
        "rv_4h": rv_4h,
        "rv_1d": rv_1d,
        "rv_3d": rv_3d,
        "rv_ratio_1d_3d": rv_1d / rv_3d,
        "atr_ratio_1d": atr(bars_1h[-24:], float(bars_1h[-25].close_price)),
        "atr_ratio_3d": atr(bars_1h, float(bars_1h[0].open_price)),
        "range_ratio_3d": (max(highs) - min(lows)) / last_close,
        "close_location_3d": (last_close - min(lows)) / (max(highs) - min(lows)),
        "directional_efficiency_1d": efficiency(path_1d),
        "directional_efficiency_3d": efficiency(path_3d),
        "sign_change_rate_1d": sign_change(returns_1d),
        "sign_change_rate_3d": sign_change(returns_3d),
        "return_autocorr_1d": autocorr(returns_1d),
        "return_autocorr_3d": autocorr(returns_3d),
        "max_drawdown_3d": drawdown,
        "max_runup_3d": runup,
        "breakout_rate_3d": breakouts / (len(bars_15m) - 96),
        "mean_body_ratio_3d": statistics.fmean(item[0] for item in ratios),
        "mean_upper_wick_ratio_3d": statistics.fmean(item[1] for item in ratios),
        "mean_lower_wick_ratio_3d": statistics.fmean(item[2] for item in ratios),
        "volume_cv_3d": statistics.pstdev(volumes) / statistics.fmean(volumes),
        "top_decile_volume_share_3d": sum(sorted(volumes, reverse=True)[:math.ceil(len(volumes) * 0.1)]) / sum(volumes),
        "volume_ratio_1d_3d": statistics.fmean(volumes[-24:]) / statistics.fmean(volumes),
    }


def test_extractor_uses_closed_half_open_three_day_window():
    from src.application.services.three_day_chart_feature_extractor import (
        extract_three_day_chart_feature_vector,
    )

    all_candles = _minute_candles(count=4321)
    expected = extract_three_day_chart_feature_vector(all_candles[:4320], ANCHOR)
    actual = extract_three_day_chart_feature_vector(all_candles, ANCHOR)

    assert actual == expected
    assert actual.window_start_at == START
    assert actual.anchor_at == ANCHOR


def test_registry_values_match_independent_formula_reference():
    from src.application.services.three_day_chart_feature_extractor import (
        calculate_three_day_registry_values,
    )

    bars_15m, bars_1h = _bars(minutes=15, count=288), _bars(minutes=60, count=72)
    actual = calculate_three_day_registry_values(bars_15m, bars_1h)
    expected = _reference_values(bars_15m, bars_1h)

    assert tuple(actual) == tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    assert expected["breakout_rate_3d"] > 0
    assert actual == pytest.approx(expected, rel=1e-12, abs=1e-15)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda values: values[:-1], "complete three-day"),
        (lambda values: values[:100] + (values[99],) + values[101:], "complete three-day"),
        (lambda values: values[:100] + (replace(values[100], symbol=Symbol("ETH", "USDT")),) + values[101:], "same symbol"),
        (lambda values: values[:100] + (replace(values[100], opened_at=values[100].opened_at + timedelta(minutes=1), closed_at=values[100].closed_at + timedelta(minutes=1)),) + values[101:], "complete three-day"),
        (lambda values: values[:100] + (replace(values[100], opened_at=values[100].opened_at.astimezone(timezone(timedelta(hours=9))), closed_at=values[100].closed_at.astimezone(timezone(timedelta(hours=9)))),) + values[101:], "complete three-day"),
        (lambda values: values[:100] + (replace(values[100], opened_at=values[100].opened_at.replace(tzinfo=None), closed_at=values[100].closed_at.replace(tzinfo=None)),) + values[101:], "complete three-day"),
    ],
)
def test_extractor_rejects_invalid_minute_history(mutation, message):
    from src.application.services.three_day_chart_feature_extractor import extract_three_day_chart_feature_vector

    with pytest.raises(ValueError, match=message):
        extract_three_day_chart_feature_vector(mutation(_minute_candles()), ANCHOR)


def test_extractor_requires_midnight_canonical_utc_anchor():
    from src.application.services.three_day_chart_feature_extractor import extract_three_day_chart_feature_vector

    with pytest.raises(ValueError, match="midnight UTC"):
        extract_three_day_chart_feature_vector(_minute_candles(), ANCHOR + timedelta(hours=1))
    with pytest.raises(ValueError, match="midnight UTC"):
        extract_three_day_chart_feature_vector(_minute_candles(), ANCHOR.replace(tzinfo=None))


def test_registry_calculation_rejects_misaligned_aggregated_history():
    from src.application.services.three_day_chart_feature_extractor import (
        calculate_three_day_registry_values,
    )

    bars_15m, bars_1h = _bars(minutes=15, count=288), _bars(minutes=60, count=72)
    shifted = replace(
        bars_15m[1],
        opened_at=bars_15m[1].opened_at + timedelta(minutes=1),
        closed_at=bars_15m[1].closed_at + timedelta(minutes=1),
    )
    with pytest.raises(ValueError, match="three-day aggregated history"):
        calculate_three_day_registry_values(
            bars_15m[:1] + (shifted,) + bars_15m[2:], bars_1h
        )


def test_extractor_rejects_nonfinite_ohlcv():
    from src.application.services.three_day_chart_feature_extractor import extract_three_day_chart_feature_vector

    candles = _minute_candles()
    huge = Decimal("1e10000")
    invalid = replace(candles[0], open_price=huge, high_price=huge, close_price=huge)
    with pytest.raises(ValueError, match="finite"):
        extract_three_day_chart_feature_vector((invalid,) + candles[1:], ANCHOR)


def test_zero_range_maintenance_hour_contributes_zero_shape_ratios():
    from src.application.services.chart_feature_extractor import aggregate_closed_candles
    from src.application.services.three_day_chart_feature_extractor import extract_three_day_chart_feature_vector

    candles = _minute_candles()
    offset = 2 * 24 * 60
    carried = candles[offset].open_price
    flat_hour = tuple(replace(candle, open_price=carried, high_price=carried, low_price=carried, close_price=carried, volume=Decimal("0")) for candle in candles[offset:offset + 60])
    changed = candles[:offset] + flat_hour + candles[offset + 60:]
    vector = extract_three_day_chart_feature_vector(changed, ANCHOR)
    bars = aggregate_closed_candles(changed, minutes=60)
    ratios = [
        (Decimal("0"), Decimal("0"), Decimal("0")) if bar.high_price == bar.low_price else (
            abs(bar.close_price - bar.open_price) / (bar.high_price - bar.low_price),
            (bar.high_price - max(bar.open_price, bar.close_price)) / (bar.high_price - bar.low_price),
            (min(bar.open_price, bar.close_price) - bar.low_price) / (bar.high_price - bar.low_price),
        ) for bar in bars
    ]
    assert vector.values["mean_body_ratio_3d"] == pytest.approx(float(sum(item[0] for item in ratios) / len(ratios)))
    assert vector.values["mean_upper_wick_ratio_3d"] == pytest.approx(float(sum(item[1] for item in ratios) / len(ratios)))
    assert vector.values["mean_lower_wick_ratio_3d"] == pytest.approx(float(sum(item[2] for item in ratios) / len(ratios)))


def test_extractor_rejects_wholly_flat_window():
    from src.application.services.three_day_chart_feature_extractor import extract_three_day_chart_feature_vector

    with pytest.raises(ValueError, match="zero denominator"):
        extract_three_day_chart_feature_vector(_minute_candles(flat=True), ANCHOR)


def test_application_services_exports_three_day_api():
    from src.application.services import (
        calculate_three_day_registry_values,
        extract_three_day_chart_feature_vector,
    )

    assert callable(calculate_three_day_registry_values)
    assert callable(extract_three_day_chart_feature_vector)
