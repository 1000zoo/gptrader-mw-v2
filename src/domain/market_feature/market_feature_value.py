from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


def require_aware_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class MarketFeatureValue:
    name: str
    value: Decimal
    source: str
    observed_at: datetime
    available_at: datetime

    def __post_init__(self) -> None:
        name = self.normalize_name(self.name)
        source = self.normalize_source(self.source)
        if not isinstance(self.value, Decimal):
            raise TypeError("value must be a Decimal")
        if not self.value.is_finite():
            raise ValueError("value must be finite")

        require_aware_datetime(self.observed_at, "observed_at")
        require_aware_datetime(self.available_at, "available_at")
        if as_utc(self.observed_at) > as_utc(self.available_at):
            raise ValueError("observed_at must be before or equal to available_at")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "source", source)

    @staticmethod
    def normalize_name(name: str) -> str:
        if not isinstance(name, str):
            raise TypeError("name must be a str")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("name is required")
        return normalized_name

    @staticmethod
    def normalize_source(source: str) -> str:
        if not isinstance(source, str):
            raise TypeError("source must be a str")
        normalized_source = source.strip()
        if not normalized_source:
            raise ValueError("source is required")
        return normalized_source
