from decimal import Decimal

import pytest

from src.domain.market import Symbol, Timeframe
from src.domain.strategy import StaticStrategyCatalog, StrategySpec
from src.domain.strategy.implementations import (
    ChartPatternStrategy,
    LatestCloseMovingAverageStrategy,
    RangeEdgeReversionStrategy,
    SessionVolumeProfileStrategy,
    VolatilityCompressionBreakoutStrategy,
    create_default_strategy_catalog,
)


def test_strategy_spec_stores_candidate_metadata() -> None:
    spec = StrategySpec(
        strategy_id="session-volume-profile",
        name="Session Volume Profile",
        implementation="src.domain.strategy.implementations.SessionVolumeProfileStrategy",
        version="2026.06.17",
        symbol=Symbol("BTC", "USDT"),
        timeframe=Timeframe(5, "m"),
        lookback_candle_limit=25920,
        parameters={"price_bin_size": Decimal("10")},
        metadata={"family": "volume_profile"},
    )

    assert spec.strategy_id == "session-volume-profile"
    assert spec.name == "Session Volume Profile"
    assert spec.lookback_candle_limit == 25920
    assert spec.parameters["price_bin_size"] == Decimal("10")
    assert spec.metadata["family"] == "volume_profile"


def test_strategy_spec_stores_indicator_requirements_as_tuple() -> None:
    indicator_keys = [" moving_average.period_4 "]

    spec = StrategySpec(
        strategy_id="latest-close-moving-average",
        name="Latest Close Moving Average",
        implementation="src.domain.strategy.implementations.LatestCloseMovingAverageStrategy",
        version="2026.06.17",
        symbol=Symbol("BTC", "USDT"),
        timeframe=Timeframe(1, "m"),
        lookback_candle_limit=240,
        indicator_keys=indicator_keys,
    )
    indicator_keys.append("moving_average.period_99")

    assert spec.indicator_keys == ("moving_average.period_4",)


def test_strategy_spec_rejects_blank_ids_and_invalid_lookback() -> None:
    with pytest.raises(ValueError, match="strategy_id"):
        StrategySpec(
            strategy_id=" ",
            name="Name",
            implementation="impl",
            version="1",
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            lookback_candle_limit=1,
        )

    with pytest.raises(ValueError, match="lookback_candle_limit"):
        StrategySpec(
            strategy_id="strategy-1",
            name="Name",
            implementation="impl",
            version="1",
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            lookback_candle_limit=0,
        )

    with pytest.raises(ValueError, match="indicator_keys"):
        StrategySpec(
            strategy_id="strategy-1",
            name="Name",
            implementation="impl",
            version="1",
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "m"),
            lookback_candle_limit=1,
            indicator_keys=(" ",),
        )


def test_static_strategy_catalog_lists_specs_in_stable_order() -> None:
    catalog = create_default_strategy_catalog()

    specs = catalog.list_specs()

    assert tuple(spec.strategy_id for spec in specs) == (
        "latest-close-moving-average",
        "session-volume-profile",
        "chart-pattern",
        "tv-range-seed-s1-t1-p2-fixed",
        "live-compression-s2-sl0030-rr045-balanced",
    )


def test_default_strategy_catalog_declares_indicator_requirements() -> None:
    catalog = create_default_strategy_catalog()
    specs = {spec.strategy_id: spec for spec in catalog.list_specs()}

    assert specs["latest-close-moving-average"].indicator_keys == (
        "moving_average.period_3",
    )
    assert specs["session-volume-profile"].indicator_keys == ()
    assert specs["chart-pattern"].indicator_keys == ()
    assert specs["tv-range-seed-s1-t1-p2-fixed"].parameters == {
        "range_period": 300,
        "lower_band": Decimal("0.06"),
        "upper_band": Decimal("0.94"),
        "min_range_width": Decimal("0.010"),
        "reclaim_return": Decimal("0.0007"),
    }
    assert specs["live-compression-s2-sl0030-rr045-balanced"].parameters == {
        "lookback": 180,
        "compression_period": 45,
        "compression_ratio": Decimal("0.45"),
        "breakout_buffer": Decimal("0.0006"),
        "min_volume_ratio": Decimal("1.00"),
        "direction_filter_period": 1440,
        "min_filter_return": Decimal("0.002"),
    }
    assert specs["live-compression-s2-sl0030-rr045-balanced"].lookback_candle_limit == 1442


def test_static_strategy_catalog_instantiates_strategy_from_spec() -> None:
    catalog = create_default_strategy_catalog()
    specs = {spec.strategy_id: spec for spec in catalog.list_specs()}

    moving_average = catalog.create_strategy(specs["latest-close-moving-average"])
    profile = catalog.create_strategy(specs["session-volume-profile"])
    chart_pattern = catalog.create_strategy(specs["chart-pattern"])
    range_edge = catalog.create_strategy(specs["tv-range-seed-s1-t1-p2-fixed"])
    compression = catalog.create_strategy(
        specs["live-compression-s2-sl0030-rr045-balanced"]
    )

    assert isinstance(moving_average, LatestCloseMovingAverageStrategy)
    assert isinstance(profile, SessionVolumeProfileStrategy)
    assert isinstance(chart_pattern, ChartPatternStrategy)
    assert isinstance(range_edge, RangeEdgeReversionStrategy)
    assert isinstance(compression, VolatilityCompressionBreakoutStrategy)


def test_static_strategy_catalog_applies_spec_parameters() -> None:
    catalog = StaticStrategyCatalog(
        entries=(
            (
                StrategySpec(
                    strategy_id="session-volume-profile",
                    name="Session Volume Profile",
                    implementation="src.domain.strategy.implementations.SessionVolumeProfileStrategy",
                    version="2026.06.17",
                    symbol=Symbol("BTC", "USDT"),
                    timeframe=Timeframe(5, "m"),
                    lookback_candle_limit=100,
                    parameters={"price_bin_size": Decimal("25")},
                ),
                SessionVolumeProfileStrategy,
            ),
        )
    )

    strategy = catalog.create_strategy(catalog.list_specs()[0])

    assert isinstance(strategy, SessionVolumeProfileStrategy)
    assert strategy.price_bin_size == Decimal("25")
