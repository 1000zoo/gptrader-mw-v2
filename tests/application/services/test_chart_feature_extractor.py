from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
import statistics

import pytest

from src.application.services.chart_feature_extractor import (
    ChartFeatureExtractor,
    _sign_change_rate,
    aggregate_closed_candles,
    extract_chart_feature_vector,
)
from src.domain.market.candle import Candle
from src.domain.market.symbol import Symbol
from src.domain.market.timeframe import Timeframe


ANCHOR = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)
START = ANCHOR - timedelta(days=7)
BTCUSDT = Symbol("BTC", "USDT")
ONE_MINUTE = Timeframe(1, "m")


def _candles(*, scale=Decimal("1"), flat=False):
    candles = []
    previous_close = Decimal("100")
    for index in range(7 * 24 * 60):
        closed_at = START + timedelta(minutes=index)
        opened_at = closed_at - timedelta(minutes=1)
        if flat:
            open_price = close_price = Decimal("100") * scale
        else:
            open_price = previous_close
            direction = Decimal("0.02") if index % 7 else Decimal("-0.01")
            close_price = open_price + direction
            previous_close = close_price
            open_price *= scale
            close_price *= scale
        padding = Decimal("0.03") * scale
        candles.append(
            Candle(
                symbol=BTCUSDT,
                timeframe=ONE_MINUTE,
                opened_at=opened_at,
                closed_at=closed_at,
                open_price=open_price,
                high_price=max(open_price, close_price) + padding,
                low_price=min(open_price, close_price) - padding,
                close_price=close_price,
                volume=Decimal(10 + index % 13),
            )
        )
    return tuple(candles)


@pytest.fixture(scope="module")
def complete_candles():
    return _candles()


def test_aggregate_closed_candles_uses_complete_ohlcv_buckets():
    source = _candles()[:15]
    bars = aggregate_closed_candles(source, minutes=15)

    assert len(bars) == 1
    assert bars[0].opened_at == START
    assert bars[0].closed_at == START + timedelta(minutes=15)
    assert bars[0].open_price == source[0].open_price
    assert bars[0].close_price == source[-1].close_price
    assert bars[0].high_price == max(candle.high_price for candle in source)
    assert bars[0].low_price == min(candle.low_price for candle in source)
    assert bars[0].volume == sum(candle.volume for candle in source)


def test_aggregate_closed_candles_rejects_incomplete_bucket():
    with pytest.raises(ValueError, match="incomplete aggregation bucket"):
        aggregate_closed_candles(_candles()[:14], minutes=15)


def test_extractor_excludes_anchor_and_future_candles(complete_candles):
    expected = extract_chart_feature_vector(complete_candles, ANCHOR)
    dramatic = Candle(
        symbol=BTCUSDT,
        timeframe=ONE_MINUTE,
        opened_at=ANCHOR - timedelta(minutes=1),
        closed_at=ANCHOR,
        open_price=Decimal("100"),
        high_price=Decimal("1000000"),
        low_price=Decimal("1"),
        close_price=Decimal("900000"),
        volume=Decimal("999999999"),
    )

    actual = extract_chart_feature_vector(complete_candles + (dramatic,), ANCHOR)

    assert actual == expected
    assert actual.window_start_at == START
    assert tuple(actual.values) == tuple(expected.values)


def test_extractor_service_exposes_the_application_contract(complete_candles):
    assert ChartFeatureExtractor().extract(complete_candles, ANCHOR) == extract_chart_feature_vector(
        complete_candles, ANCHOR
    )


def test_extractor_features_are_price_scale_invariant(complete_candles):
    baseline = extract_chart_feature_vector(complete_candles, ANCHOR)
    scaled = extract_chart_feature_vector(_candles(scale=Decimal("10")), ANCHOR)

    assert scaled.values == pytest.approx(baseline.values, rel=1e-12, abs=1e-12)


def test_extractor_calculates_targeted_return_and_shape_formulas(complete_candles):
    vector = extract_chart_feature_vector(complete_candles, ANCHOR)
    bars_15m = aggregate_closed_candles(complete_candles, minutes=15)
    bars_1h = aggregate_closed_candles(complete_candles, minutes=60)
    recent_4h = bars_15m[-16:]
    expected_return = float(recent_4h[-1].close_price / recent_4h[0].open_price - 1)
    ranges = [bar.high_price - bar.low_price for bar in bars_1h]
    expected_body_ratio = sum(
        abs(bar.close_price - bar.open_price) / width
        for bar, width in zip(bars_1h, ranges)
    ) / len(bars_1h)

    assert vector.values["return_4h"] == pytest.approx(expected_return)
    assert vector.values["mean_body_ratio_7d"] == pytest.approx(float(expected_body_ratio))
    assert all(math.isfinite(value) for value in vector.values.values())


