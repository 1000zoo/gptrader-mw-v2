from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.domain.indicator import IndicatorValue


def test_indicator_value_normalizes_name_and_parameters_into_key():
    value = IndicatorValue(
        name=" RSI ",
        value=Decimal("72.5"),
        measured_at=datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc),
        parameters={"window": 14, "source": "close"},
    )

    assert value.name == "rsi"
    assert value.key == "rsi.source_close.window_14"
    assert value.value == Decimal("72.5")


def test_indicator_value_without_parameters_uses_name_as_key():
    value = IndicatorValue(
        name="macd_hist",
        value=Decimal("-0.15"),
        measured_at=datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc),
    )

    assert value.key == "macd_hist"


def test_indicator_value_rejects_empty_name():
    with pytest.raises(ValueError, match="name"):
        IndicatorValue(
            name=" ",
            value=Decimal("1"),
            measured_at=datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc),
        )


def test_indicator_value_copies_parameters():
    parameters = {"window": 20}

    value = IndicatorValue(
        name="sma",
        value=Decimal("102.5"),
        measured_at=datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc),
        parameters=parameters,
    )
    parameters["window"] = 50

    assert value.parameters["window"] == 20
