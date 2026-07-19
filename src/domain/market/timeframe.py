from dataclasses import dataclass


_SECONDS_BY_UNIT = {
    "m": 60,
    "h": 60 * 60,
    "d": 24 * 60 * 60,
    "w": 7 * 24 * 60 * 60,
}


@dataclass(frozen=True)
class Timeframe:
    value: int
    unit: str

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise ValueError("timeframe value must be positive")

        unit = self.unit.strip().lower()
        if unit not in _SECONDS_BY_UNIT:
            raise ValueError("timeframe unit is not supported")

        object.__setattr__(self, "unit", unit)

    @property
    def label(self) -> str:
        return f"{self.value}{self.unit}"

    @property
    def duration_seconds(self) -> int:
        return self.value * _SECONDS_BY_UNIT[self.unit]
