from typing import List, Optional

from sqlalchemy import text

from src.common.db.connection import SessionLocal


class CalibrationRepository:
    async def fetch_trade_outcomes(
        self, c_interval: str, symbol_id: Optional[str] = None
    ) -> List[dict]:
        sql = text(
            """
            SELECT
                sl.raw_confidence,
                tf.pnl_usd,
                tf.r_multiple
            FROM trade_fill tf
            JOIN signal_log sl ON tf.signal_log_id = sl.id
            WHERE tf.status = 'CLOSED'
              AND sl.c_interval = :c_interval
              AND (:symbol_id IS NULL OR sl.symbol_id = :symbol_id)
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"c_interval": c_interval, "symbol_id": symbol_id})
            return [dict(r) for r in result.mappings().all()]
