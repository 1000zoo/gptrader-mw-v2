from loguru import logger

from src.app.usecase.account_praparation_usecase import AccountPreparationUseCase, JobPosition
from src.app.usecase.strategy_usecase import StrategyUseCase, RunStrategyDto
from src.binance.service.trader.trade_service import TradeService
from src.ops.service.scheduler.scheduler_service import SchedulerService


class StrategyScheduler:
    def __init__(self):
        self.name = self.__class__.__name__

        self.scheduler_service = SchedulerService()
        self.account_usecase = AccountPreparationUseCase()
        self.strategy_usecase = StrategyUseCase()
        self.trade_service = TradeService()

    async def _can_start_exit_scheduler(self):
        if not await self.scheduler_service.is_valid_scheduler(self.name):
            logger.info(f"{self.name} state is not Y")
            return False
        return True

    async def run_exit(self):
        if not await self._can_start_exit_scheduler():
            return
        job_position: JobPosition = await self.account_usecase.get_current_job_position()
        if not job_position:
            logger.info("no position")
            return
        job = job_position.job
        position = job_position.position

        _ = await self.strategy_usecase.load_strategy_by_priority()
        decision = await self.strategy_usecase.run_exit_strategy(RunStrategyDto(symbol_id=job.symbol_id))
        if self._is_opposite_signal(decision.action, position.position_amt):
            logger.info(
                f"close position by strategy exit decision: symbol={job.symbol_id}, "
                f"decision={decision.action}, position_amt={position.position_amt}"
            )
            self.trade_service.close_position(job.symbol_id)

    @staticmethod
    def _is_opposite_signal(action: str, position_amt: float) -> bool:
        if action not in {"BUY", "SELL"}:
            return False
        if position_amt is None or position_amt == 0:
            return False
        if action == "SELL" and position_amt > 0:
            return True
        if action == "BUY" and position_amt < 0:
            return True
        return False


async def execute():
    scheduler = StrategyScheduler()
    return await scheduler.run_exit()
