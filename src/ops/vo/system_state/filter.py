from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class SystemStateFilterVo(Vo):
    id: Optional[int] = None
    trading_enabled: Optional[bool] = None
    updated_by: Optional[str] = None
    since_ts: Optional[datetime] = None
