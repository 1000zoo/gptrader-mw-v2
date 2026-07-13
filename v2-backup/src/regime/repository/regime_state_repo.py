from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from src.common.db.connection import SessionLocal
from src.regime.vo.default import DefaultRegimeStateVo


class RegimeStateRepository:
    TABLE_NAME = "regime_state"

    async def select_by_symbol(self, symbol_id: str) -> Optional[DefaultRegimeStateVo]:
        sql = text(
            f"""
            SELECT *
            FROM {self.TABLE_NAME}
            WHERE symbol_id = :symbol_id
            LIMIT 1
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"symbol_id": symbol_id})
            row = result.mappings().first()
            return DefaultRegimeStateVo(**row) if row else None

    async def upsert(self, vo: DefaultRegimeStateVo) -> None:
        payload = vo.model_dump(exclude_none=True)
        sql = text(
            f"""
            INSERT INTO {self.TABLE_NAME} (
                symbol_id, timeframe, regime, pending_regime, pending_count,
                trend_strength, range_strength, transition_risk,
                adx, atr, bb_bandwidth, ema_gap,
                computed_at, confirmed_at
            ) VALUES (
                :symbol_id, :timeframe, :regime, :pending_regime, :pending_count,
                :trend_strength, :range_strength, :transition_risk,
                :adx, :atr, :bb_bandwidth, :ema_gap,
                :computed_at, :confirmed_at
            )
            ON CONFLICT (symbol_id) DO UPDATE SET
                timeframe = EXCLUDED.timeframe,
                regime = EXCLUDED.regime,
                pending_regime = EXCLUDED.pending_regime,
                pending_count = EXCLUDED.pending_count,
                trend_strength = EXCLUDED.trend_strength,
                range_strength = EXCLUDED.range_strength,
                transition_risk = EXCLUDED.transition_risk,
                adx = EXCLUDED.adx,
                atr = EXCLUDED.atr,
                bb_bandwidth = EXCLUDED.bb_bandwidth,
                ema_gap = EXCLUDED.ema_gap,
                computed_at = EXCLUDED.computed_at,
                confirmed_at = EXCLUDED.confirmed_at,
                upd_dt = NOW()
            """
        )
        async with SessionLocal() as session:
            await session.execute(sql, payload)
            await session.commit()
