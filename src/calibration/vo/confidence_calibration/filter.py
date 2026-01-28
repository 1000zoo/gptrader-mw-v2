from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class ConfidenceCalibrationFilterVo(Vo):
    id: Optional[int] = None
    c_interval: Optional[str] = None
    symbol_id: Optional[str] = None
    bucket_from: Optional[float] = None
    bucket_to: Optional[float] = None
    created_at: Optional[datetime] = None
