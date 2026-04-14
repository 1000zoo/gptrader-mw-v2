import asyncio
import os
from typing import Optional, List, cast

from loguru import logger
from pydantic import BaseModel

from src.binance.service.ohlcv.ohlcv_master_service import OhlcvMasterService
from src.binance.service.ohlcv.ohlcv_service import OhlcvService
from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.binance.vo.ohlcv.filter import OhlcvFilterVo
from src.common.model.params import IndParams
from src.common.model.types import TF
from src.indicators.service.indicator.indicator_service import IndicatorService
from src.indicators.service.indicator_parameter.indParam_service import IndicatorParamService
from src.indicators.vo.indicator.default import DefaultIndicatorVo
from src.indicators.vo.indicator_parameter.default import DefaultIndicatorParamsVo


class PrepareDataDto(BaseModel):
    symbol_id: str
    interval: str
    limit: int
    params_name: Optional[str] = None

class PreparedDataDto(BaseModel):
    ohlcv: List[DefaultOhlcvVo]
    indicators: List[DefaultIndicatorVo]
    symbol_id: str
    tf: TF

class MarketDataPreparationUseCase:
    def __init__(self):
        self.ohlcv_service = OhlcvService()
        self.ohlcv_master_service = OhlcvMasterService()
        self.indicator_param_service = IndicatorParamService()
        self.indicator_service = IndicatorService()

    async def _get_indicator_params(self, params_name: str = None):
        if not params_name:
            params_name = os.getenv('INDICATOR_PARAMS_NAME', 'default_2')
        vo = DefaultIndicatorParamsVo(name=params_name)
        try:
            return await self.indicator_param_service.find_params(vo)
        except Exception as e:
            logger.warning(f'indParams can not found, use default param set, {e}')
            return IndParams()


    async def prepare_data(self, dto_list: List[PrepareDataDto]) -> List[PreparedDataDto]:
        async def process(dto) -> PreparedDataDto:
            ohlcv_vo = await self.ohlcv_master_service.only_fetch_candle(OhlcvFilterVo(
                symbol_id=dto.symbol_id,
                c_interval=dto.interval,
                c_limit=dto.limit,
            ))
            indParam = await self._get_indicator_params(dto.params_name)

            indicators = IndicatorService.cal_indicators(ohlcv_vo, indParam)
            return PreparedDataDto(
                ohlcv=ohlcv_vo, indicators=indicators, tf=cast(TF, dto.interval), symbol_id=dto.symbol_id
            )

        results = await asyncio.gather(
            *[process(dto) for dto in dto_list]
        )
        return list(results)

    ## Todo: 위는 analyze, strategy 용이고, backtest 용 추가 필요 (시간범위)
