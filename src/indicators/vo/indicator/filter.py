from typing import Optional

from src.common.model.base import Vo

class IndicatorsFilterVo(Vo):
    id: Optional[int] = None

    reg_ymd: Optional[str] = None           # '20251221'
    symbol_id: Optional[str] = None
    batch_id: Optional[str] = None
    indicator_parameter_id: Optional[int] = None

    c_interval: Optional[str] = None
    c_limit: Optional[int] = None
    seq_no: Optional[int] = None