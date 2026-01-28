import asyncio
from src.binance.service.ohlcv.ohlcv_service import OhlcvService
from src.binance.vo.ohlcv.filter import OhlcvFilterVo

def test_load_ohlcv():
    service = OhlcvService()
    ret = asyncio.run(service.load_ohlcv("BTCUSDT", "1h", "150", "0001"))
    print(len(ret))

def test_find_ohlcv():
    service = OhlcvService()
    ret = asyncio.run(service.find_ohlcv(
        OhlcvFilterVo(batch_id='TESTBTCUSDT')
    ))
    print(len(ret))