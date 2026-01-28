import os
from typing import List, Dict, Any

import httpx

from loguru import logger

from src.binance.constants.url import BINANCE_MAINNET, BINANCE_TESTNET
from src.binance.api.symbol.symbol_util import exchange_info_serializer
from src.binance.api.binance_util import isTest
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_response_exception import InvalidResponseException

class SymbolApi:
    def __init__(self):
        self.BASE_URL = BINANCE_TESTNET if isTest() else BINANCE_MAINNET
        self.exchange_information = self.BASE_URL + "/fapi/v1/exchangeInfo"

    def get_symbol_info(self, symbol_name: str) -> list[Any]:
        try:
            data = httpx.get(self.exchange_information)
            data.raise_for_status()
            data = data.json()
        except httpx.HTTPError as e:
            logger.error(f"error in SymbolApi.get_symbol_info:: {e}")
            raise ExternalApiError("Failed to fetch symbol information.") from e
        symbols = data.get("symbols")
        if symbols is None:
            raise InvalidResponseException("Symbol information response is missing symbols.")
        for s in symbols:
            if s.get("symbol") == symbol_name:
                info = exchange_info_serializer(s)
                return [info]
        return []

    def get_symbols_info(self, symbol_names: list[str]) -> list[dict]:
        try:
            data = httpx.get(self.exchange_information)
            data.raise_for_status()
            data = data.json()
        except httpx.HTTPError as e:
            logger.error(f"error in SymbolApi.get_symbols_info:: {e}")
            raise ExternalApiError("Failed to fetch symbols information.") from e

        res = []

        symbols = data.get("symbols")
        if symbols is None:
            raise InvalidResponseException("Symbols response is missing symbols.")
        for s in symbols:
            symbol = s.get("symbol")
            if symbol in symbol_names:
                info = exchange_info_serializer(s)
                res.append(info)
        
        return res
        
