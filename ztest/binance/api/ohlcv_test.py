from src.binance.api.ohlcv.ohlcv_api import OHLCVApi

from ztest.test_helper import pretty_printer

def test_klines():
    symbolApi = OHLCVApi()
    # res = symbolApi.get_ohlcv_klines('BTCUSDT')
    # print(res)

    res = symbolApi.get_ohlcv_klines("BTCUSDT", "5m", 5)
    pretty_printer(res)
