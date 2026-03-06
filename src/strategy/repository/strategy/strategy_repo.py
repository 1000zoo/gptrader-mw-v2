from typing import List, Optional

from loguru import logger
from sqlalchemy import text

from src.common.db.connection import SessionLocal
from src.common.db.util import common_insert, common_select
from src.strategy.vo.strategy.default import DefaultStrategyVo
from src.strategy.vo.strategy.filter import StrategyFilterVo


class StrategyRepository:
    def __init__(self):
        self.TABLE_NAME = "strategy"
        self.TIMESTAMP_TABLE = "strategy_timeframe"

    async def insert_strategy(self, vo: DefaultStrategyVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_strategies(self, vo: StrategyFilterVo) -> List[DefaultStrategyVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultStrategyVo)

    async def select_strategy_by_name(
        self, strategy_name: str, only_active: bool = True
    ) -> Optional[DefaultStrategyVo]:
        where_use = "AND use_yn = 'Y'" if only_active else ""
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE strategy_name = :strategy_name
            {where_use}
            ORDER BY id DESC
            LIMIT 1
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"strategy_name": strategy_name})
            row = result.mappings().first()
            if not row:
                return None
            return DefaultStrategyVo(**row)

    async def select_top_active_strategy(self) -> Optional[DefaultStrategyVo]:
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE use_yn = 'Y'
            ORDER BY priority ASC NULLS LAST, id ASC
            LIMIT 1
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql)
            row = result.mappings().first()
            if not row:
                return None
            return DefaultStrategyVo(**row)

    async def update_strategy(self, vo: DefaultStrategyVo) -> int:
        data = vo.model_dump(exclude_none=True)
        strategy_name = data.pop("strategy_name", None)
        data.pop("id", None)
        data.pop("reg_dt", None)

        if not strategy_name:
            raise ValueError("strategy_name is required for update")
        if not data:
            return 0

        set_clause = ", ".join([f"{key} = :{key}" for key in data.keys()])
        sql = text(
            f"""
            UPDATE {self.TABLE_NAME}
            SET {set_clause},
                upd_dt = NOW()
            WHERE strategy_name = :strategy_name
            """
        )
        data["strategy_name"] = strategy_name

        async with SessionLocal() as session:
            result = await session.execute(sql, data)
            await session.commit()
            return result.rowcount

    async def delete_strategy(self, strategy_name: str) -> int:
        sql = text(f"DELETE FROM {self.TABLE_NAME} WHERE strategy_name = :strategy_name")
        async with SessionLocal() as session:
            result = await session.execute(sql, {"strategy_name": strategy_name})
            await session.commit()
            return result.rowcount

    async def find_timestamp(self, strategy_name: str) -> Optional[List[str]]:
        sql = text(f"SELECT timeframe FROM {self.TIMESTAMP_TABLE} WHERE strategy_name = :strategy_name")
        async with SessionLocal() as session:
            result = await session.execute(sql, {"strategy_name": strategy_name})
            return result.mappings().all()