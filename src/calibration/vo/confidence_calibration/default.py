from typing import Optional
from datetime import datetime

from src.common.model.base import Vo


class DefaultConfidenceCalibrationVo(Vo):
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    c_interval: Optional[str] = None
    symbol_id: Optional[str] = None
    window_n_trades: Optional[int] = None
    bucket_from: Optional[float] = None
    bucket_to: Optional[float] = None
    trades: Optional[int] = None
    winrate: Optional[float] = None
    ev: Optional[float] = None
    avg_r: Optional[float] = None
    pf: Optional[float] = None
    recommended_threshold: Optional[float] = None

    class Config:
        from_attributes = True
        extra = "ignore"
