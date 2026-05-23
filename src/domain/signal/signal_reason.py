from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class SignalReason:
    code: str
    message: str
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("code is required")
        if not self.message.strip():
            raise ValueError("message is required")

        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
