
from datetime import datetime
from typing import List, Dict, Any, Optional
from loguru import logger

from src.common.db.util import common_insert_bulk, common_insert, common_select
from src.analyze.vo.openAi.analyze.analyze_action_vo_default import DefaultAnalyzeActionVo
from src.analyze.vo.openAi.analyze.analyze_action_vo_filter import AnalyzeActionFilterVo

class AnalyzeActionRepository:
    def __init__(self):
        self.TABLE_NAME = "analyze_action"

    async def insert_action_bulk(self, vo: List[DefaultAnalyzeActionVo]) -> Any:
        rowcount = await common_insert_bulk(self.TABLE_NAME, vo)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def insert_action(self, vo: DefaultAnalyzeActionVo) -> Any:
        rowcount = await common_insert(self.TABLE_NAME, vo.model_dump(exclude_none=True))
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_action(self, vo: AnalyzeActionFilterVo) -> Optional[DefaultAnalyzeActionVo]:
        actions = await common_select(self.TABLE_NAME, vo, DefaultAnalyzeActionVo)
        if not actions:
            return None
        latest_action = max(actions, key=lambda action: action.reg_dt or action.upd_dt or datetime.min)
        if len(actions) > 1:
            logger.warning(
                "multiple analyze actions found, returning newest batch_id={} (reg_dt={})",
                latest_action.batch_id,
                latest_action.reg_dt,
            )
        return latest_action
