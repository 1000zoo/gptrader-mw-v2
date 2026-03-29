from typing import List, Optional

from loguru import logger
from sqlalchemy import text

from src.common.db.connection import SessionLocal
from src.common.db.util import common_insert, common_select
from src.ops.vo.slack_setting.default import DefaultSlackSettingVo
from src.ops.vo.slack_setting.filter import SlackSettingFilterVo


class SlackSettingRepository:
    def __init__(self):
        self.TABLE_NAME = "slack_setting"

    async def insert_slack_setting(self, vo: DefaultSlackSettingVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_slack_settings(self, vo: SlackSettingFilterVo) -> List[DefaultSlackSettingVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultSlackSettingVo)

    async def select_active_by_process(self, process_name: str) -> Optional[DefaultSlackSettingVo]:
        sql = text(
            "SELECT * FROM slack_setting "
            "WHERE process_name = :process_name AND is_active = 'Y' "
            "ORDER BY reg_dt DESC LIMIT 1"
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"process_name": process_name})
            rows = result.mappings().all()
            if not rows:
                return None
            return DefaultSlackSettingVo(**rows[0])
