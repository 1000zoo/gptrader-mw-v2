from datetime import timedelta, datetime, timezone

from loguru import logger
from typing import List, Optional

from src.job.repository.job.job_run_repo import JobRunRepository
from src.job.vo.job.default import DefaultJobRunVo
from src.job.vo.job.filter import JobRunFilterVo
from src.common.constants.job_constants import JOB_TYPE_POSITION_OPEN_FAIL
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.repository_error import RepositoryError
from sqlalchemy.exc import SQLAlchemyError

class JobRunService:
    def __init__(self):
        self.repository = JobRunRepository()

    async def create_job_run(self, vo: DefaultJobRunVo) -> int:
        try:
            return await self.repository.insert_job_run(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to create job run.") from e

    async def get_job_runs(self, vo: JobRunFilterVo) -> List[DefaultJobRunVo]:
        try:
            return await self.repository.select_job_runs(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch job runs.") from e

    async def update_job_run(self, vo: DefaultJobRunVo) -> int:
        try:
            origin_vo = await self.repository.select_job_runs(JobRunFilterVo(batch_id=vo.batch_id))
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch job run for update.") from e
        if len(origin_vo) == 0:
            logger.error(f"can't find batch_id: {vo.batch_id}, skip update")
            raise DataNotFoundException(f"Job run not found for batch_id={vo.batch_id}.")
        try:
            await self.repository.insert_job_run_hist(origin_vo[0])
            return await self.repository.update_job_run(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to update job run.") from e

    async def delete_job_run(self, batch_id: str) -> int:
        try:
            origin_vo = await self.repository.select_job_runs(JobRunFilterVo(batch_id=batch_id))
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch job run for delete.") from e
        if len(origin_vo) == 0:
            logger.error(f"can't find batch_id: {batch_id}, skip delete")
            raise DataNotFoundException(f"Job run not found for batch_id={batch_id}.")
        try:
            await self.repository.insert_job_run_hist(origin_vo[0])
            return await self.repository.delete_job_run(batch_id)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to delete job run.") from e

    async def get_running_batch_ids(self, job_type: Optional[str] = None) -> List[str]:
        filter_vo = JobRunFilterVo(job_type=job_type)
        try:
            results = await self.repository.select_job_runs(filter_vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch running batch ids.") from e
        return [row.batch_id for row in results if row.batch_id]

    async def get_current_batch_id(self, job_type: Optional[str] = None) -> Optional[str]:
        batch_ids = await self.get_running_batch_ids(job_type=job_type)
        if not batch_ids:
            raise DataNotFoundException("No running batch ids found.")
        return batch_ids[0]

    async def get_newest_job(self, symbol_id: Optional[str] = None) -> Optional[DefaultJobRunVo]:
        try:
            job = await self.repository.select_newest_job(symbol_id)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch newest job.") from e
        if not job:
            raise DataNotFoundException(f"No newest job found for symbol_id={symbol_id}.")
        return job

    async def get_open_position_job(self, symbol_id) -> Optional[DefaultJobRunVo]:
        try:
            job = await self.repository.select_open_position_job(symbol=symbol_id)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch open position job.") from e
        return job

    async def get_failed_job(self) -> Optional[DefaultJobRunVo]:
        try:
            temp = await self.repository.select_job_runs(JobRunFilterVo(job_type=JOB_TYPE_POSITION_OPEN_FAIL))
            if not temp:
                return None
            max_vo = max(temp, key=lambda x: x.reg_dt or "0")
            if max_vo.reg_dt > datetime.now(timezone.utc) - timedelta(minutes=10):
                return max_vo
            await self.delete_job_run(max_vo.batch_id)
            logger.info(f"delete old failed job run : {max_vo.batch_id}")
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch failed jobs.") from e

    async def get_all_old_job(self) -> List[DefaultJobRunVo]:
        try:
            vos = await self.repository.select_old_jobs()
            return vos
        except Exception as e:
            raise RepositoryError("Failed to get jobs.") from e