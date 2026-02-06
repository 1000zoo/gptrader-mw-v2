from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class DefaultSlackSettingVo(Vo):
    id: Optional[int] = None
    process_name: Optional[str] = None
    channel_name: Optional[str] = None
    webhook_url: Optional[str] = None
    is_active: Optional[bool] = None
    reg_dt: Optional[datetime] = None
    upd_dt: Optional[datetime] = None

    class Config:
        from_attributes = True
        extra = "ignore"
