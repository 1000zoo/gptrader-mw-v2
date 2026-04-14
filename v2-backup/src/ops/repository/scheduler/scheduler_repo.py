from typing import List, Optional

from loguru import logger
from sqlalchemy import text

from src.common.db.connection import SessionLocal
from src.common.db.util import common_insert, common_select
from src.ops.vo.scheduler.default import DefaultSchedulerVo
from src.ops.vo.scheduler.filter import SchedulerFilterVo


class SchedulerRepository:
    def __init__(self):
        self.TABLE_NAME = "scheduler"

    async def insert_scheduler(self, vo: DefaultSchedulerVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_schedulers(self, vo: SchedulerFilterVo) -> List[DefaultSchedulerVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultSchedulerVo)

    async def select_by_name(self, name: str) -> Optional[DefaultSchedulerVo]:
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE name = :name and use_yn = 'Y'
            ORDER BY reg_dt DESC LIMIT 1
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"name": name})
            rows = result.mappings().all()
            if not rows:
                return None
            return DefaultSchedulerVo(**rows[0])
