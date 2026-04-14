from datetime import datetime
from typing import Optional

from src.common.model.base import Vo


class OhlcvSummaryFilterVo(Vo):
    id: Optional[int] = None

    batch_id: Optional[str] = None
    reg_ymd: Optional[str] = None
    symbol_id: Optional[str] = None

    c_interval: Optional[str] = None
    c_limit: Optional[int] = None

    start_ts: Optional[datetime] = None
    end_ts: Optional[datetime] = None
