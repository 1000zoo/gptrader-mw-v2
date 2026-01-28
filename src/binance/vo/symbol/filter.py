from typing import Optional

from src.common.model.base import Vo
from src.binance.vo.symbol.default import DefaultSymbolVo

class SymbolFilterVo(Vo):
    symbol_id: Optional[str] = None

    symbol_name: Optional[str] = None
    price_precision: Optional[int] = None
    quantity_precision: Optional[int] = None

    tick_size: Optional[float] = None
    step_size: Optional[float] = None

    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_qty: Optional[float] = None
    max_qty: Optional[float] = None

    class Config:
        from_attributes = True