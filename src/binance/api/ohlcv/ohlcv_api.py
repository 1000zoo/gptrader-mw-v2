import httpx

from loguru import logger

from src.binance.api.ohlcv.ohlcv_util import ohlcv_klines_serializer
from src.binance.api.binance_util import get_settings
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_response_exception import InvalidResponseException

class OHLCVApi:
    def __init__(self):
        _, _, self.BASE_URL = get_settings()
        self.ohlcv_klines_url = self.BASE_URL + "/fapi/v1/klines"
        
    def get_ohlcv_klines(
            self,
            symbol: str,
            interval: str = "1h",
            limit: int = 150,
            startTime: int = None,
            endTime: int = None
        ):
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }

        if startTime and endTime:
            params["startTime"] = startTime
            params["endTime"] = endTime
        
        try:
            data = httpx.get(self.ohlcv_klines_url, params=params)
            data.raise_for_status()
            data = data.json()
        except httpx.HTTPError as e:
            logger.error(f"error ohlcv_api:: {e}")
            raise ExternalApiError("Failed to fetch OHLCV data.") from e
        if not isinstance(data, list):
            raise InvalidResponseException("OHLCV response is not a list.")
        res = ohlcv_klines_serializer(data, meta=params)
        return res

        