def test_period_features_cover_every_interval_in_the_named_lookback(complete_candles):
    first_recent_index = len(complete_candles) - 24 * 60
    first_recent = complete_candles[first_recent_index]
    changed_open = first_recent.close_price / Decimal("2")
    changed = replace(
        first_recent,
        open_price=changed_open,
        low_price=min(first_recent.low_price, changed_open),
    )
    candles = (
        complete_candles[:first_recent_index]
        + (changed,)
        + complete_candles[first_recent_index + 1 :]
    )

    vector = extract_chart_feature_vector(candles, ANCHOR)
    recent = aggregate_closed_candles(candles, minutes=15)[-96:]
    price_path = [float(recent[0].open_price), *(float(bar.close_price) for bar in recent)]
    log_returns = [math.log(current / previous) for previous, current in zip(price_path, price_path[1:])]
    simple_returns = [current / previous - 1 for previous, current in zip(price_path, price_path[1:])]
    movements = [current - previous for previous, current in zip(price_path, price_path[1:])]
    eligible_pairs = [
        (left, right)
        for left, right in zip(simple_returns, simple_returns[1:])
        if left != 0 and right != 0
    ]
    left = simple_returns[:-1]
    right = simple_returns[1:]
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    covariance = statistics.fmean((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_variance = statistics.fmean((x - left_mean) ** 2 for x in left)
    right_variance = statistics.fmean((y - right_mean) ** 2 for y in right)

    assert len(log_returns) == 96
    assert vector.values["return_1d"] == pytest.approx(price_path[-1] / price_path[0] - 1)
    assert vector.values["rv_1d"] == pytest.approx(statistics.pstdev(log_returns))
    assert vector.values["directional_efficiency_1d"] == pytest.approx(
        abs(price_path[-1] - price_path[0]) / sum(abs(value) for value in movements)
    )
    assert vector.values["sign_change_rate_1d"] == pytest.approx(
        sum(first * second < 0 for first, second in eligible_pairs) / len(eligible_pairs)
    )
    assert vector.values["return_autocorr_1d"] == pytest.approx(
        covariance / math.sqrt(left_variance * right_variance)
    )


def test_one_day_atr_uses_close_before_the_one_day_window(complete_candles):
    first_recent_index = len(complete_candles) - 24 * 60
    gap = Decimal("50")
    shifted = tuple(
        replace(
            candle,
            open_price=candle.open_price + gap,
            high_price=candle.high_price + gap,
            low_price=candle.low_price + gap,
            close_price=candle.close_price + gap,
        )
        for candle in complete_candles[first_recent_index:]
    )
    candles = complete_candles[:first_recent_index] + shifted

    vector = extract_chart_feature_vector(candles, ANCHOR)
    bars = aggregate_closed_candles(candles, minutes=60)
    recent = bars[-24:]
    previous_close = float(bars[-25].close_price)
    true_ranges = []
    for bar in recent:
        high = float(bar.high_price)
        low = float(bar.low_price)
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = float(bar.close_price)
    expected = statistics.fmean(true_ranges) / float(recent[-1].close_price)
    wrong_first_reference = max(
        float(recent[0].high_price - recent[0].low_price),
        abs(float(recent[0].high_price - recent[0].open_price)),
        abs(float(recent[0].low_price - recent[0].open_price)),
    )

    assert true_ranges[0] != pytest.approx(wrong_first_reference)
    assert vector.values["atr_ratio_1d"] == pytest.approx(expected)


def test_zero_returns_break_sign_change_adjacency():
    with pytest.raises(ValueError, match="zero denominator"):
        _sign_change_rate([0.1, 0.0, -0.2])

    assert _sign_change_rate([0.1, 0.0, -0.2, -0.3]) == 0.0


@pytest.mark.parametrize(
    ("candles", "message"),
    [
        (lambda items: items[:-1], "complete seven-day one-minute history"),
        (lambda items: items[:100] + (items[99],) + items[101:], "complete seven-day one-minute history"),
        (
            lambda items: items[:500]
            + (Candle(
                symbol=Symbol("ETH", "USDT"),
                timeframe=ONE_MINUTE,
                opened_at=items[500].opened_at,
                closed_at=items[500].closed_at,
                open_price=items[500].open_price,
                high_price=items[500].high_price,
                low_price=items[500].low_price,
                close_price=items[500].close_price,
                volume=items[500].volume,
            ),)
            + items[501:],
            "same symbol",
        ),
    ],
)
def test_extractor_rejects_invalid_history(complete_candles, candles, message):
    with pytest.raises(ValueError, match=message):
        extract_chart_feature_vector(candles(complete_candles), ANCHOR)


def test_extractor_requires_canonical_utc_four_hour_anchor(complete_candles):
    with pytest.raises(ValueError, match="four-hour UTC boundary"):
        extract_chart_feature_vector(complete_candles, ANCHOR.replace(tzinfo=None))


def test_extractor_rejects_zero_denominators():
    with pytest.raises(ValueError, match="zero denominator"):
        extract_chart_feature_vector(_candles(flat=True), ANCHOR)


def test_extractor_rejects_nonfinite_numeric_input(complete_candles):
    original = complete_candles[0]
    huge = Decimal("1e10000")
    invalid = Candle(
        symbol=original.symbol,
        timeframe=original.timeframe,
        opened_at=original.opened_at,
        closed_at=original.closed_at,
        open_price=huge,
        high_price=huge,
        low_price=huge,
        close_price=huge,
        volume=original.volume,
    )

    with pytest.raises(ValueError, match="finite"):
        extract_chart_feature_vector((invalid,) + complete_candles[1:], ANCHOR)
