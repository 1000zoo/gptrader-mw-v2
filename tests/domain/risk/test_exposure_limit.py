from decimal import Decimal

import pytest

from src.domain.risk import ExposureLimit


def test_exposure_limit_calculates_remaining_capacity():
    limit = ExposureLimit(
        equity=Decimal("1000"),
        current_total_exposure=Decimal("300"),
        current_symbol_exposure=Decimal("100"),
        max_total_exposure_ratio=Decimal("0.8"),
        max_symbol_exposure_ratio=Decimal("0.25"),
    )

    assert limit.max_total_exposure == Decimal("800.0")
    assert limit.max_symbol_exposure == Decimal("250.00")
    assert limit.remaining_total_exposure == Decimal("500.0")
    assert limit.remaining_symbol_exposure == Decimal("150.00")


def test_exposure_limit_allows_new_notional_within_both_limits():
    limit = ExposureLimit(
        equity=Decimal("1000"),
        current_total_exposure=Decimal("300"),
        current_symbol_exposure=Decimal("100"),
        max_total_exposure_ratio=Decimal("0.8"),
        max_symbol_exposure_ratio=Decimal("0.25"),
    )

    assert limit.allows(Decimal("150"))
    assert not limit.allows(Decimal("151"))


def test_exposure_limit_rejects_invalid_values():
    with pytest.raises(ValueError, match="equity"):
        ExposureLimit(
            equity=Decimal("0"),
            current_total_exposure=Decimal("0"),
            current_symbol_exposure=Decimal("0"),
            max_total_exposure_ratio=Decimal("1"),
            max_symbol_exposure_ratio=Decimal("1"),
        )

    with pytest.raises(ValueError, match="exposure"):
        ExposureLimit(
            equity=Decimal("1000"),
            current_total_exposure=Decimal("-1"),
            current_symbol_exposure=Decimal("0"),
            max_total_exposure_ratio=Decimal("1"),
            max_symbol_exposure_ratio=Decimal("1"),
        )

    with pytest.raises(ValueError, match="ratio"):
        ExposureLimit(
            equity=Decimal("1000"),
            current_total_exposure=Decimal("0"),
            current_symbol_exposure=Decimal("0"),
            max_total_exposure_ratio=Decimal("0"),
            max_symbol_exposure_ratio=Decimal("1"),
        )
