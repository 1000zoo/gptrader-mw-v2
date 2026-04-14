from loguru import logger
from typing import List

from src.indicators.service.indicator.indicator_service import IndicatorService
from src.indicators.service.indicator_parameter.indParam_service import IndicatorParamService
from src.indicators.vo.indicator.default import DefaultIndicatorVo
from src.indicators.vo.indicator.filter import IndicatorsFilterVo
from src.common.model.params import IndParams
from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.repository_error import RepositoryError


class IndicatorExecutor:
    def __init__(self):
        self.indicatorService = IndicatorService()
        self.indParamService = IndicatorParamService()

    async def cal_insert_indicators(
        self,
        ohlcv: List[DefaultOhlcvVo],
        indParams: IndParams,
        indParams_name: str = "default_2"
    ) -> List[DefaultIndicatorVo]:
        try:
            indParams = await self.indParamService.findby_name(indParams_name)
            return await self.indicatorService.cal_insert_indicators(ohlcv, indParams)
        except (DataNotFoundException, InvalidRequestException) as e:
            logger.warning(f"indicatorExecutor.cal_insert_indicators: {e}")
            return []
        except RepositoryError as e:
            logger.error(f"indicatorExecutor.cal_insert_indicators: {e}")
            raise

    async def find_indicators(self, vo: IndicatorsFilterVo) -> List[DefaultIndicatorVo]:
        try:
            return await self.indicatorService.find_indicators(vo)
        except DataNotFoundException as e:
            logger.warning(f"indicatorExecutor.find_indicators: {e}")
            return []
        except (RepositoryError, InvalidRequestException) as e:
            logger.error(f"indicatorExecutor.find_indicators: {e}")
            raise
