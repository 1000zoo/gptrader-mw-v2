from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class IndicatorValue:
    name: str
    value: Decimal
    measured_at: datetime
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized_name = self._normalize_key_part(self.name)
        if not normalized_name:
            raise ValueError("name is required")

        normalized_parameters = {
            self._normalize_key_part(key): value for key, value in self.parameters.items()
        }
        if any(not key for key in normalized_parameters):
            raise ValueError("parameter names are required")

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "parameters", dict(normalized_parameters))

    @property
    def key(self) -> str:
        if not self.parameters:
            return self.name

        suffix = ".".join(
            f"{key}_{self._normalize_key_part(str(value))}"
            for key, value in sorted(self.parameters.items())
        )
        return f"{self.name}.{suffix}"

    @classmethod
    def normalize_key(cls, value: str) -> str:
        return cls._normalize_key_part(value)

    @staticmethod
    def _normalize_key_part(value: str) -> str:
        return value.strip().lower().replace(" ", "_")
