from typing import List
from pydantic import BaseModel

from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.indicators.vo.indicator.default import DefaultIndicatorVo
from src.common.model.params import IndParams

class AnalyzeInputDto(BaseModel):
    ohlcv: List[DefaultOhlcvVo]
    indicators: List[DefaultIndicatorVo]
    indParams: IndParams