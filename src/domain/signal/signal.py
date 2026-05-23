from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Sequence

from src.domain.signal.signal_reason import SignalReason


class SignalDirection(Enum):
    LONG = "long"
    SHORT = "short"
    WAIT = "wait"


@dataclass(frozen=True)
class Signal:
    direction: SignalDirection
    confidence: Decimal
    reasons: Sequence[SignalReason] = field(default_factory=tuple)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.confidence < Decimal("0") or self.confidence > Decimal("1"):
            raise ValueError("confidence must be between zero and one")

        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def wait(cls, metadata: Mapping[str, object] | None = None) -> "Signal":
        return cls(
            direction=SignalDirection.WAIT,
            confidence=Decimal("0"),
            metadata={} if metadata is None else metadata,
        )
