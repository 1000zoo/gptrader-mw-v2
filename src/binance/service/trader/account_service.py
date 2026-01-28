from loguru import logger

from src.binance.api.trader.account_api import AccountApi
from src.common.exception.external_api_error import ExternalApiError


class AccountService:
    def __init__(self):
        self.api = AccountApi()


    def has_position(self):
        try:
            return len(self.api.get_current_positions()) > 0
        except ExternalApiError as e:
            raise ExternalApiError("Failed to determine if account has positions.") from e

    def get_usdt_balance(self) -> float:
        try:
            return float(self.api.get_usdt_balance())
        except ExternalApiError as e:
            raise ExternalApiError("Failed to fetch USDT balance.") from e

    def get_positions(self):
        try:
            return self.api.get_current_positions()
        except ExternalApiError as e:
            raise ExternalApiError("Failed to fetch account positions.") from e
