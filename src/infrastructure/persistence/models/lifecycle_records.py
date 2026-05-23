import json
from decimal import Decimal
from typing import Any

from src.domain.lifecycle import (
    SignalGeneratorDefinition,
    StrategyDefinition,
    StrategyEvaluation,
    StrategyLifecycleStatus,
)


def dumps_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def loads_payload(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def strategy_definition_to_payload(definition: StrategyDefinition) -> dict[str, Any]:
    return {
        "strategy_id": definition.strategy_id,
        "name": definition.name,
        "implementation": definition.implementation,
        "version": definition.version,
        "parameters": dict(definition.parameters),
        "metadata": dict(definition.metadata),
    }


def strategy_definition_from_payload(payload: dict[str, Any]) -> StrategyDefinition:
    return StrategyDefinition(
        strategy_id=payload["strategy_id"],
        name=payload["name"],
        implementation=payload["implementation"],
        version=payload["version"],
        parameters=payload.get("parameters", {}),
        metadata=payload.get("metadata", {}),
    )


def signal_generator_definition_to_payload(
    definition: SignalGeneratorDefinition,
) -> dict[str, Any]:
    return {
        "generator_id": definition.generator_id,
        "name": definition.name,
        "strategy_ids": list(definition.strategy_ids),
        "regime_routes": dict(definition.regime_routes),
        "metadata": dict(definition.metadata),
    }


def signal_generator_definition_from_payload(
    payload: dict[str, Any],
) -> SignalGeneratorDefinition:
    return SignalGeneratorDefinition(
        generator_id=payload["generator_id"],
        name=payload["name"],
        strategy_ids=tuple(payload["strategy_ids"]),
        regime_routes=payload.get("regime_routes", {}),
        metadata=payload.get("metadata", {}),
    )


def strategy_evaluation_to_payload(evaluation: StrategyEvaluation) -> dict[str, Any]:
    return {
        "evaluation_id": evaluation.evaluation_id,
        "target_id": evaluation.target_id,
        "status": evaluation.status.value,
        "metrics": {
            name: str(value)
            for name, value in evaluation.metrics.items()
        },
        "metadata": dict(evaluation.metadata),
    }


def strategy_evaluation_from_payload(payload: dict[str, Any]) -> StrategyEvaluation:
    return StrategyEvaluation(
        evaluation_id=payload["evaluation_id"],
        target_id=payload["target_id"],
        status=StrategyLifecycleStatus(payload["status"]),
        metrics={
            name: Decimal(value)
            for name, value in payload.get("metrics", {}).items()
        },
        metadata=payload.get("metadata", {}),
    )
