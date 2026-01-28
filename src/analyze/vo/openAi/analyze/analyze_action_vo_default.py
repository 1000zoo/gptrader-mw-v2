from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from src.common.model.base import Vo


class DefaultAnalyzeActionVo(Vo):
    id: Optional[int] = None

    reg_ymd: Optional[str] = None          # '20251225'
    batch_id: Optional[str] = None
    symbol_id: Optional[str] = None

    side: Optional[str] = None             # 'LONG', 'SHORT', 'NONE'
    entry_price: Optional[float] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    confidence: Optional[float] = None     # 0~100 or 0~1 (너 기준)

    reason: Optional[str] = None

    class Config:
        from_attributes = True
        extra = "ignore"