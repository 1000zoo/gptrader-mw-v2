from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from src.domain.signal import Signal


@dataclass(frozen=True)
class StrategyResult:
    name: str
    signal: Signal
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("name is required")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
