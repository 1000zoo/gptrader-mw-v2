from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from src.common.exception.repository_error import RepositoryError
from src.signal.repository.signal_log.signal_log_repo import SignalLogRepository
from src.signal.vo.signal_log.default import DefaultSignalLogVo
from src.signal.vo.signal_log.filter import SignalLogFilterVo


class SignalLogService:
    def __init__(self):
        self.repository = SignalLogRepository()

    async def create_signal_log(self, vo: DefaultSignalLogVo) -> int:
        try:
            return await self.repository.insert_signal_log(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert signal_log.") from e

    async def find_signal_logs(self, vo: SignalLogFilterVo) -> List[DefaultSignalLogVo]:
        try:
            return await self.repository.select_signal_logs(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select signal_log.") from e

    async def find_latest_by_run_id(
        self, run_id: str, symbol_id: Optional[str] = None
    ) -> Optional[DefaultSignalLogVo]:
        try:
            return await self.repository.select_latest_by_run_id(run_id, symbol_id)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select latest signal_log.") from e

    async def update_gate_decision(self, signal_log_id: int, allowed: bool, reason: Optional[str]) -> int:
        try:
            return await self.repository.update_gate_decision(signal_log_id, allowed, reason)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to update signal_log gate decision.") from e

    async def update_calibration_fields(
        self,
        signal_log_id: int,
        calibrated_confidence: Optional[float],
        dynamic_threshold_used: Optional[float],
    ) -> int:
        try:
            return await self.repository.update_calibration_fields(
                signal_log_id, calibrated_confidence, dynamic_threshold_used
            )
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to update signal_log calibration fields.") from e
