from typing import Optional

from pydantic import BaseModel


class TradeExecuteDto(BaseModel):
    symbol_id: str
    side: str
    entry_price: Optional[float] = None
    tp: Optional[float] = None
    sl: Optional[float] = None
    confidence: Optional[float] = None
    reason: Optional[str] = None
    batch_id: Optional[str] = None
    signal_log_id: Optional[int] = None
    c_interval: Optional[str] = None
