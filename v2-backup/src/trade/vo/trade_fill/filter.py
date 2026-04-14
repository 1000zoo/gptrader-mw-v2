from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class TradeFillFilterVo(Vo):
    id: Optional[int] = None
    signal_log_id: Optional[int] = None
    symbol_id: Optional[str] = None
    side: Optional[str] = None
    status: Optional[str] = None
    entry_ts: Optional[datetime] = None
    exit_ts: Optional[datetime] = None
