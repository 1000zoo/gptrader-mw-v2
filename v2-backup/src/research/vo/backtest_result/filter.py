from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class BacktestResultFilterVo(Vo):
    id: Optional[int] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    created_at: Optional[datetime] = None
