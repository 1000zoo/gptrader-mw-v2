from datetime import datetime
from typing import List, Optional

from loguru import logger
from sqlalchemy import text

from src.common.db.connection import SessionLocal
from src.common.db.util import common_insert, common_select
from src.job.vo.job.default import DefaultJobRunVo
from src.job.vo.job.filter import JobRunFilterVo
from src.common.constants.job_constants import JOB_TYPE_POSITION_OPEN, JOB_TYPE_POSITION_CLOSED

class JobRunRepository:
    def __init__(self):
        self.TABLE_NAME = "job_run"
        self.HIST_TABLE_NAME = "job_run_hist"

    async def insert_job_run(self, vo: DefaultJobRunVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def insert_job_run_hist(self, vo: DefaultJobRunVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.HIST_TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_job_runs(self, vo: JobRunFilterVo) -> List[DefaultJobRunVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultJobRunVo)

    async def update_job_run(self, vo: DefaultJobRunVo) -> int:
        data = vo.model_dump(exclude_none=True)
        batch_id = data.pop("batch_id", None)
        if not batch_id:
            raise ValueError("batch_id is required for update")
        if not data:
            return 0

        set_clause = ", ".join([f"{key} = :{key}" for key in data.keys()])
        sql = text(f"""
        UPDATE {self.TABLE_NAME}
        SET {set_clause},
            upd_dt = NOW()
        WHERE batch_id = :batch_id
        """)
        data["batch_id"] = batch_id

        async with SessionLocal() as session:
            result = await session.execute(sql, data)
            await session.commit()
            return result.rowcount

    async def delete_job_run(self, batch_id: str) -> int:
        sql = text(f"DELETE FROM {self.TABLE_NAME} WHERE batch_id = :batch_id")
        async with SessionLocal() as session:
            result = await session.execute(sql, {"batch_id": batch_id})
            await session.commit()
            return result.rowcount

    async def select_open_position_job(self, symbol: str) -> Optional[DefaultJobRunVo]:
        sql = text(f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE 1=1
                AND symbol_id = :symbol
                AND job_type in ('{JOB_TYPE_POSITION_OPEN}', '{JOB_TYPE_POSITION_CLOSED}')
        """)
        async with SessionLocal() as session:
            result = await session.execute(sql, {"symbol": symbol})
            if not result:
                return None
            r = result.mappings().all()
            if not r:
                return None
            return DefaultJobRunVo(**r[0])


    async def select_newest_job(self, symbol: str) -> Optional[DefaultJobRunVo]:
        sql = text(f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE 1=1
                AND symbol_id = :symbol
            ORDER BY UPD_DT DESC
            LIMIT 1
        """)
        async with SessionLocal() as session:
            result = await session.execute(sql, {"symbol": symbol})
            if not result:
                return None
            r = result.mappings().all()
            if not r:
                return None
            return DefaultJobRunVo(**r[0])

    async def select_old_jobs(self) -> List[DefaultJobRunVo]:
        sql = text(f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE 1=1
                AND reg_dt <= now() - INTERVAL '1 hour'
        """)
        async with SessionLocal() as session:
            result = await session.execute(sql)
            rows = result.mappings().all()
            if not rows:
                return []
            return [DefaultJobRunVo(**r) for r in rows]