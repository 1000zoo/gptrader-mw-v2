from typing import List

from loguru import logger
from sqlalchemy import text

from src.common.db.util import common_insert, common_select
from src.common.db.connection import SessionLocal
from src.ops.vo.execution_anomaly.default import DefaultExecutionAnomalyVo
from src.ops.vo.execution_anomaly.filter import ExecutionAnomalyFilterVo


class ExecutionAnomalyRepository:
    def __init__(self):
        self.TABLE_NAME = "execution_anomaly"

    async def insert_execution_anomaly(self, vo: DefaultExecutionAnomalyVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_execution_anomalies(self, vo: ExecutionAnomalyFilterVo) -> List[DefaultExecutionAnomalyVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultExecutionAnomalyVo)

    async def count_recent_anomalies(self, since_ts) -> int:
        sql = text(
            f"""
            SELECT COUNT(*) AS cnt FROM {self.TABLE_NAME}
            WHERE created_at >= :since_ts
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"since_ts": since_ts})
            row = result.mappings().first()
            if not row:
                return 0
            return int(row.get("cnt", 0))
