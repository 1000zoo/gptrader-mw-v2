import pytest

from src.domain.market import Timeframe


def test_timeframe_exposes_canonical_label_and_duration_seconds():
    timeframe = Timeframe(15, "m")

    assert timeframe.value == 15
    assert timeframe.unit == "m"
    assert timeframe.label == "15m"
    assert timeframe.duration_seconds == 900


def test_timeframe_accepts_supported_units():
    assert Timeframe(1, "m").duration_seconds == 60
    assert Timeframe(2, "h").duration_seconds == 7200
    assert Timeframe(1, "d").duration_seconds == 86400
    assert Timeframe(1, "w").duration_seconds == 604800


def test_timeframe_rejects_non_positive_value():
    with pytest.raises(ValueError, match="positive"):
        Timeframe(0, "m")


def test_timeframe_rejects_unsupported_unit():
    with pytest.raises(ValueError, match="unit"):
        Timeframe(1, "month")
