import pytest

from src.domain.lifecycle import StrategyDefinition


def test_strategy_definition_normalizes_required_fields_and_stores_details():
    definition = StrategyDefinition(
        strategy_id=" breakout-v1 ",
        name=" Breakout ",
        implementation=" src.domain.strategy.implementations.breakout:BreakoutStrategy ",
        version=" 1.0.0 ",
        parameters={"window": 20},
        metadata={"owner": "research"},
    )

    assert definition.strategy_id == "breakout-v1"
    assert definition.name == "Breakout"
    assert definition.implementation == "src.domain.strategy.implementations.breakout:BreakoutStrategy"
    assert definition.version == "1.0.0"
    assert definition.parameters["window"] == 20
    assert definition.metadata["owner"] == "research"


def test_strategy_definition_rejects_blank_required_fields():
    with pytest.raises(ValueError, match="strategy_id"):
        StrategyDefinition(
            strategy_id=" ",
            name="Breakout",
            implementation="module:Strategy",
            version="1.0.0",
        )


def test_strategy_definition_defensively_copies_parameters_and_metadata():
    parameters = {"window": 20}
    metadata = {"owner": "research"}

    definition = StrategyDefinition(
        strategy_id="breakout-v1",
        name="Breakout",
        implementation="module:Strategy",
        version="1.0.0",
        parameters=parameters,
        metadata=metadata,
    )
    parameters["window"] = 10
    metadata["owner"] = "ops"

    assert definition.parameters["window"] == 20
    assert definition.metadata["owner"] == "research"
    with pytest.raises(TypeError):
        definition.parameters["window"] = 30
    with pytest.raises(TypeError):
        definition.metadata["owner"] = "ops"
