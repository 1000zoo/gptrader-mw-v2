from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import List

from src.binance.api.symbol.symbol_api import SymbolApi
from src.common.model.response import GetResponse
from src.common.util.base import (
    get_meta, success_meta, fail_meta, to_data
)
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_response_exception import InvalidResponseException

router = APIRouter(prefix="/binance/info")


@router.get("/symbol", response_model=GetResponse)
def get_symbol(name: str, svc = Depends(lambda: SymbolService())):
    return svc.get_symbol(name)

@router.get("/symbols")
def get_symbols(names: List[str] = Query(...), svc = Depends(lambda: SymbolService())):
    return svc.get_symbols(names)

class SymbolService:
    def __init__(self):
        self.api = SymbolApi()
    
    def get_symbol(self, name: str) -> GetResponse:
        data = []
        try:
            res = self.api.get_symbol_info(symbol_name=name)
            if not res:
                raise DataNotFoundException(f"Symbol not found: {name}")
            meta = success_meta()
            data = res

        except (DataNotFoundException, ExternalApiError, InvalidResponseException) as e:
            meta = fail_meta(msg=f"fail => SymbolService.get_symbol: {e}")
        return GetResponse(meta=meta, data=to_data(data))
    
    def get_symbols(self, names: List[str]) -> GetResponse:
        data = []

        try:
            res = self.api.get_symbols_info(symbol_names=names)
            if not res:
                raise DataNotFoundException("No symbols found.")
            meta = self.symbols_meta(names, res)
            data = res

        except (DataNotFoundException, ExternalApiError, InvalidResponseException) as e:
            meta = fail_meta(msg=f"fail => SymbolService.get_symbols: {e}")
        return GetResponse(meta=meta, data=to_data(data))

    def symbols_meta(self, names, data):
        none_includes = []
        for name in names:
            print(name)
            if name not in data:
                none_includes.append(name)
        if none_includes:
            rrr = ",".join(none_includes)
            return success_meta(status=201, msg=f"not included: {rrr}")
        return success_meta()

