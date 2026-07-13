from src.common.model.base import OhlcvMeta
from src.common.model.request import IndicatorRequest

from src.indicators.mw.indicator.indicator_mw import indicator

def test_indicator_mw():
    ohlcvMeta = OhlcvMeta(symbol="BTCUSDT")
    req = IndicatorRequest(ohlcvMeta=ohlcvMeta)

    indicator(req)
