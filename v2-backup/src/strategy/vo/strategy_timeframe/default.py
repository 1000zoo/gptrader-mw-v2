from typing import Optional

from src.common.model.base import Vo
from src.common.model.types import TF


class DefaultStrategyTimeframeVo(Vo):
    strategy_name: str
    timeframe: Optional[TF] = None
    lookback: Optional[int] = None
    c_limit: int = 150