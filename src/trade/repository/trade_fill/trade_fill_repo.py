from datetime import datetime
from typing import List, Optional

from loguru import logger
from sqlalchemy import text

from src.common.db.util import common_insert, common_select
from src.common.db.connection import SessionLocal
from src.trade.vo.trade_fill.default import DefaultTradeFillVo
from src.trade.vo.trade_fill.filter import TradeFillFilterVo


class TradeFillRepository:
    def __init__(self):
        self.TABLE_NAME = "trade_fill"

    async def insert_trade_fill(self, vo: DefaultTradeFillVo) -> int:
        data = vo.model_dump(exclude_none=True)
        rowcount = await common_insert(self.TABLE_NAME, data)
        logger.info(f"INSERT to {self.TABLE_NAME} SUCCESS rowcount > {rowcount}")
        return rowcount

    async def select_trade_fills(self, vo: TradeFillFilterVo) -> List[DefaultTradeFillVo]:
        return await common_select(self.TABLE_NAME, vo, DefaultTradeFillVo)

    async def select_closed_trades_since(self, since_ts: datetime) -> List[DefaultTradeFillVo]:
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE status = 'CLOSED'
              AND exit_ts >= :since_ts
            ORDER BY exit_ts DESC
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"since_ts": since_ts})
            rows = result.mappings().all()
            return [DefaultTradeFillVo(**r) for r in rows]

    async def select_recent_closed_trades(self, limit: int) -> List[DefaultTradeFillVo]:
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE status = 'CLOSED'
            ORDER BY exit_ts DESC
            LIMIT :limit
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"limit": limit})
            rows = result.mappings().all()
            return [DefaultTradeFillVo(**r) for r in rows]

    async def select_by_entry_order_id(self, entry_order_id: str) -> Optional[DefaultTradeFillVo]:
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE entry_order_id = :entry_order_id
            LIMIT 1
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"entry_order_id": entry_order_id})
            row = result.mappings().first()
            if not row:
                return None
            return DefaultTradeFillVo(**row)

    async def select_by_exit_order_id(self, exit_order_id: str) -> Optional[DefaultTradeFillVo]:
        sql = text(
            f"""
            SELECT * FROM {self.TABLE_NAME}
            WHERE exit_order_id = :exit_order_id
            LIMIT 1
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(sql, {"exit_order_id": exit_order_id})
            row = result.mappings().first()
            if not row:
                return None
            return DefaultTradeFillVo(**row)

    async def update_entry_fill(
        self,
        entry_order_id: str,
        entry_price: Optional[float],
        entry_qty: Optional[float],
        entry_fee: Optional[float],
        entry_ts: Optional[datetime],
    ) -> int:
        sql = text(
            f"""
            UPDATE {self.TABLE_NAME}
            SET entry_price = :entry_price,
                entry_qty = :entry_qty,
                entry_fee = :entry_fee,
                entry_ts = :entry_ts,
                upd_dt = NOW()
            WHERE entry_order_id = :entry_order_id
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {
                    "entry_price": entry_price,
                    "entry_qty": entry_qty,
                    "entry_fee": entry_fee,
                    "entry_ts": entry_ts,
                    "entry_order_id": entry_order_id,
                },
            )
            await session.commit()
            return result.rowcount

    async def update_exit_fill(
        self,
        entry_order_id: str,
        exit_order_id: Optional[str],
        exit_price: Optional[float],
        exit_fee: Optional[float],
        exit_ts: Optional[datetime],
        pnl_usd: Optional[float],
        pnl_pct: Optional[float],
        r_multiple: Optional[float],
        status: str,
    ) -> int:
        sql = text(
            f"""
            UPDATE {self.TABLE_NAME}
            SET exit_order_id = :exit_order_id,
                exit_price = :exit_price,
                exit_fee = :exit_fee,
                exit_ts = :exit_ts,
                pnl_usd = :pnl_usd,
                pnl_pct = :pnl_pct,
                r_multiple = :r_multiple,
                status = :status,
                upd_dt = NOW()
            WHERE entry_order_id = :entry_order_id
            """
        )
        async with SessionLocal() as session:
            result = await session.execute(
                sql,
                {
                    "exit_order_id": exit_order_id,
                    "exit_price": exit_price,
                    "exit_fee": exit_fee,
                    "exit_ts": exit_ts,
                    "pnl_usd": pnl_usd,
                    "pnl_pct": pnl_pct,
                    "r_multiple": r_multiple,
                    "status": status,
                    "entry_order_id": entry_order_id,
                },
            )
            await session.commit()
            return result.rowcount
