from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from src.app.schedulers.strategy.strategy_scheduler import StrategyScheduler
from src.strategy.strategies.models import StrategyDecision


@pytest.mark.asyncio
async def test_run_exit_closes_position_when_decision_is_opposite_side():
    scheduler = object.__new__(StrategyScheduler)
    scheduler.name = "StrategyScheduler"
    scheduler._can_start_exit_scheduler = Mock(return_value=True)

    scheduler.account_usecase = SimpleNamespace(
        get_current_job_position=AsyncMock(
            return_value=SimpleNamespace(
                job=SimpleNamespace(symbol_id="BTCUSDT"),
                position=SimpleNamespace(position_amt=0.5),
            )
        )
    )
    scheduler.strategy_usecase = SimpleNamespace(
        load_strategy_by_priority=AsyncMock(return_value=object()),
        run_exit_strategy=AsyncMock(
            return_value=StrategyDecision(action="SELL", confidence=0.8, reason="exit_long_signal")
        ),
    )
    scheduler.trade_service = SimpleNamespace(close_position=Mock())

    await scheduler.run_exit()

    scheduler.trade_service.close_position.assert_called_once_with("BTCUSDT")


@pytest.mark.asyncio
async def test_run_exit_does_not_close_when_decision_matches_position_side():
    scheduler = object.__new__(StrategyScheduler)
    scheduler.name = "StrategyScheduler"
    scheduler._can_start_exit_scheduler = Mock(return_value=True)

    scheduler.account_usecase = SimpleNamespace(
        get_current_job_position=AsyncMock(
            return_value=SimpleNamespace(
                job=SimpleNamespace(symbol_id="BTCUSDT"),
                position=SimpleNamespace(position_amt=1.0),
            )
        )
    )
    scheduler.strategy_usecase = SimpleNamespace(
        load_strategy_by_priority=AsyncMock(return_value=object()),
        run_exit_strategy=AsyncMock(
            return_value=StrategyDecision(action="BUY", confidence=0.7, reason="exit_short_signal")
        ),
    )
    scheduler.trade_service = SimpleNamespace(close_position=Mock())

    await scheduler.run_exit()

    scheduler.trade_service.close_position.assert_not_called()
