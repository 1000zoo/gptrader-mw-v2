from datetime import datetime
from typing import Any, List, Dict
from loguru import logger

from src.binance.api.symbol.symbol_api import SymbolApi
from src.binance.repository.symbol.symbol_repo import SymbolRepository
from src.binance.vo.symbol.default import DefaultSymbolVo
from src.binance.vo.symbol.filter import SymbolFilterVo
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_response_exception import InvalidResponseException
from src.common.exception.repository_error import RepositoryError
from sqlalchemy.exc import SQLAlchemyError

def _increase_n(s: str) -> str:
    if s == '9999':
        return '10000'
    length = len(s)
    return str(int(s) + 1).zfill(length)

def _to_vo(data: List[Dict]) -> List[DefaultSymbolVo]:
    ret = []
    for d in data:
        vo = DefaultSymbolVo(
            symbol_id=d["symbol"],
            symbol_name=d["symbol"],        
            quantity_precision=d.get("baseAssetPrecision"),
            tick_size=float(d["tickSize"]) if d.get("tickSize") else None,
            step_size=float(d["stepSize"]) if d.get("stepSize") else None,

            min_price=float(d["minPrice"]) if d.get("minPrice") else None,
            max_price=float(d["maxPrice"]) if d.get("maxPrice") else None,

            min_qty=float(d["minQty"]) if d.get("minQty") else None,
            max_qty=float(d["maxQty"]) if d.get("maxQty") else None,
            attr1='Y'
        )
        ret.append(vo)
    return ret

class SymbolService:
    def __init__(self):
        self.api = SymbolApi()
        self.repository = SymbolRepository()

    async def add_symbol(self, symbol_names: str | List[str]) -> Any:
        if isinstance(symbol_names, str):
            symbol_names = [symbol_names]
            
        try:
            symbols = self.api.get_symbols_info(symbol_names)
        except (ExternalApiError, InvalidResponseException) as e:
            raise ExternalApiError("Failed to fetch symbol info from API.") from e
        if not symbols:
            raise DataNotFoundException("No symbols returned from API.")
        vo_list = _to_vo(symbols)

        for vo in vo_list:
            try:
                await self.repository.insert_symbol(vo)
            except (SQLAlchemyError, ValueError) as e:
                logger.error(f"error at add_symbol:: {e}")
                raise RepositoryError("Failed to insert symbol.") from e


    async def find_use_symbols(self):
        try:
            symbols = await self.repository.select_symbol(SymbolFilterVo(attr1='Y'))
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch symbols.") from e
        if not symbols:
            raise DataNotFoundException("No active symbols found.")
        return symbols
    

    async def get_update_today_n(self, symbol: str) -> str:
        try:
            vo_list = await self.repository.select_symbol(SymbolFilterVo(
                symbol_id=symbol,
                attr1='Y'
            ))
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch symbol for update.") from e
        if not vo_list:
            raise DataNotFoundException(f"Symbol not found: {symbol}.")
        
        vo = vo_list[0]
        n = vo.attr2
        now_ymd = datetime.now().strftime("%Y%m%d")
        reg_ymd = vo.attr3 or now_ymd

        vo.attr2 = _increase_n(n) if n else "0001"
        vo.attr3 = now_ymd

        if reg_ymd < now_ymd:
            vo.attr2 = "0001"

        try:
            await self.repository.update_symbol(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to update symbol.") from e

        return n

