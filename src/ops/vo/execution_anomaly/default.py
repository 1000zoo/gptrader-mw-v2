from typing import Optional, Any
from datetime import datetime

from src.common.model.base import Vo


class DefaultExecutionAnomalyVo(Vo):
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    run_id: Optional[str] = None
    symbol_id: Optional[str] = None
    anomaly_type: Optional[str] = None
    severity: Optional[str] = None
    signal_log_id: Optional[int] = None
    trade_fill_id: Optional[int] = None
    order_id: Optional[str] = None
    payload: Optional[Any] = None

    class Config:
        from_attributes = True
        extra = "ignore"
