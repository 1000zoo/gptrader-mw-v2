from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class JobRunFilterVo(Vo):
    batch_id: Optional[str] = None
    job_type: Optional[str] = None
    symbol_id: Optional[str] = None
    reg_ymd: Optional[str] = None
    target_interval: Optional[str] = None
    status: Optional[str] = None

    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
