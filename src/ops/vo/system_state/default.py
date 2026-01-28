from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class DefaultSystemStateVo(Vo):
    id: Optional[int] = None
    trading_enabled: Optional[bool] = None
    reason: Optional[str] = None
    since_ts: Optional[datetime] = None
    updated_by: Optional[str] = None
    reg_dt: Optional[datetime] = None
    upd_dt: Optional[datetime] = None

    class Config:
        from_attributes = True
        extra = "ignore"
