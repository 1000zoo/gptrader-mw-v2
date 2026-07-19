from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.domain.signal_generator import GeneratedSignal


@dataclass(frozen=True)
class SignalLogEntry:
    signal_id: str
    generator_id: str
    generated_signal: GeneratedSignal

    def __post_init__(self) -> None:
        signal_id = self.signal_id.strip()
        generator_id = self.generator_id.strip()
        if not signal_id:
            raise ValueError("signal_id is required")
        if not generator_id:
            raise ValueError("generator_id is required")

        object.__setattr__(self, "signal_id", signal_id)
        object.__setattr__(self, "generator_id", generator_id)


@runtime_checkable
class SignalLogRepositoryPort(Protocol):
    def append_signal(self, entry: SignalLogEntry) -> None:
        ...

    def list_signals_for_generator(
        self,
        generator_id: str,
    ) -> tuple[SignalLogEntry, ...]:
        ...
