from typing import Optional, List, Literal

from loguru import logger
from pydantic import BaseModel
from sqlalchemy.util import await_only

from src.binance.service.trader.account_service import AccountService
from src.binance.vo.trader import DefaultAccountPositionVo
from src.job.service.job.job_run_service import JobRunService
from src.job.vo.job.default import DefaultJobRunVo


class JobPosition(BaseModel):
    job: DefaultJobRunVo
    position: DefaultAccountPositionVo

class AccountPreparationUseCase:
    def __init__(self):
        self.account_service = AccountService()
        self.job_service = JobRunService()

    async def get_current_job_position(self) -> Optional[JobPosition]:
        positions: List[DefaultAccountPositionVo] = self.account_service.get_positions()
        if not positions:
            return None
        for position in positions:
            job = await self.job_service.get_open_position_job(position.symbol)
            if job:
                return JobPosition(
                    job=job, position=position
                )
            logger.info(f"has position of {position.symbol} but not job")
        return None