from typing import List

from loguru import logger
from sqlalchemy import text

from src.binance.vo.ohlcv.summary_default import OhlcvSummaryVo
from src.binance.vo.ohlcv.summary_filter import OhlcvSummaryFilterVo
from src.common.db.connection import SessionLocal
from src.common.db.util import common_insert, common_select


class OhlcvSummaryRepository:
    def __init__(self):
        self.TABLE_NAME = "ohlcv_summary"

    async def insert_ohlcv_summary(self, vo: OhlcvSummaryVo) -> int:
        data = vo.model_dump()
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_ohlcv_summary(self, vo: OhlcvSummaryFilterVo) -> List[OhlcvSummaryVo]:
        return await common_select(self.TABLE_NAME, vo, OhlcvSummaryVo)

    async def select_recent_ohlcv_summary(
        self, symbol_id: str, interval: str, limit: int
    ) -> List[OhlcvSummaryVo]:
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE symbol_id = :symbol_id
              AND c_interval = :interval
            ORDER BY COALESCE(end_ts, start_ts, reg_dt) DESC
            LIMIT :limit
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {"symbol_id": symbol_id, "interval": interval, "limit": limit},
            )
            rows = result.mappings().all()
            return [OhlcvSummaryVo(**r) for r in rows]
