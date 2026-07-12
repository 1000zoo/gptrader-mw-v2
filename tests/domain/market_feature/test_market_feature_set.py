from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.domain.market import Symbol, Timeframe
from src.domain.market_feature import (
    MARKET_FEATURES_METADATA_KEY,
    MarketFeatureSet,
    MarketFeatureValue,
)


SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")
MEASURED_AT = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def make_value(
    name: str = "taker_imbalance",
    source: str = "binance_klines",
    observed_at: datetime = MEASURED_AT,
    available_at: datetime = MEASURED_AT,
) -> MarketFeatureValue:
    return MarketFeatureValue(
        name=name,
        value=Decimal("0.2"),
        source=source,
        observed_at=observed_at,
        available_at=available_at,
    )


def test_market_feature_value_is_immutable_and_normalizes_text_fields():
    value = make_value(name=" taker_imbalance ", source=" binance_klines ")

    assert value.name == "taker_imbalance"
    assert value.source == "binance_klines"
    with pytest.raises(FrozenInstanceError):
        value.value = Decimal("0.3")


@pytest.mark.parametrize("field", ["name", "source"])
def test_market_feature_value_rejects_empty_text_fields(field: str):
    arguments = {
        "name": "taker_imbalance",
        "value": Decimal("0.2"),
        "source": "binance_klines",
        "observed_at": MEASURED_AT,
        "available_at": MEASURED_AT,
    }
    arguments[field] = " "

    with pytest.raises(ValueError, match=field):
        MarketFeatureValue(**arguments)


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_market_feature_value_rejects_non_finite_decimal(value: Decimal):
    with pytest.raises(ValueError, match="finite"):
        MarketFeatureValue(
            name="taker_imbalance",
            value=value,
            source="binance_klines",
            observed_at=MEASURED_AT,
            available_at=MEASURED_AT,
        )


def test_market_feature_value_rejects_non_decimal_value():
    with pytest.raises(TypeError, match="Decimal"):
        MarketFeatureValue(
            name="taker_imbalance",
            value=1,
            source="binance_klines",
            observed_at=MEASURED_AT,
            available_at=MEASURED_AT,
        )


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_type"),
    [
        ("name", 1, "str"),
        ("source", object(), "str"),
        ("observed_at", "2026-01-01T00:01:00Z", "datetime"),
        ("available_at", 1, "datetime"),
    ],
)
def test_market_feature_value_rejects_invalid_field_types(
    field: str,
    invalid_value: object,
    expected_type: str,
):
    arguments = {
        "name": "taker_imbalance",
        "value": Decimal("0.2"),
        "source": "binance_klines",
        "observed_at": MEASURED_AT,
        "available_at": MEASURED_AT,
    }
    arguments[field] = invalid_value

    with pytest.raises(TypeError, match=f"{field}.*{expected_type}"):
        MarketFeatureValue(**arguments)


@pytest.mark.parametrize("field", ["observed_at", "available_at"])
def test_market_feature_value_rejects_naive_timestamps(field: str):
    arguments = {
        "name": "taker_imbalance",
        "value": Decimal("0.2"),
        "source": "binance_klines",
        "observed_at": MEASURED_AT,
        "available_at": MEASURED_AT,
    }
    arguments[field] = datetime(2026, 1, 1, 0, 1)

    with pytest.raises(ValueError, match=field):
        MarketFeatureValue(**arguments)


def test_market_feature_value_rejects_availability_before_observation():
    with pytest.raises(ValueError, match="observed_at"):
        make_value(
            observed_at=MEASURED_AT,
            available_at=MEASURED_AT - timedelta(microseconds=1),
        )


def test_market_feature_value_compares_fallback_fold_times_absolutely():
    new_york = ZoneInfo("America/New_York")
    observed_at = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=1)
    available_at = datetime(2026, 11, 1, 1, 45, tzinfo=new_york, fold=0)

    with pytest.raises(ValueError, match="observed_at"):
        make_value(observed_at=observed_at, available_at=available_at)


def test_market_feature_set_defensively_normalizes_tuples_and_supports_lookup():
    value = make_value()
    values = [value]
    unavailable_sources = [" open_interest "]

    features = MarketFeatureSet(
        SYMBOL,
        TIMEFRAME,
        MEASURED_AT,
        values,
        unavailable_sources,
    )
    values.clear()
    unavailable_sources.clear()

    assert features.values == (value,)
    assert features.unavailable_sources == ("open_interest",)
    assert features.get(" taker_imbalance ") is value
    assert features.get("open_interest") is None
    assert features.require(" taker_imbalance ") is value
    with pytest.raises(FrozenInstanceError):
        features.measured_at = MEASURED_AT + timedelta(minutes=1)
    with pytest.raises(KeyError, match="missing market feature: open_interest"):
        features.require("open_interest")


