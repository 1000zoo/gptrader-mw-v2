from loguru import logger
from typing import List, Dict, Any, Optional

from src.binance.service.symbol.symbol_service import SymbolService
from src.binance.vo.symbol.default import DefaultSymbolVo
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.repository_error import RepositoryError

class SymbolExecutor:
    def __init__(self):
        self.symbolService = SymbolService()

    async def get_symbol_list(self) -> List[DefaultSymbolVo]:
        try:
            symbol_list = await self.symbolService.find_use_symbols()
            return symbol_list
        except DataNotFoundException as e:
            logger.warning(f"symbolController.get_symbol_list: {e}")
            return []
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"symbolController.get_symbol_list: {e}")
            raise

    async def get_today_n(self, symbol: DefaultSymbolVo):
        try:
            n = await self.symbolService.get_update_today_n(symbol.symbol_id)
            return n
        except DataNotFoundException as e:
            logger.warning(f"symbolController.get_today_n: {e}")
            raise
        except (ExternalApiError, RepositoryError, InvalidRequestException) as e:
            logger.error(f"symbolController.get_today_n: {e}")
            raise
