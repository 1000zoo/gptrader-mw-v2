from datetime import datetime, timezone
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

    async def enable_trading(
        self,
        reason: Optional[str] = None,
        updated_by: str = "manual",
        since_ts: Optional[datetime] = None,
    ) -> int:
        return await self._create_state(
            trading_enabled=True,
            reason=reason,
            updated_by=updated_by,
            since_ts=since_ts,
        )

    async def disable_trading(
        self,
        reason: Optional[str] = None,
        updated_by: str = "manual",
        since_ts: Optional[datetime] = None,
    ) -> int:
        return await self._create_state(
            trading_enabled=False,
            reason=reason,
            updated_by=updated_by,
            since_ts=since_ts,
        )

    async def is_trading_enabled(self) -> bool:
        latest_state = await self.find_latest_state()
        if latest_state and latest_state.trading_enabled is False:
            return False
        return True

    async def _create_state(
        self,
        trading_enabled: bool,
        reason: Optional[str],
        updated_by: str,
        since_ts: Optional[datetime],
    ) -> int:
        payload = DefaultSystemStateVo(
            trading_enabled=trading_enabled,
            reason=reason,
            since_ts=since_ts or datetime.now(timezone.utc),
            updated_by=updated_by,
        )
        return await self.create_system_state(payload)
