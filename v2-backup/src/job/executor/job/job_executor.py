from loguru import logger
from typing import List, Optional

from src.binance.vo.symbol.default import DefaultSymbolVo
from src.job.service.job.job_run_service import JobRunService
from src.job.vo.job.default import DefaultJobRunVo
from src.job.vo.job.filter import JobRunFilterVo
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.repository_error import RepositoryError

class JobExecutor:
    def __init__(self):
        self.jobService = JobRunService()

    async def create_job_run(self, vo: DefaultJobRunVo) -> int:
        try:
            return await self.jobService.create_job_run(vo)
        except (DataNotFoundException, InvalidRequestException) as e:
            logger.warning(f"jobController.create_job_run: {e}")
            return 0
        except (ExternalApiError, RepositoryError) as e:
            logger.error(f"jobController.create_job_run: {e}")
            raise

    async def get_job_runs(self, vo: JobRunFilterVo) -> List[DefaultJobRunVo]:
        try:
            return await self.jobService.get_job_runs(vo)
        except DataNotFoundException as e:
            logger.warning(f"jobController.get_job_runs: {e}")
            return []
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"jobController.get_job_runs: {e}")
            raise

    async def update_job_run(self, vo: DefaultJobRunVo) -> int:
        try:
            return await self.jobService.update_job_run(vo)
        except DataNotFoundException as e:
            logger.warning(f"jobController.update_job_run: {e}")
            return 0
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"jobController.update_job_run: {e}")
            raise

    async def delete_job_run(self, batch_id: str) -> int:
        try:
            return await self.jobService.delete_job_run(batch_id)
        except DataNotFoundException as e:
            logger.warning(f"jobController.delete_job_run: {e}")
            return 0
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"jobController.delete_job_run: {e}")
            raise

    async def get_running_batch_ids(self, job_type: Optional[str] = None) -> List[str]:
        try:
            return await self.jobService.get_running_batch_ids(job_type=job_type)
        except DataNotFoundException as e:
            logger.warning(f"jobController.get_running_batch_ids: {e}")
            return []
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"jobController.get_running_batch_ids: {e}")
            raise

    async def get_current_batch_id(self, job_type: Optional[str] = None) -> Optional[str]:
        try:
            return await self.jobService.get_current_batch_id(job_type=job_type)
        except DataNotFoundException as e:
            logger.warning(f"jobController.get_current_batch_id: {e}")
            return None
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"jobController.get_current_batch_id: {e}")
            raise

    async def get_newest_job(self, symbol: DefaultSymbolVo):
        try:
            return await self.jobService.get_newest_job(symbol_id=symbol.symbol_id)
        except DataNotFoundException as e:
            logger.warning(f"jobController.get_newest_job: {e}")
            return None
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"jobController.get_newest_job: {e}")
            raise

    async def get_failed_job(self) -> Optional[DefaultJobRunVo]:
        try:
            vo = await self.jobService.get_failed_job()
            return vo
        except DataNotFoundException as e:
            logger.warning(f"jobController.get_failed_job: {e}")
            return None
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"jobController.get_failed_job: {e}")
            raise

    async def delete_all_old_job(self):
        try:
            vos = await self.jobService.get_all_old_job()
            for vo in vos:
                await self.jobService.delete_job_run(vo.batch_id)
                logger.info(f"delete old job: {vo.batch_id}")
        except Exception as e:
            logger.error(f"jobController.delete_all_old_job: {e}")
            raise e