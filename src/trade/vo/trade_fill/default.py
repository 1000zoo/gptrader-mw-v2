from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class DefaultTradeFillVo(Vo):
    id: Optional[int] = None
    signal_log_id: Optional[int] = None
    symbol_id: Optional[str] = None
    side: Optional[str] = None
    entry_order_id: Optional[str] = None
    entry_price: Optional[float] = None
    entry_qty: Optional[float] = None
    entry_fee: Optional[float] = None
    entry_ts: Optional[datetime] = None
    exit_order_id: Optional[str] = None
    exit_price: Optional[float] = None
    exit_fee: Optional[float] = None
    exit_ts: Optional[datetime] = None
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None
    r_multiple: Optional[float] = None
    slippage_est: Optional[float] = None
    status: Optional[str] = None
    risk_budget_usd: Optional[float] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
        extra = "ignore"
