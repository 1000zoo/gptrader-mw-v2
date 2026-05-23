from decimal import Decimal

from src.domain.lifecycle import (
    SignalGeneratorDefinition,
    StrategyDefinition,
    StrategyEvaluation,
    StrategyLifecycleStatus,
)
from src.domain.ports import StrategyRepositoryPort
from src.infrastructure.persistence.repositories import SqliteStrategyRepository


def test_sqlite_strategy_repository_round_trips_lifecycle_models(tmp_path):
    repository = SqliteStrategyRepository(tmp_path / "lifecycle.sqlite3")
    strategy = StrategyDefinition(
        strategy_id="mean-reversion",
        name="Mean Reversion",
        implementation="src.domain.strategy.implementations.mean_reversion",
        version="1",
        parameters={"window": 20, "threshold": "1.5"},
        metadata={"market": "BTCUSDT"},
    )
    generator = SignalGeneratorDefinition(
        generator_id="generator-1",
        name="Main Generator",
        strategy_ids=("mean-reversion",),
        regime_routes={"range": "mean-reversion"},
        metadata={"mode": "composite"},
    )
    evaluation = StrategyEvaluation(
        evaluation_id="eval-1",
        target_id="generator-1",
        status=StrategyLifecycleStatus.BACKTESTED,
        metrics={"sharpe": Decimal("1.50"), "max_drawdown": Decimal("0.12")},
        metadata={"sample": "backtest"},
    )

    repository.save_strategy_definition(strategy)
    repository.save_signal_generator_definition(generator)
    repository.save_strategy_evaluation(evaluation)

    assert isinstance(repository, StrategyRepositoryPort)
    assert repository.load_strategy_definition("mean-reversion") == strategy
    assert repository.load_signal_generator_definition("generator-1") == generator
    assert repository.list_strategy_evaluations("generator-1") == (evaluation,)
    assert repository.list_strategy_evaluations("unknown") == ()


def test_sqlite_strategy_repository_updates_definitions_by_id(tmp_path):
    repository = SqliteStrategyRepository(tmp_path / "lifecycle.sqlite3")
    original = StrategyDefinition(
        strategy_id="breakout",
        name="Breakout",
        implementation="old.module",
        version="1",
    )
    updated = StrategyDefinition(
        strategy_id="breakout",
        name="Breakout V2",
        implementation="new.module",
        version="2",
        parameters={"lookback": 55},
    )

    repository.save_strategy_definition(original)
    repository.save_strategy_definition(updated)

    assert repository.load_strategy_definition("breakout") == updated
