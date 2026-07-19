from typing import List

from sqlalchemy.exc import SQLAlchemyError

from src.common.exception.repository_error import RepositoryError
from src.calibration.repository.confidence_calibration.confidence_calibration_repo import ConfidenceCalibrationRepository
from src.calibration.vo.confidence_calibration.default import DefaultConfidenceCalibrationVo
from src.calibration.vo.confidence_calibration.filter import ConfidenceCalibrationFilterVo


class ConfidenceCalibrationService:
    def __init__(self):
        self.repository = ConfidenceCalibrationRepository()

    async def create_confidence_calibration(self, vo: DefaultConfidenceCalibrationVo) -> int:
        try:
            return await self.repository.insert_confidence_calibration(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert confidence_calibration.") from e

    async def find_confidence_calibrations(
        self, vo: ConfidenceCalibrationFilterVo
    ) -> List[DefaultConfidenceCalibrationVo]:
        try:
            return await self.repository.select_confidence_calibrations(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select confidence_calibration.") from e
