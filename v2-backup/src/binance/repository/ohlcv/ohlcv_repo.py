from typing import List
from loguru import logger
from sqlalchemy import text

from src.common.db.util import common_insert, common_select, common_insert_bulk
from src.common.db.connection import SessionLocal
from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.binance.vo.ohlcv.filter import OhlcvFilterVo

class OhlcvRepository:
    def __init__(self):
        self.TABLE_NAME = "ohlcv"
    
    # row count 관련해서는 추후에 수정
    async def insert_ohlcv(self, vo: DefaultOhlcvVo) -> int:
        data = vo.model_dump()
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
    
    async def insert_ohlcv_bulk(self, vo: List[DefaultOhlcvVo]) -> int:
        rowcount = await common_insert_bulk(self.TABLE_NAME, vo)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount
    
    async def select_ohlcv(self, vo: OhlcvFilterVo) -> List[DefaultOhlcvVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultOhlcvVo)

    async def select_recent_ohlcv(self, symbol_id: str, interval: str, limit: int) -> List[DefaultOhlcvVo]:
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
            return [DefaultOhlcvVo(**r) for r in rows]

    async def select_count_total_candles(self) -> int:
        sql = text(
            f"""
            SELECT COUNT(*) FROM {self.TABLE_NAME}
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {}
            )
            ret = result.mappings().all()
            return ret[0]['count']

    async def delete_candles(self, limit: int, symbol: str) -> int:
        sql = text(
            f"""
            DELETE FROM ohlcv
            WHERE id IN (
                SELECT id
                FROM ohlcv
                WHERE SYMBOL_ID LIKE :symbol
                LIMIT :limit
            )
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {'symbol': symbol, 'limit': limit}
            )
            print(result.rowcount)
            await session.commit()