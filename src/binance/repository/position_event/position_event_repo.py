from loguru import logger

from src.common.db.util import common_insert
from src.binance.vo.position_event.default import DefaultPositionEventVo


class PositionEventRepository:
    def __init__(self):
        self.TABLE_NAME = "position_event"

    async def insert_position_event(self, vo: DefaultPositionEventVo) -> int:
        data = vo.model_dump()
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount
