from loguru import logger

from src.app.usecase.account_praparation_usecase import AccountPreparationUseCase, JobPosition
from src.app.usecase.market_data_preparation_usecase import MarketDataPreparationUseCase, PreparedDataDto, \
    PrepareDataDto
from src.app.usecase.strategy_preparation_usecase import StrategyPreparationUseCase
from src.ops.service.scheduler.scheduler_service import SchedulerService
from src.strategy.strategies.IStrategy import IStrategy


class StrategyScheduler:
    def __init__(self):
        self.name = self.__class__.__name__

        self.scheduler_service = SchedulerService()
        self.account_usecase = AccountPreparationUseCase()
        self.strategy_usecase = StrategyPreparationUseCase()
        self.market_data_usecase = MarketDataPreparationUseCase()

    def _can_start_exit_scheduler(self):
        if not self.scheduler_service.is_valid_scheduler(self.name):
            logger.info(f"{self.name} state is not Y")
            return False
        return True

    async def run_exit(self):
        if not self._can_start_exit_scheduler():
            return
        job_position: JobPosition = await self.account_usecase.get_current_job_position()
        job = job_position.job
        position = job_position.position

        strategy: IStrategy = await self.strategy_usecase.load_strategy_by_priority()

        prepared_data: PreparedDataDto = await self.market_data_usecase.prepare_data(
            PrepareDataDto(

            )
        )