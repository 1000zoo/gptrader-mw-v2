from typing import List

from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from src.common.exception.repository_error import RepositoryError
from src.ops.repository.execution_anomaly.execution_anomaly_repo import ExecutionAnomalyRepository
from src.ops.vo.execution_anomaly.default import DefaultExecutionAnomalyVo
from src.ops.vo.execution_anomaly.filter import ExecutionAnomalyFilterVo


class ExecutionAnomalyService:
    def __init__(self):
        self.repository = ExecutionAnomalyRepository()

    async def create_execution_anomaly(self, vo: DefaultExecutionAnomalyVo) -> int:
        try:
            return await self.repository.insert_execution_anomaly(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert execution_anomaly.") from e

    async def find_execution_anomalies(self, vo: ExecutionAnomalyFilterVo) -> List[DefaultExecutionAnomalyVo]:
        try:
            return await self.repository.select_execution_anomalies(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select execution_anomaly.") from e

    async def count_recent_anomalies(self, since_ts: datetime) -> int:
        try:
            return await self.repository.count_recent_anomalies(since_ts)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to count execution_anomaly.") from e
