from binance.um_futures import UMFutures
from binance.error import ClientError

from src.binance.api.binance_util import get_settings
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.external_api_error import ExternalApiError

class AccountApi:
    def __init__(self):
        key, secret, url = get_settings()
        self.client = UMFutures(key=key, secret=secret, base_url=url)

    def get_balance(self):
        try:
            return self.client.balance()
        except (ClientError, KeyError, TypeError, ValueError) as e:
            raise ExternalApiError("Failed to fetch balance.") from e

    def get_account(self):
        try:
            return self.client.account()
        except (ClientError, KeyError, TypeError, ValueError) as e:
            raise ExternalApiError("Failed to fetch account data.") from e
    
    def get_usdt_balance(self):
        account = self.get_account()
        assets = account.get("assets")
        if assets is None:
            raise DataNotFoundException("Account assets are missing.")
        for asset in assets:
            if asset["asset"] == "USDT":
                return float(asset["availableBalance"])
        raise DataNotFoundException("USDT balance not found.")
    
    def get_current_positions(self):
        account = self.get_account()
        positions = account.get("positions")
        if positions is None:
            return []
        return positions
