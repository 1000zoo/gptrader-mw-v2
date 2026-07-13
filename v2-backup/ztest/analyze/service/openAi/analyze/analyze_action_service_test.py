
from src.analyze.service.openAi.analyze.analyze_result_service import AnalyzeResultService
from src.analyze.service.openAi.analyze.analyze_action_service import AnalyzeActionService

import asyncio

from src.analyze.service.openAi.analyze.analyze_result_service import AnalyzeResultService

from src.binance.service.ohlcv.ohlcv_service import OhlcvService
from src.binance.vo.ohlcv.filter import OhlcvFilterVo
from src.indicators.service.indicator.indicator_service import IndicatorService
from src.indicators.vo.indicator.filter import IndicatorsFilterVo
from src.common.model.params import IndParams


def test_analyze_action_insert():
    ohlcvService = OhlcvService()
    indicatorService = IndicatorService()
    analyzeService = AnalyzeResultService()
    actionService = AnalyzeActionService()

    async def _test():
        ohlcv = await ohlcvService.find_ohlcv(OhlcvFilterVo(batch_id='TESTBTCUSDT'))
        ind = await indicatorService.find_indicators(IndicatorsFilterVo(batch_id='TESTBTCUSDT'))
        result_vo = await analyzeService.analyze(ohlcv, ind, IndParams())
        await actionService.insert_action(result_vo)

    asyncio.run(_test())


