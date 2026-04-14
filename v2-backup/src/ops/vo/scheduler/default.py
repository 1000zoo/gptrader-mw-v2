from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class DefaultSchedulerVo(Vo):
    id: Optional[int] = None
    name: Optional[str] = None
    state: Optional[str] = None
    last_run_dt: Optional[datetime] = None
    last_run_log: Optional[str] = None
    use_yn: Optional[bool] = None

    class Config:
        from_attributes = True
        extra = "ignore"
