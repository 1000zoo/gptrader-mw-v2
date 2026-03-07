import asyncio

from typing import Any, List, Dict
from loguru import logger

from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.indicators.engine.indicator import Indicator
from src.common.model.params import IndParams
from src.indicators.vo.indicator.default import DefaultIndicatorVo
from src.indicators.vo.indicator.filter import IndicatorsFilterVo
from src.indicators.repository.indicator.indicator_repo import IndicatorRepository
from src.common.util.date import reg_ymd_now
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.repository_error import RepositoryError
from src.common.exception.data_not_found_exception import DataNotFoundException
from sqlalchemy.exc import SQLAlchemyError

def _to_vo_list(data: List[Dict], **meta) -> List[DefaultIndicatorVo]:
    vo_list = []
    for i, d in enumerate(data):
        vo_list.append(DefaultIndicatorVo.to_vo(
            d, **meta, seq_no=i
        ))
    return vo_list

def _vo_to_dict(vo_list: List[DefaultOhlcvVo]) -> List[Dict]:
    data: List[Dict[str, Any]] = []

    for vo in vo_list:
        data.append({
            # index
            "openTime": vo.ts,

            # OHLC
            "open": float(vo.c_open),
            "high": float(vo.c_high),
            "low": float(vo.c_low),
            "close": float(vo.c_close),

            # volume
            "quoteAssetVolume": float(vo.quote_volume),

            # calculator에서 요구하지만 DB에는 없는 값들
            "takerBuyBaseAsset": 0.0,
            "takerBuyQuoteAsset": 0.0,
            "numberOfTrades": 0.0,
        })

    return data

class IndicatorService:
    def __init__(self):
        self.repository = IndicatorRepository()

    @staticmethod
    def cal_indicators(ohlcv: List[DefaultOhlcvVo], indParams: IndParams) -> List[DefaultIndicatorVo]:
        if not ohlcv:
            raise InvalidRequestException("OHLCV data is required to calculate indicators.")
        indicator = Indicator(ohlcv=_vo_to_dict(ohlcv), indParams=indParams)
        results = indicator.getT()
        sample = ohlcv[0]
        meta = {
            'reg_ymd': sample.reg_ymd,
            'symbol_id': sample.symbol_id,
            'batch_id': sample.batch_id,
            'indicator_parameter_id': indParams.name,
            'c_interval': sample.c_interval,
            'c_limit': sample.c_limit
        }
        vo_list = _to_vo_list(results, **meta)
        return vo_list

    async def cal_insert_indicators(self, ohlcv: List[DefaultOhlcvVo], indParams: IndParams) -> List[DefaultIndicatorVo]:
        if not ohlcv:
            raise InvalidRequestException("OHLCV data is required to calculate indicators.")
        indicator = Indicator(ohlcv=_vo_to_dict(ohlcv), indParams=indParams)
        results = indicator.getT()
        sample = ohlcv[0]
        meta = {
            'reg_ymd': sample.reg_ymd,
            'symbol_id': sample.symbol_id,
            'batch_id': sample.batch_id,
            'indicator_parameter_id': indParams.name,
            'c_interval': sample.c_interval,
            'c_limit': sample.c_limit
        }
        vo_list = _to_vo_list(results, **meta)
        try:
            await self.repository.insert_indicators_bulk(vo_list)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert indicators.") from e
        return vo_list
    
    async def find_indicators(self, vo: IndicatorsFilterVo) -> List[DefaultIndicatorVo]:
        try:
            indicators = await self.repository.select_indicators(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select indicators.") from e
        if not indicators:
            raise DataNotFoundException("Indicators not found.")
        return indicators

    async def find_recent_indicators(
        self, symbol_id: str, interval: str, limit: int
    ) -> List[DefaultIndicatorVo]:
        try:
            indicators = await self.repository.select_recent_indicators(
                symbol_id=symbol_id,
                interval=interval,
                limit=limit,
            )
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select recent indicators.") from e
        if not indicators:
            raise DataNotFoundException("Recent indicators not found.")
        return list(reversed(indicators))
