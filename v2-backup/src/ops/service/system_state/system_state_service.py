from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from src.common.exception.repository_error import RepositoryError
from src.ops.repository.system_state.system_state_repo import SystemStateRepository
from src.ops.vo.system_state.default import DefaultSystemStateVo
from src.ops.vo.system_state.filter import SystemStateFilterVo


class SystemStateService:
    def __init__(self):
        self.repository = SystemStateRepository()

    async def create_system_state(self, vo: DefaultSystemStateVo) -> int:
        try:
            return await self.repository.insert_system_state(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert system_state.") from e

    async def find_system_states(self, vo: SystemStateFilterVo) -> List[DefaultSystemStateVo]:
        try:
            return await self.repository.select_system_states(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select system_state.") from e

    async def find_latest_state(self) -> Optional[DefaultSystemStateVo]:
        try:
            return await self.repository.select_latest_state()
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select latest system_state.") from e
