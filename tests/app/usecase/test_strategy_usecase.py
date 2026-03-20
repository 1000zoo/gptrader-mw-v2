import pytest

from src.app.usecase.strategy_usecase import StrategyUseCase, RunStrategyDto

usecase = StrategyUseCase()

@pytest.mark.asyncio
async def test_load_strategy_by_priority():
    strategy = await usecase.load_strategy_by_priority()

    print(strategy._config.timeframes)
    print(strategy._config.lookback_by_tf)

@pytest.mark.asyncio
async def test_run_exit_strategy():
    _ = await usecase.load_strategy_by_priority()
    decision = await usecase.run_exit_strategy(RunStrategyDto(symbol_id="BTCUSDT"))
    print(decision)