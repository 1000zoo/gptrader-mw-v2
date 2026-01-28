from typing import List, Optional

from loguru import logger
from sqlalchemy import text

from src.common.db.util import common_insert, common_select
from src.common.db.connection import SessionLocal
from src.ops.vo.system_state.default import DefaultSystemStateVo
from src.ops.vo.system_state.filter import SystemStateFilterVo


class SystemStateRepository:
    def __init__(self):
        self.TABLE_NAME = "system_state"

    async def insert_system_state(self, vo: DefaultSystemStateVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_system_states(self, vo: SystemStateFilterVo) -> List[DefaultSystemStateVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultSystemStateVo)

    async def select_latest_state(self) -> Optional[DefaultSystemStateVo]:
        sql = text(f"SELECT * FROM {self.TABLE_NAME} ORDER BY reg_dt DESC LIMIT 1")
        async with SessionLocal() as session:
            result = await session.execute(sql)
            rows = result.mappings().all()
            if not rows:
                return None
            return DefaultSystemStateVo(**rows[0])
