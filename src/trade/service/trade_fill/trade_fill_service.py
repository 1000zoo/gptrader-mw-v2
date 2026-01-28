from typing import List, Optional

from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from src.common.exception.repository_error import RepositoryError
from src.trade.repository.trade_fill.trade_fill_repo import TradeFillRepository
from src.trade.vo.trade_fill.default import DefaultTradeFillVo
from src.trade.vo.trade_fill.filter import TradeFillFilterVo


class TradeFillService:
    def __init__(self):
        self.repository = TradeFillRepository()

    async def create_trade_fill(self, vo: DefaultTradeFillVo) -> int:
        try:
            return await self.repository.insert_trade_fill(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert trade_fill.") from e

    async def find_trade_fills(self, vo: TradeFillFilterVo) -> List[DefaultTradeFillVo]:
        try:
            return await self.repository.select_trade_fills(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select trade_fill.") from e

    async def find_closed_trades_since(self, since_ts: datetime) -> List[DefaultTradeFillVo]:
        try:
            return await self.repository.select_closed_trades_since(since_ts)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select closed trade_fill window.") from e

    async def find_recent_closed_trades(self, limit: int) -> List[DefaultTradeFillVo]:
        try:
            return await self.repository.select_recent_closed_trades(limit)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select recent trade_fill.") from e

    async def find_by_entry_order_id(self, entry_order_id: str) -> Optional[DefaultTradeFillVo]:
        try:
            return await self.repository.select_by_entry_order_id(entry_order_id)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select trade_fill by entry order.") from e

    async def update_entry_fill(
        self,
        entry_order_id: str,
        entry_price: Optional[float],
        entry_qty: Optional[float],
        entry_fee: Optional[float],
        entry_ts: Optional[datetime],
    ) -> int:
        try:
            return await self.repository.update_entry_fill(
                entry_order_id, entry_price, entry_qty, entry_fee, entry_ts
            )
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to update entry trade_fill.") from e

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
        try:
            return await self.repository.update_exit_fill(
                entry_order_id,
                exit_order_id,
                exit_price,
                exit_fee,
                exit_ts,
                pnl_usd,
                pnl_pct,
                r_multiple,
                status,
            )
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to update exit trade_fill.") from e
