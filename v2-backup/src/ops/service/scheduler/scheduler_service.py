from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from src.common.exception.repository_error import RepositoryError
from src.ops.repository.scheduler.scheduler_repo import SchedulerRepository
from src.ops.vo.scheduler.default import DefaultSchedulerVo
from src.ops.vo.scheduler.filter import SchedulerFilterVo


class SchedulerService:
    def __init__(self):
        self.repository = SchedulerRepository()

    async def create_scheduler(self, vo: DefaultSchedulerVo) -> int:
        try:
            return await self.repository.insert_scheduler(vo)
        except (SQLAlchemyError, ValueError) as exc:
            raise RepositoryError("Failed to insert scheduler.") from exc

    async def find_schedulers(self, vo: SchedulerFilterVo) -> List[DefaultSchedulerVo]:
        try:
            return await self.repository.select_schedulers(vo)
        except (SQLAlchemyError, ValueError) as exc:
            raise RepositoryError("Failed to select scheduler.") from exc

    async def find_by_name(self, name: str) -> Optional[DefaultSchedulerVo]:
        try:
            return await self.repository.select_by_name(name)
        except (SQLAlchemyError, ValueError) as exc:
            raise RepositoryError("Failed to select scheduler by name.") from exc

    async def is_valid_scheduler(self, name: str) -> bool:
        try:
            vo = await self.find_by_name(name)
            return vo.state == 'Y'
        except RepositoryError as e:
            return False