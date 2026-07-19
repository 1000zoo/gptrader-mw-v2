from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.application.services.verified_market_timeline import (
    VerifiedDailyMarketSlice,
    VerifiedPhaseMarketTimeline,
    market_snapshot_hash,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe


def _market(start: datetime, minutes: int, *, price: str = "100") -> MarketSnapshot:
    value = Decimal(price)
    return MarketSnapshot(tuple(
        Candle(
            symbol=Symbol("BTC", "USDT"), timeframe=Timeframe(1, "m"),
            opened_at=start + timedelta(minutes=index),
            closed_at=start + timedelta(minutes=index + 1),
            open_price=value, high_price=value + 1, low_price=value - 1,
            close_price=value, volume=Decimal("1"),
        )
        for index in range(minutes)
    ))


def test_verified_timeline_factory_binds_source_index_and_exact_daily_slice() -> None:
    start = datetime(2025, 7, 1, tzinfo=timezone.utc)
    market = _market(start, 4 * 24 * 60)
    timeline = VerifiedPhaseMarketTimeline.from_market(market)

    daily = timeline.daily_slice(start + timedelta(days=3), warmup_minutes=1442)
    verified = daily.verify(
        outcome_start_at=start + timedelta(days=3),
        minimum_context_start_at=start + timedelta(days=3, minutes=-1442),
    )

    assert timeline.market_data_hash == market_snapshot_hash(market)
    assert verified is daily.market
    assert len(verified.candles) == 2882
    assert daily.slice_hash == market_snapshot_hash(verified)


def test_verified_market_types_reject_direct_construction() -> None:
    with pytest.raises(TypeError):
        VerifiedPhaseMarketTimeline()
    with pytest.raises(TypeError):
        VerifiedDailyMarketSlice()


def test_verified_timeline_factory_rejects_malformed_phase_gap() -> None:
    start = datetime(2025, 7, 1, tzinfo=timezone.utc)
    complete = _market(start, 10)
    malformed = MarketSnapshot(complete.candles[:4] + complete.candles[5:])

    with pytest.raises(ValueError, match="gap|overlap"):
        VerifiedPhaseMarketTimeline.from_market(malformed)


def test_verified_timeline_rejects_public_market_tuple_replacement_without_changing_hash() -> None:
    start = datetime(2025, 7, 1, tzinfo=timezone.utc)
    timeline = VerifiedPhaseMarketTimeline.from_market(_market(start, 4 * 24 * 60))
    frozen_hash = timeline.market_data_hash
    replacement = _market(start, 4 * 24 * 60, price="999")

    object.__setattr__(timeline.market, "candles", replacement.candles)

    with pytest.raises(ValueError, match="source|tuple|proof|verified"):
        timeline.daily_slice(start + timedelta(days=3), warmup_minutes=60)
    assert timeline.market_data_hash == frozen_hash


@pytest.mark.parametrize("forgery", ("private_tuple", "index", "proof"))
def test_verified_timeline_rejects_replaced_private_binding_index_or_proof(forgery) -> None:
    start = datetime(2025, 7, 1, tzinfo=timezone.utc)
    timeline = VerifiedPhaseMarketTimeline.from_market(_market(start, 4 * 24 * 60))
    if forgery == "private_tuple":
        object.__setattr__(timeline, "_source_candles", tuple(list(timeline._source_candles)))
    elif forgery == "index":
        object.__setattr__(timeline, "opened_times", tuple(list(timeline.opened_times)))
    else:
        object.__setattr__(timeline, "_proof", timeline._proof + ("forged",))

    with pytest.raises(ValueError, match="source|tuple|proof|verified"):
        timeline.daily_slice(start + timedelta(days=3), warmup_minutes=60)


def test_verified_timeline_detects_nested_candle_value_mutation_in_bounded_slice() -> None:
    start = datetime(2025, 7, 1, tzinfo=timezone.utc)
    timeline = VerifiedPhaseMarketTimeline.from_market(_market(start, 4 * 24 * 60))
    target = timeline.market.candles[-30]
    object.__setattr__(target, "close_price", Decimal("100.5"))

    with pytest.raises(ValueError, match="signature|source|slice|verified"):
        timeline.daily_slice(start + timedelta(days=3), warmup_minutes=60)


def test_verified_daily_slice_rejects_replaced_public_candle_tuple() -> None:
    start = datetime(2025, 7, 1, tzinfo=timezone.utc)
    timeline = VerifiedPhaseMarketTimeline.from_market(_market(start, 4 * 24 * 60))
    daily = timeline.daily_slice(start + timedelta(days=3), warmup_minutes=60)
    object.__setattr__(daily.market, "candles", tuple(list(daily.market.candles)))

    with pytest.raises(ValueError, match="source|tuple|proof|verified"):
        daily.verify(
            outcome_start_at=start + timedelta(days=3),
            minimum_context_start_at=start + timedelta(days=3, minutes=-60),
        )


@pytest.mark.parametrize("forgery", ("source_hash", "prices", "bounds", "slice_hash"))
def test_verified_daily_slice_rejects_forged_source_prices_hash_or_bounds(forgery) -> None:
    start = datetime(2025, 7, 1, tzinfo=timezone.utc)
    timeline = VerifiedPhaseMarketTimeline.from_market(_market(start, 4 * 24 * 60))
    daily = timeline.daily_slice(start + timedelta(days=3), warmup_minutes=60)
    if forgery == "source_hash":
        object.__setattr__(timeline, "market_data_hash", "0" * 64)
    elif forgery == "prices":
        changed = _market(daily.context_start_at, len(daily.market.candles), price="101")
        object.__setattr__(daily, "market", changed)
    elif forgery == "bounds":
        object.__setattr__(daily, "outcome_start_at", daily.outcome_start_at + timedelta(minutes=1))
    else:
        object.__setattr__(daily, "slice_hash", "0" * 64)

    with pytest.raises(ValueError, match="verified|hash|slice|bound|source"):
        daily.verify(
            outcome_start_at=start + timedelta(days=3),
            minimum_context_start_at=start + timedelta(days=3, minutes=-60),
        )
