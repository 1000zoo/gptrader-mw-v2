import asyncio

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
