from typing import Optional, Any
from datetime import datetime

from src.common.model.base import Vo


class DefaultBacktestResultVo(Vo):
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    config: Optional[Any] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    pnl_usd: Optional[float] = None
    sharpe: Optional[float] = None
    pf: Optional[float] = None
    mdd: Optional[float] = None
    trades: Optional[int] = None
    winrate: Optional[float] = None
    turnover: Optional[float] = None

    class Config:
        from_attributes = True
        extra = "ignore"
