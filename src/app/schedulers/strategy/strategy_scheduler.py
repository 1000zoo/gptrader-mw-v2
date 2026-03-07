from loguru import logger

from src.app.usecase.market_data_preparation_usecase import MarketDataPreparationUseCase
from src.binance.service.trader.account_service import AccountService
from src.ops.service.scheduler.scheduler_service import SchedulerService


class StrategyScheduler:
    def __init__(self):
        self.name = self.__class__.__name__

        self.scheduler_service = SchedulerService()
        self.account_service = AccountService()
        self.market_data_usecase = MarketDataPreparationUseCase()

    def _can_start_exit_scheduler(self):
        if not self.scheduler_service.is_valid_scheduler(self.name):
            logger.info(f"{self.name} state is not Y")
            return False
        if not self.account_service.has_position():
            logger.info(f"has no open position now.. skip strategy")
            return False
        return True

    def _get_prepare_data(self):
        position = self.account_service.get_positions()

    def run_exit(self):
        if not self._can_start_exit_scheduler():
            return

        data = self.market_data_usecase()










