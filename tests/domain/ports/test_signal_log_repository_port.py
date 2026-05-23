from decimal import Decimal
from typing import Protocol

from src.domain.ports import SignalLogEntry, SignalLogRepositoryPort
from src.domain.signal import Signal, SignalDirection
from src.domain.signal_generator import GeneratedSignal


class InMemorySignalLogRepositoryPort:
    def __init__(self) -> None:
        self.entries: list[SignalLogEntry] = []

    def append_signal(self, entry: SignalLogEntry) -> None:
        self.entries.append(entry)

    def list_signals_for_generator(self, generator_id: str) -> tuple[SignalLogEntry, ...]:
        return tuple(
            entry
            for entry in self.entries
            if entry.generator_id == generator_id
        )


def test_signal_log_repository_port_is_protocol_contract():
    assert issubclass(SignalLogRepositoryPort, Protocol)


def test_signal_log_entry_normalizes_ids_and_stores_generated_signal():
    generated = GeneratedSignal(
        signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.7")),
    )
    entry = SignalLogEntry(
        signal_id=" signal-1 ",
        generator_id=" generator-1 ",
        generated_signal=generated,
    )
    repository = InMemorySignalLogRepositoryPort()

    repository.append_signal(entry)

    assert isinstance(repository, SignalLogRepositoryPort)
    assert entry.signal_id == "signal-1"
    assert entry.generator_id == "generator-1"
    assert repository.list_signals_for_generator("generator-1") == (entry,)
