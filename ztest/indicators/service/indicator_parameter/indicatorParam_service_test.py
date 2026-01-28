import asyncio

from src.indicators.service.indicator_parameter.indParam_service import IndicatorParamService

def test_findby():
    service = IndicatorParamService()
    params = asyncio.run(service.findby_name("default"))
    print(params)
    print(type(params))