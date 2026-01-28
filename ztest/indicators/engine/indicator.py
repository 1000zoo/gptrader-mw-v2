from src.binance.api.ohlcv.ohlcv_api import OHLCVApi
from src.indicators.engine.indicator import Indicator

def _get_data(limit=50):
    
    api = OHLCVApi()
    q = api.get_ohlcv_klines("BTCUSDT", "1h", limit=limit)
    return q

def test_indicator():
    api = OHLCVApi()
    q = api.get_ohlcv_klines("BTCUSDT", "1h", limit=50)


    ind = Indicator(q)
    print(ind.ma_fast())

def test_tuple_indicator():
    q = _get_data()
    ind = Indicator(q)
    macd = ind.macd()
    for m in macd:
        print(m)

def test_all_get():
    q = _get_data(150)
    ind = Indicator(q)
    a = ind.get_all()

    for z in a:
        print(z, a[z])