from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    name: str
    implementation: str
    version: str
    parameters: Mapping[str, object] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        strategy_id = self.strategy_id.strip()
        name = self.name.strip()
        implementation = self.implementation.strip()
        version = self.version.strip()

        if not strategy_id:
            raise ValueError("strategy_id is required")
        if not name:
            raise ValueError("name is required")
        if not implementation:
            raise ValueError("implementation is required")
        if not version:
            raise ValueError("version is required")

        object.__setattr__(self, "strategy_id", strategy_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "implementation", implementation)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