@pytest.mark.parametrize("method_name", ["get", "require"])
def test_market_feature_set_lookup_rejects_non_string_name(method_name: str):
    features = MarketFeatureSet(SYMBOL, TIMEFRAME, MEASURED_AT, (make_value(),))

    with pytest.raises(TypeError, match="name.*str"):
        getattr(features, method_name)(1)


@pytest.mark.parametrize("method_name", ["get", "require"])
def test_market_feature_set_lookup_rejects_blank_name(method_name: str):
    features = MarketFeatureSet(SYMBOL, TIMEFRAME, MEASURED_AT, (make_value(),))

    with pytest.raises(ValueError, match="name"):
        getattr(features, method_name)(" ")


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_type"),
    [
        ("symbol", "BTCUSDT", "Symbol"),
        ("timeframe", "1m", "Timeframe"),
        ("measured_at", "2026-01-01T00:01:00Z", "datetime"),
        ("values", (object(),), "MarketFeatureValue"),
        ("unavailable_sources", (1,), "str"),
    ],
)
def test_market_feature_set_rejects_invalid_field_types(
    field: str,
    invalid_value: object,
    expected_type: str,
):
    arguments = {
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "measured_at": MEASURED_AT,
        "values": (),
        "unavailable_sources": (),
    }
    arguments[field] = invalid_value

    with pytest.raises(TypeError, match=f"{field}.*{expected_type}"):
        MarketFeatureSet(**arguments)


def test_market_feature_set_rejects_naive_measured_at():
    with pytest.raises(ValueError, match="measured_at"):
        MarketFeatureSet(
            SYMBOL,
            TIMEFRAME,
            datetime(2026, 1, 1, 0, 1),
            (),
        )


def test_market_feature_set_rejects_duplicate_feature_names():
    with pytest.raises(ValueError, match="duplicate feature name"):
        MarketFeatureSet(
            SYMBOL,
            TIMEFRAME,
            MEASURED_AT,
            (make_value(), make_value()),
        )


def test_market_feature_set_rejects_duplicate_unavailable_source_names():
    with pytest.raises(ValueError, match="duplicate unavailable source"):
        MarketFeatureSet(
            SYMBOL,
            TIMEFRAME,
            MEASURED_AT,
            (),
            ("open_interest", " open_interest "),
        )


def test_market_feature_set_materializes_unavailable_source_generator_once():
    unavailable_sources = (source for source in (" open_interest ", "funding"))

    features = MarketFeatureSet(
        SYMBOL,
        TIMEFRAME,
        MEASURED_AT,
        (),
        unavailable_sources,
    )

    assert features.unavailable_sources == ("open_interest", "funding")


def test_market_feature_set_rejects_bare_string_unavailable_sources():
    with pytest.raises(TypeError, match="unavailable_sources"):
        MarketFeatureSet(SYMBOL, TIMEFRAME, MEASURED_AT, (), "open_interest")


def test_market_feature_set_rejects_empty_unavailable_source_name():
    with pytest.raises(ValueError, match="unavailable source"):
        MarketFeatureSet(SYMBOL, TIMEFRAME, MEASURED_AT, (), (" ",))


def test_market_feature_set_rejects_future_available_value():
    value = make_value(available_at=MEASURED_AT + timedelta(microseconds=1))

    with pytest.raises(ValueError, match="available_at"):
        MarketFeatureSet(SYMBOL, TIMEFRAME, MEASURED_AT, (value,), ())


def test_market_feature_set_compares_fallback_fold_times_absolutely():
    new_york = ZoneInfo("America/New_York")
    observed_at = datetime(2026, 11, 1, 1, 30, tzinfo=new_york, fold=0)
    available_at = datetime(2026, 11, 1, 1, 45, tzinfo=new_york, fold=1)
    measured_at = datetime(2026, 11, 1, 1, 50, tzinfo=new_york, fold=0)
    value = make_value(observed_at=observed_at, available_at=available_at)

    with pytest.raises(ValueError, match="available_at"):
        MarketFeatureSet(SYMBOL, TIMEFRAME, measured_at, (value,))


def test_market_feature_set_rejects_source_available_and_unavailable():
    with pytest.raises(ValueError, match="available and unavailable"):
        MarketFeatureSet(
            SYMBOL,
            TIMEFRAME,
            MEASURED_AT,
            (make_value(source="open_interest"),),
            ("open_interest",),
        )


def test_missing_source_is_not_represented_as_zero():
    features = MarketFeatureSet(
        SYMBOL,
        TIMEFRAME,
        MEASURED_AT,
        (),
        ("open_interest",),
    )

    assert features.get("open_interest") is None
    assert "open_interest" in features.unavailable_sources


def test_market_feature_metadata_key_is_exported():
    assert MARKET_FEATURES_METADATA_KEY == "market_features"
