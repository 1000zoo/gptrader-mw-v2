import asyncio

from typing import List
from loguru import logger
from sqlalchemy import text

from src.common.db.util import common_insert, common_select, common_insert_bulk
from src.common.db.connection import SessionLocal
from src.indicators.vo.indicator.default import DefaultIndicatorVo
from src.indicators.vo.indicator.filter import IndicatorsFilterVo

class IndicatorRepository:
    def __init__(self):
        self.TABLE_NAME = "indicators"
    
    async def insert_indicators(self, vo: DefaultIndicatorVo) -> int:
        data = vo.model_dump()
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
    
    async def insert_indicators_bulk(self, vo: List[DefaultIndicatorVo]) -> int:
        rowcount = await common_insert_bulk(self.TABLE_NAME, vo)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_indicators(self, vo: IndicatorsFilterVo) -> List[DefaultIndicatorVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultIndicatorVo)

    async def select_recent_indicators(
        self, symbol_id: str, interval: str, limit: int
    ) -> List[DefaultIndicatorVo]:
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE symbol_id = :symbol_id
              AND c_interval = :interval
            ORDER BY COALESCE(ts, reg_dt) DESC, seq_no DESC
            LIMIT :limit
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {"symbol_id": symbol_id, "interval": interval, "limit": limit},
            )
            rows = result.mappings().all()
            return [DefaultIndicatorVo(**r) for r in rows]
