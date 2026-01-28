from pydantic import BaseModel
from typing import List, Dict

from src.common.model.base import Meta, OhlcvMeta
from src.common.model.params import IndParams


class IndicatorRequest(BaseModel):
    ohlcvMeta: OhlcvMeta
    indParams: IndParams = IndParams()
    ohlcv: List[Dict] = None

class AnalyzeRequest(BaseModel):
    ohlcvMeta: OhlcvMeta
    ohlcv: List[Dict]
    indicators: List[Dict]
    indParams: IndParams = IndParams()

class TradeRequest(BaseModel):
    symbol: str
    side: str
    percent: float
    leverage: float
    tp: float
    sl: float

class TradeCloseRequest(BaseModel):
    symbol: str