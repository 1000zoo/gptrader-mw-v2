from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.domain.market import Symbol, Timeframe
from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue
from src.infrastructure.market_feature import (
    EmptyMarketFeatureProvider,
    InMemoryMarketFeatureProvider,
)


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")
T = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def make_value(name: str, source: str, available_at: datetime) -> MarketFeatureValue:
    return MarketFeatureValue(
        name=name,
        value=Decimal("1"),
        source=source,
        observed_at=available_at,
        available_at=available_at,
    )


def make_set(
    measured_at: datetime,
    values: tuple[MarketFeatureValue, ...] = (),
    unavailable_sources: tuple[str, ...] = (),
) -> MarketFeatureSet:
    return MarketFeatureSet(
        SYMBOL,
        TIMEFRAME,
        measured_at,
        values,
        unavailable_sources,
    )


def test_empty_provider_returns_requested_alignment_and_unavailable_sources():
    provider = EmptyMarketFeatureProvider(unavailable_sources=("open_interest",))

    result = provider.load_features(SYMBOL, TIMEFRAME, T)

    assert result == MarketFeatureSet(
        SYMBOL,
        TIMEFRAME,
        T,
        (),
        ("open_interest",),
    )


def test_in_memory_provider_uses_exact_cutoff_and_excludes_future_rows():
    exact = make_set(T, (make_value("flow", "agg_trades", T),))
    future_time = T + timedelta(microseconds=1)
    future = make_set(
        future_time,
        (make_value("future_flow", "agg_trades", T),),
    )
    provider = InMemoryMarketFeatureProvider((future, exact))

    result = provider.load_features(SYMBOL, TIMEFRAME, T)

    assert result.measured_at == T
    assert result.values == exact.values
    assert result.get("future_flow") is None


def test_in_memory_provider_merges_configured_sources_into_eligible_row():
    row = make_set(
        T,
        (make_value("flow", "agg_trades", T),),
        ("funding",),
    )
    provider = InMemoryMarketFeatureProvider(
        (row,),
        unavailable_sources=("open_interest",),
    )

    result = provider.load_features(SYMBOL, TIMEFRAME, T)

    assert result.values == row.values
    assert result.unavailable_sources == ("open_interest", "funding")


def test_in_memory_provider_aligns_latest_past_row_to_requested_time():
    measured_at = T - timedelta(minutes=1)
    row = make_set(
        measured_at,
        (make_value("flow", "agg_trades", measured_at),),
    )
    provider = InMemoryMarketFeatureProvider((row,))

    result = provider.load_features(SYMBOL, TIMEFRAME, T)

    assert result.measured_at == T
    assert result.values == row.values


def test_in_memory_provider_rejects_duplicate_timestamps():
    row = make_set(T)

    with pytest.raises(ValueError, match="duplicate.*timestamp"):
        InMemoryMarketFeatureProvider((row, row))


def test_in_memory_provider_rejects_configured_unavailable_value_source():
    row = make_set(T, (make_value("flow", "agg_trades", T),))

    with pytest.raises(
        ValueError,
        match="configured unavailable source.*agg_trades.*row value",
    ):
        InMemoryMarketFeatureProvider(
            (row,),
            unavailable_sources=("agg_trades",),
        )


def test_in_memory_provider_deduplicates_matching_unavailable_declarations():
    row = make_set(T, unavailable_sources=("funding",))
    provider = InMemoryMarketFeatureProvider(
        (row,),
        unavailable_sources=("funding",),
    )

    result = provider.load_features(SYMBOL, TIMEFRAME, T)

    assert result.unavailable_sources == ("funding",)


def test_in_memory_provider_applies_source_specific_staleness():
    measured_at = T - timedelta(minutes=2)
    row = make_set(
        measured_at,
        (
            make_value("flow", "agg_trades", measured_at),
            make_value("funding_rate", "funding", measured_at),
        ),
    )
    provider = InMemoryMarketFeatureProvider(
        (row,),
        max_staleness_by_source={"funding": timedelta(minutes=1)},
    )

    result = provider.load_features(SYMBOL, TIMEFRAME, T)

    assert tuple(value.name for value in result.values) == ("flow",)
    assert result.unavailable_sources == ("funding",)


def test_in_memory_provider_keeps_source_available_when_it_has_a_fresh_value():
    measured_at = T - timedelta(seconds=30)
    row = make_set(
        measured_at,
        (
            make_value("old_flow", "agg_trades", T - timedelta(minutes=2)),
            make_value("new_flow", "agg_trades", measured_at),
        ),
    )
    provider = InMemoryMarketFeatureProvider(
        (row,),
        max_staleness_by_source={"agg_trades": timedelta(minutes=1)},
    )

    result = provider.load_features(SYMBOL, TIMEFRAME, T)

    assert tuple(value.name for value in result.values) == ("new_flow",)
    assert result.unavailable_sources == ()


def test_in_memory_provider_applies_overall_staleness():
    measured_at = T - timedelta(minutes=2)
    row = make_set(
        measured_at,
        (make_value("flow", "agg_trades", measured_at),),
        ("funding",),
    )
    provider = InMemoryMarketFeatureProvider(
        (row,),
        max_staleness=timedelta(minutes=1),
        unavailable_sources=("open_interest",),
    )

    result = provider.load_features(SYMBOL, TIMEFRAME, T)

    assert result == MarketFeatureSet(
        SYMBOL,
        TIMEFRAME,
        T,
        (),
        ("open_interest", "funding", "agg_trades"),
    )


def test_in_memory_provider_returns_configured_empty_when_no_row_is_eligible():
    provider = InMemoryMarketFeatureProvider(
        (make_set(T + timedelta(microseconds=1)),),
        unavailable_sources=("agg_trades",),
    )

    result = provider.load_features(SYMBOL, TIMEFRAME, T)

    assert result == MarketFeatureSet(
        SYMBOL,
        TIMEFRAME,
        T,
        (),
        ("agg_trades",),
    )
