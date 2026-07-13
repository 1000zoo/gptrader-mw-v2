from datetime import datetime, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from typing import Dict, List

from src.binance.vo.ohlcv.default import DefaultOhlcvVo

class OHLCVConstants(Enum):
    OPEN_TIME = 0
    OPEN = 1
    HIGH = 2
    LOW = 3
    CLOSE = 4
    VOLUME = 5
    CLOSE_TIME = 6
    QUOTE_ASSET_VOLUME = 7
    NUMBER_OF_TRADES = 8
    TAKER_BUY_BASE_ASSET = 9
    TAKER_BUY_QUOTE_ASSET = 10
    IGNORE = 11

def _to_datetime(ms, tz: str = "Asia/Seoul") -> str:
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return str(dt.astimezone(ZoneInfo(tz)))


def ohlcv_klines_serializer(data: List[Dict], meta: Dict) -> List[Dict]:
    ret = []
    
    for d in data:
        openTime = _to_datetime(d[OHLCVConstants.OPEN_TIME.value])
        closeTime = _to_datetime(d[OHLCVConstants.CLOSE_TIME.value])
        ret.append({
            "symbol": meta["symbol"],
            "interval": meta["interval"],
            "limit": meta["limit"],
            "openTime": openTime,
            "open": d[OHLCVConstants.OPEN.value],
            "high": d[OHLCVConstants.HIGH.value],
            "low": d[OHLCVConstants.LOW.value],
            "close": d[OHLCVConstants.CLOSE.value],
            "closeTime": closeTime,
            "quoteAssetVolume": d[OHLCVConstants.QUOTE_ASSET_VOLUME.value],
            "numberOfTrades": d[OHLCVConstants.NUMBER_OF_TRADES.value],
            "takerBuyBaseAsset": d[OHLCVConstants.TAKER_BUY_BASE_ASSET.value],
            "takerBuyQuoteAsset": d[OHLCVConstants.TAKER_BUY_QUOTE_ASSET.value]
        })

    return ret



