from typing import List

from loguru import logger

from src.common.db.util import common_insert, common_select
from src.calibration.vo.confidence_calibration.default import DefaultConfidenceCalibrationVo
from src.calibration.vo.confidence_calibration.filter import ConfidenceCalibrationFilterVo


class ConfidenceCalibrationRepository:
    def __init__(self):
        self.TABLE_NAME = "confidence_calibration"

    async def insert_confidence_calibration(self, vo: DefaultConfidenceCalibrationVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_confidence_calibrations(self, vo: ConfidenceCalibrationFilterVo) -> List[DefaultConfidenceCalibrationVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultConfidenceCalibrationVo)
