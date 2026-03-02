from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class SchedulerFilterVo(Vo):
    id: Optional[int] = None
    name: Optional[str] = None
    state: Optional[str] = None
    last_run_dt: Optional[datetime] = None
    use_yn: Optional[bool] = None
