import asyncio

from src.indicators.repository.indicator_parameter.indParam_repo import IndicatorParamRepository
from src.indicators.vo.indicator_parameter.default import DefaultIndicatorParamsVo

def test_select():
    vo = DefaultIndicatorParamsVo(name="default")
    repo = IndicatorParamRepository()
    res = asyncio.run(repo.select_params(vo))
    print(res)