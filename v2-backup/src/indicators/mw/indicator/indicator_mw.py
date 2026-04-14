from fastapi import APIRouter, Depends
from typing import Dict, List
from loguru import logger

from src.binance.api.ohlcv.ohlcv_api import OHLCVApi
from src.indicators.engine.indicator import Indicator
from src.common.model.response import IndPostResponse
from src.common.model.request import IndicatorRequest

from src.common.util.base import success_meta, fail_meta, to_data
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.invalid_response_exception import InvalidResponseException


router = APIRouter(prefix="/indicator")


@router.post("/", response_model=IndPostResponse)
def indicator(req: IndicatorRequest, svc=Depends(lambda: IndicatorService())):
    return svc.cal_indicators(req)

class IndicatorService:
    def __init__(self):
        self.ohlcvApi = OHLCVApi

    def cal_indicators(self, req: IndicatorRequest) -> IndPostResponse:
        symbol = req.ohlcvMeta.symbol
        interval = req.ohlcvMeta.interval
        limit = req.ohlcvMeta.limit
        ohlcv = req.ohlcv

        data = []

        try:
            if not ohlcv:
                if not symbol or not interval or not limit:
                    raise InvalidRequestException("Symbol, interval, and limit are required to fetch OHLCV data.")
                oApi = OHLCVApi()
                ohlcv = oApi.get_ohlcv_klines(symbol=symbol, interval=interval, limit=limit)
            
            ind = Indicator(ohlcv, req.indParams)
            indicators = ind.getT()
            meta = self.get_meta(indicators, req.indParams.tail)
            data = indicators

        except (ExternalApiError, InvalidRequestException, InvalidResponseException) as e:
            msg = f"error at indicator => {e}"
            logger.error(msg)
            meta = fail_meta(msg=msg)
        
        return IndPostResponse(
            meta=meta, ohlcvMeta=req.ohlcvMeta, params=req.indParams,
            data=data
        )

    def get_meta(self, indicators: List[Dict], tail: int):
        l = len(indicators)
        if l != tail:
            return success_meta(status=201, msg=f"not full request data, only {l} lengths not {tail}")
        return success_meta()
