import asyncio

from src.analyze.service.openAi.analyze.analyze_service import AnalyzeService
from src.analyze.dto.openAi.analyze.analyze_input_dto import AnalyzeInputDto
from src.binance.service.ohlcv.ohlcv_service import OhlcvService
from src.binance.vo.ohlcv.filter import OhlcvFilterVo
from src.indicators.service.indicator.indicator_service import IndicatorService
from src.indicators.vo.indicator.filter import IndicatorsFilterVo
from src.indicators.service.indicator_parameter.indParam_service import IndicatorParamService


TEST_BATCH_ID = 'BTCUSDT202601129090'
def test_input_service():
    async def _inner():
        ohlcvService = OhlcvService()
        indicatorService = IndicatorService()
        paramsService = IndicatorParamService()
        analyzeService = AnalyzeService()
        ohlcv = await ohlcvService.find_ohlcv(OhlcvFilterVo(batch_id=TEST_BATCH_ID))
        indParams = await paramsService.findby_name("default")
        indicator = await indicatorService.find_indicators(IndicatorsFilterVo(batch_id=TEST_BATCH_ID))

        dto = AnalyzeInputDto(ohlcv=ohlcv, indicators=indicator, indParams=indParams)
        action = await analyzeService.analyze(dto)
        print(action)

    asyncio.run(_inner())
