import asyncio

from src.common.model.params import IndParams
from src.indicators.service.indicator.indicator_service import IndicatorService
from src.indicators.vo.indicator.filter import IndicatorsFilterVo
from src.binance.service.ohlcv.ohlcv_service import OhlcvService

def test_cal_indicator():
    ohlcvService = OhlcvService()
    service = IndicatorService()

    async def _test():
        ohlcv = await ohlcvService.load_ohlcv(symbol_name="BTCUSDT", interval="1h", limit=150, batch_id="BTCUSDT202699990001")
        res = await service.cal_insert_indicators(ohlcv=ohlcv, indParams=IndParams())
        print(res)
    asyncio.run(_test())


def test_select_indicators():
    service = IndicatorService()

    ret = asyncio.run(service.find_indicators(
        IndicatorsFilterVo(batch_id="TESTBTCUSDT")
    ))

    print(len(ret))