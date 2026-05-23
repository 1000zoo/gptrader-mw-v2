from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from src.domain.signal import Signal
from src.domain.strategy import StrategyContext
from src.domain.signal_generator.signal_generator import GeneratedSignal, SignalGenerator


@dataclass(frozen=True)
class RegimeSignalGenerator:
    generators: Mapping[str, SignalGenerator]
    metadata_key: str = "regime"

    def __post_init__(self) -> None:
        metadata_key = self.metadata_key.strip()
        if not metadata_key:
            raise ValueError("metadata_key is required")

        object.__setattr__(self, "metadata_key", metadata_key)
        object.__setattr__(self, "generators", MappingProxyType(dict(self.generators)))

    def generate(self, context: StrategyContext) -> GeneratedSignal:
        regime = context.metadata.get(self.metadata_key)
        if not isinstance(regime, str):
            return GeneratedSignal(signal=Signal.wait())

        generator = self.generators.get(regime)
        if generator is None:
            return GeneratedSignal(signal=Signal.wait())

        return generator.generate(context)
