from loguru import logger
from typing import List

from src.binance.service.ohlcv.ohlcv_service import OhlcvService
from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.binance.vo.ohlcv.filter import OhlcvFilterVo
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.repository_error import RepositoryError


class OhlcvExecutor:
    def __init__(self):
        self.ohlcvService = OhlcvService()

    async def load_ohlcv(self, symbol_name: str, interval: str, limit: int, batch_id: str) -> List[DefaultOhlcvVo]:
        try:
            return await self.ohlcvService.load_ohlcv(
                symbol_name=symbol_name,
                interval=interval,
                limit=limit,
                batch_id=batch_id,
            )
        except DataNotFoundException as e:
            logger.warning(f"ohlcvExecutor.load_ohlcv: {e}")
            return []
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"ohlcvExecutor.load_ohlcv: {e}")
            raise

    async def find_ohlcv(self, vo: OhlcvFilterVo) -> List[DefaultOhlcvVo]:
        try:
            return await self.ohlcvService.find_ohlcv(vo)
        except DataNotFoundException as e:
            logger.warning(f"ohlcvExecutor.find_ohlcv: {e}")
            return []
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"ohlcvExecutor.find_ohlcv: {e}")
            raise
