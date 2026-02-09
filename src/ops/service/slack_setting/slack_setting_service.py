from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from src.common.exception.repository_error import RepositoryError
from src.ops.repository.slack_setting.slack_setting_repo import SlackSettingRepository
from src.ops.vo.slack_setting.default import DefaultSlackSettingVo
from src.ops.vo.slack_setting.filter import SlackSettingFilterVo


class SlackSettingService:
    def __init__(self):
        self.repository = SlackSettingRepository()

    async def create_slack_setting(self, vo: DefaultSlackSettingVo) -> int:
        try:
            return await self.repository.insert_slack_setting(vo)
        except (SQLAlchemyError, ValueError) as exc:
            raise RepositoryError("Failed to insert slack_setting.") from exc

    async def find_slack_settings(self, vo: SlackSettingFilterVo) -> List[DefaultSlackSettingVo]:
        try:
            return await self.repository.select_slack_settings(vo)
        except (SQLAlchemyError, ValueError) as exc:
            raise RepositoryError("Failed to select slack_setting.") from exc

    async def find_active_by_process(self, process_name: str) -> Optional[DefaultSlackSettingVo]:
        try:
            return await self.repository.select_active_by_process(process_name)
        except (SQLAlchemyError, ValueError) as exc:
            raise RepositoryError("Failed to select active slack_setting.") from exc
