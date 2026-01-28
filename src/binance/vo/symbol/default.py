from typing import Optional

from src.common.model.base import Vo


class DefaultSymbolVo(Vo):
    symbol_id: str

    symbol_name: Optional[str] = None
    price_precision: Optional[int] = None
    quantity_precision: Optional[int] = None

    tick_size: Optional[float] = None
    step_size: Optional[float] = None

    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_qty: Optional[float] = None
    max_qty: Optional[float] = None

    ## attr1: use_yn
    ## attr2: today symbol num (increase when batch start, reset next day)

    class Config:
        from_attributes = True