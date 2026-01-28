from typing import List, Optional

from loguru import logger
from sqlalchemy import text

from src.common.db.util import common_insert, common_select
from src.common.db.connection import SessionLocal
from src.signal.vo.signal_log.default import DefaultSignalLogVo
from src.signal.vo.signal_log.filter import SignalLogFilterVo


class SignalLogRepository:
    def __init__(self):
        self.TABLE_NAME = "signal_log"

    async def insert_signal_log(self, vo: DefaultSignalLogVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_signal_logs(self, vo: SignalLogFilterVo) -> List[DefaultSignalLogVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultSignalLogVo)

    async def select_latest_by_run_id(
        self, run_id: str, symbol_id: Optional[str] = None
    ) -> Optional[DefaultSignalLogVo]:
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE run_id = :run_id
            {"AND symbol_id = :symbol_id" if symbol_id else ""}
            ORDER BY created_at DESC
            LIMIT 1
            """
        )
        params = {"run_id": run_id}
        if symbol_id:
            params["symbol_id"] = symbol_id
        async with SessionLocal() as session:
            result = await session.execute(sql, params)
            rows = result.mappings().all()
            if not rows:
                return None
            return DefaultSignalLogVo(**rows[0])

    async def update_gate_decision(self, signal_log_id: int, allowed: bool, reason: Optional[str]) -> int:
        sql = text(
            f"""
            UPDATE {self.TABLE_NAME}
            SET gate_allowed = :gate_allowed,
                gate_rejected_reason = :gate_rejected_reason
            WHERE id = :signal_log_id
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {
                    "gate_allowed": allowed,
                    "gate_rejected_reason": reason,
                    "signal_log_id": signal_log_id,
                },
            )
            await session.commit()
            return result.rowcount

    async def update_calibration_fields(
        self,
        signal_log_id: int,
        calibrated_confidence: Optional[float],
        dynamic_threshold_used: Optional[float],
    ) -> int:
        sql = text(
            f"""
            UPDATE {self.TABLE_NAME}
            SET calibrated_confidence = :calibrated_confidence,
                dynamic_threshold_used = :dynamic_threshold_used
            WHERE id = :signal_log_id
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {
                    "calibrated_confidence": calibrated_confidence,
                    "dynamic_threshold_used": dynamic_threshold_used,
                    "signal_log_id": signal_log_id,
                },
            )
            await session.commit()
            return result.rowcount
