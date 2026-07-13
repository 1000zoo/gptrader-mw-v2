
from typing import List, Any
from loguru import logger

from src.common.db.util import common_insert_bulk, common_insert
from src.analyze.vo.openAi.analyze.analyze_result_vo_default import DefaultAnalyzeResultVo

class AnalyzeResultRepository:
    def __init__(self):
        self.TABLE_NAME = "analyze_result"

    async def insert_result_bulk(self, vo: List[DefaultAnalyzeResultVo]) -> Any:
        rowcount = await common_insert_bulk(self.TABLE_NAME, vo)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def insert_result(self, vo: DefaultAnalyzeResultVo) -> Any:
        rowcount = await common_insert(self.TABLE_NAME, vo.model_dump(exclude_none=True))
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount