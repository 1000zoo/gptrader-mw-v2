from fastapi import APIRouter, Depends
from loguru import logger

from src.binance.api.ohlcv.ohlcv_api import OHLCVApi
from src.common.model.response import GetResponse
from src.common.util.base import success_meta, fail_meta, to_data
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.invalid_response_exception import InvalidResponseException

router = APIRouter(prefix="/binance/chart")


@router.get("/klines", response_model=GetResponse)
def get_klines(
    symbol: str,
    interval: str = "1h",
    limit: int = 150,
    openTime: int = None,
    closeTime: int = None,
    svc = Depends(lambda: KLinesService())):
    logger.info(f"received: {symbol}, {interval}, {limit}")
    return svc.get_klines(
        symbol=symbol, interval=interval, limit=limit, openTime=openTime, closeTime=closeTime
    )

class KLinesService:
    def __init__(self):
        self.api = OHLCVApi()
    
    def get_klines(self, symbol, interval, limit, openTime, closeTime) -> GetResponse:
        data = []
        try:
            if not symbol or not interval or not limit:
                raise InvalidRequestException("Symbol, interval, and limit are required.")
            res = self.api.get_ohlcv_klines(symbol, interval, limit, openTime, closeTime)
            if not res:
                raise DataNotFoundException("No OHLCV data found.")
            meta = success_meta()
            data = res

            logger.info(f"{symbol} api results count: {len(data)}")
        
        except (DataNotFoundException, ExternalApiError, InvalidRequestException, InvalidResponseException) as e:
            meta = fail_meta(msg=f"fail => get_klines: {e}")
            logger.error(f"fail => get_klines :: {e}")

        return GetResponse(meta=meta, data=to_data(data))
    
