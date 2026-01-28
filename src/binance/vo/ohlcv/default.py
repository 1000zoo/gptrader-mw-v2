from typing import Optional, Dict, Any

from src.common.model.base import Vo
from datetime import datetime


class DefaultOhlcvVo(Vo):

    id: Optional[int] = None

    batch_id: Optional[str]
    reg_ymd: Optional[str]
    symbol_id: Optional[str]

    c_interval: Optional[str]
    c_limit: Optional[int]
    seq_no: Optional[int] = None        # 1 ~ c_limit

    ts: Optional[datetime] = None       # candle timestamp

    c_open: Optional[float] = None
    c_high: Optional[float] = None
    c_low: Optional[float] = None
    c_close: Optional[float] = None

    volume: Optional[float] = None
    quote_volume: Optional[float] = None

    class Config:
        from_attributes = True
        extra = "ignore"
    
    def dump_for_prompt(self) -> Dict[str, Any]:
        return {
            "timestamp": self.ts,
            "open": self.c_open,
            "high": self.c_high,
            "low": self.c_low,
            "close": self.c_close,
            "qutoe_volume": self.quote_volume
        }