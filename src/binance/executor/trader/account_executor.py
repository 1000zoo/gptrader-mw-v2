from loguru import logger

from src.binance.service.trader.account_service import AccountService
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.repository_error import RepositoryError


class AccountExecutor:
    def __init__(self):
        self.accountService = AccountService()

    def has_position(self):
        try:
            return self.accountService.has_position()
        except DataNotFoundException as e:
            logger.warning(f"accountExecutor.has_position: {e}")
            return False
        except (ExternalApiError, InvalidRequestException, RepositoryError) as e:
            logger.error(f"accountExecutor.has_position: {e}")
            raise
