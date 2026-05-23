import pytest

from src.domain.lifecycle import SignalGeneratorDefinition


def test_signal_generator_definition_stores_normalized_strategy_references():
    definition = SignalGeneratorDefinition(
        generator_id=" regime-main ",
        name=" Regime Main ",
        strategy_ids=(" breakout ", " mean-reversion "),
        regime_routes={"trend": " breakout ", "range": " mean-reversion "},
        metadata={"owner": "research"},
    )

    assert definition.generator_id == "regime-main"
    assert definition.name == "Regime Main"
    assert definition.strategy_ids == ("breakout", "mean-reversion")
    assert definition.regime_routes["trend"] == "breakout"
    assert definition.regime_routes["range"] == "mean-reversion"
    assert definition.metadata["owner"] == "research"


def test_signal_generator_definition_rejects_empty_strategy_ids():
    with pytest.raises(ValueError, match="strategy_ids"):
        SignalGeneratorDefinition(
            generator_id="main",
            name="Main",
            strategy_ids=(),
        )


def test_signal_generator_definition_rejects_unknown_regime_route_target():
    with pytest.raises(ValueError, match="regime_routes"):
        SignalGeneratorDefinition(
            generator_id="main",
            name="Main",
            strategy_ids=("breakout",),
            regime_routes={"range": "mean-reversion"},
        )


def test_signal_generator_definition_defensively_copies_mappings():
    routes = {"trend": "breakout"}
    metadata = {"owner": "research"}

    definition = SignalGeneratorDefinition(
        generator_id="main",
        name="Main",
        strategy_ids=("breakout",),
        regime_routes=routes,
        metadata=metadata,
    )
    routes["trend"] = "changed"
    metadata["owner"] = "ops"

    assert definition.regime_routes["trend"] == "breakout"
    assert definition.metadata["owner"] == "research"
    with pytest.raises(TypeError):
        definition.regime_routes["trend"] = "changed"
    with pytest.raises(TypeError):
        definition.metadata["owner"] = "ops"
