from typing import List
from loguru import logger

from src.common.db.util import common_select
from src.common.model.params import IndParams
from src.indicators.vo.indicator_parameter.default import DefaultIndicatorParamsVo

class IndicatorParamRepository:
    def __init__(self):
        self.TABLE_NAME = "indicator_parameter"
    
    async def select_params(self, vo: DefaultIndicatorParamsVo) -> IndParams:
        result = await common_select(self.TABLE_NAME, vo, IndParams)
        if not result:
            logger.error(f'params {vo.name} does not exist!')
            raise Exception
        params = result[0]
        if params.bollinger_k is not None:
            params.bollinger_k = float(params.bollinger_k)
        if params.keltner_m is not None:
            params.keltner_m = float(params.keltner_m)
        return params
