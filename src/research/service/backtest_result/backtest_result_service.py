from typing import List

from sqlalchemy.exc import SQLAlchemyError

from src.common.exception.repository_error import RepositoryError
from src.research.repository.backtest_result.backtest_result_repo import BacktestResultRepository
from src.research.vo.backtest_result.default import DefaultBacktestResultVo
from src.research.vo.backtest_result.filter import BacktestResultFilterVo


class BacktestResultService:
    def __init__(self):
        self.repository = BacktestResultRepository()

    async def create_backtest_result(self, vo: DefaultBacktestResultVo) -> int:
        try:
            return await self.repository.insert_backtest_result(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert backtest_result.") from e

    async def find_backtest_results(self, vo: BacktestResultFilterVo) -> List[DefaultBacktestResultVo]:
        try:
            return await self.repository.select_backtest_results(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select backtest_result.") from e
