from typing import List
from loguru import logger
from sqlalchemy import text

from src.common.db.util import common_insert, common_select
from src.common.db.connection import SessionLocal
from src.binance.vo.symbol.default import DefaultSymbolVo
from src.binance.vo.symbol.filter import SymbolFilterVo

class SymbolRepository:
    def __init__(self):
        self.TABLE_NAME = "symbols"
    
    async def insert_symbol(self, vo: DefaultSymbolVo) -> int:
        data = vo.model_dump()
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT SUCCESS rowcount > {rowcount}")

    async def update_symbol(self, vo: DefaultSymbolVo) -> int:
        data = vo.model_dump()
        sql = text("""
        update symbols
        set attr2=:attr2,
            attr3=:attr3
        where 1=1
            and symbol_id=:symbol_id
            and attr1='Y'
        """)
        async with SessionLocal() as session:
            rowcount = await session.execute(sql, data)
            await session.commit()
        return rowcount

    async def select_symbol(self, vo: SymbolFilterVo) -> List[DefaultSymbolVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultSymbolVo)