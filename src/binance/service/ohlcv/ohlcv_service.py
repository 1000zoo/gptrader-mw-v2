from typing import List, Dict

from src.binance.api.ohlcv.ohlcv_api import OHLCVApi
from src.binance.repository.ohlcv.ohlcv_repo import OhlcvRepository
from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.binance.vo.ohlcv.filter import OhlcvFilterVo
from src.common.util.date import reg_ymd_now
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_response_exception import InvalidResponseException
from src.common.exception.repository_error import RepositoryError
from sqlalchemy.exc import SQLAlchemyError

def _to_vo_list(data: List[Dict], batch_id: str) -> List[DefaultOhlcvVo]:
    reg_ymd = reg_ymd_now()
    vo_list: List[DefaultOhlcvVo] = []

    for idx, d in enumerate(data, start=1):
        vo = DefaultOhlcvVo(
            batch_id=batch_id,
            reg_ymd=reg_ymd,
            symbol_id=d.get("symbol"),
            c_interval=d.get("interval"),
            c_limit=d.get("limit"),
            seq_no=idx,
            ts=d.get("openTime"),
            c_open=float(d["open"]) if d.get("open") is not None else None,
            c_high=float(d["high"]) if d.get("high") is not None else None,
            c_low=float(d["low"]) if d.get("low") is not None else None,
            c_close=float(d["close"]) if d.get("close") is not None else None,
            quote_volume=float(d["quoteAssetVolume"]) if d.get("quoteAssetVolume") is not None else None,
            volume=None,
            attr1='Y'
        )
        vo_list.append(vo)
    return vo_list

class OhlcvService:
    def __init__(self):
        self.api = OHLCVApi()
        self.repository = OhlcvRepository()

    async def load_ohlcv(self, symbol_name: str, interval: str, limit: int, batch_id: str) -> List[DefaultOhlcvVo]:
        try:
            data = self.api.get_ohlcv_klines(symbol=symbol_name, interval=interval, limit=limit)
        except (ExternalApiError, InvalidResponseException) as e:
            raise ExternalApiError("Failed to fetch OHLCV data.") from e
        if not data:
            raise DataNotFoundException(f"OHLCV data not found for {symbol_name}.")
        vo = _to_vo_list(data, batch_id)
        try:
            await self.repository.insert_ohlcv_bulk(vo=vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert OHLCV data.") from e
        return vo


    async def find_ohlcv(self, vo: OhlcvFilterVo) -> List[DefaultOhlcvVo]:
        try:
            ohlcv = await self.repository.select_ohlcv(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch OHLCV data.") from e
        if not ohlcv:
            raise DataNotFoundException("OHLCV data not found.")
        return ohlcv
