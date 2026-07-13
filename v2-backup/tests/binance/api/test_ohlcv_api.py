from src.binance.api.ohlcv.ohlcv_api import OHLCVApi


def test_get_ohlcv_klines():
    api = OHLCVApi()

    d = api.get_ohlcv_klines(
        symbol="BTCUSDT",
    )
