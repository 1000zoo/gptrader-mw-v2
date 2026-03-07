import pytest

from src.app.usecase.strategy_preparation_usecase import StrategyPreparationUseCase

usecase = StrategyPreparationUseCase()

@pytest.mark.asyncio
async def test_load_strategy_by_priority():
    strategy = await usecase.load_strategy_by_priority()

    print(strategy._config.timeframes)
    print(strategy._config.lookback_by_tf)