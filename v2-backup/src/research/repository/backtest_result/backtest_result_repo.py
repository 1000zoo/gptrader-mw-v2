from typing import List

from loguru import logger

from src.common.db.util import common_insert, common_select
from src.research.vo.backtest_result.default import DefaultBacktestResultVo
from src.research.vo.backtest_result.filter import BacktestResultFilterVo


class BacktestResultRepository:
    def __init__(self):
        self.TABLE_NAME = "backtest_result"

    async def insert_backtest_result(self, vo: DefaultBacktestResultVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_backtest_results(self, vo: BacktestResultFilterVo) -> List[DefaultBacktestResultVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultBacktestResultVo)
