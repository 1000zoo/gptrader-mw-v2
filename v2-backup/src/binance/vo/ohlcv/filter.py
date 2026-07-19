from typing import Optional

from src.common.model.base import Vo


class OhlcvFilterVo(Vo):

    id: Optional[int] = None

    batch_id: Optional[str] = None      # BTCUSDT202512100001
    reg_ymd: Optional[str] = None       # 20251210
    symbol_id: Optional[str] = None

    c_interval: Optional[str] = None    # '1m', '15m', '1h'
    c_limit: Optional[int] = None       # 200

