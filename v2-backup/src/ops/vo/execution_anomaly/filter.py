from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class ExecutionAnomalyFilterVo(Vo):
    id: Optional[int] = None
    run_id: Optional[str] = None
    symbol_id: Optional[str] = None
    anomaly_type: Optional[str] = None
    severity: Optional[str] = None
    signal_log_id: Optional[int] = None
    trade_fill_id: Optional[int] = None
    created_at: Optional[datetime] = None
