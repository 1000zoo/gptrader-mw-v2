from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class DefaultJobRunVo(Vo):
    batch_id: Optional[str] = None
    job_type: Optional[str] = None
    reg_ymd: Optional[str] = None
    target_interval: Optional[str] = None
    symbol_id: Optional[str] = None
    status: Optional[str] = None
    main_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None

    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True
        extra = "ignore"
