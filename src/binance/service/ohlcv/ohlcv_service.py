from datetime import datetime, timezone
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

_INTERVAL_MS = {
    "m": 60 * 1000,
    "h": 60 * 60 * 1000,
    "d": 24 * 60 * 60 * 1000,
    "w": 7 * 24 * 60 * 60 * 1000,
    "M": 30 * 24 * 60 * 60 * 1000,
}


def _interval_to_ms(interval: str) -> int:
    if not interval:
        raise ValueError("Interval is required.")
    unit = interval[-1]
    value = int(interval[:-1])
    if unit not in _INTERVAL_MS:
        raise ValueError(f"Unsupported interval unit: {unit}")
    return value * _INTERVAL_MS[unit]


def _to_epoch_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


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

    async def load_ohlcv_window(
        self,
        symbol_name: str,
        interval: str,
        limit: int,
        batch_id: str,
        start_time: datetime,
    ) -> List[DefaultOhlcvVo]:
        interval_ms = _interval_to_ms(interval)
        start_ms = _to_epoch_ms(start_time)
        end_ms = start_ms + interval_ms * limit
        try:
            data = self.api.get_ohlcv_klines(
                symbol=symbol_name,
                interval=interval,
                limit=limit,
                startTime=start_ms,
                endTime=end_ms,
            )
        except (ExternalApiError, InvalidResponseException) as e:
            raise ExternalApiError("Failed to fetch OHLCV window data.") from e
        if not data:
            raise DataNotFoundException(f"OHLCV window data not found for {symbol_name}.")
        vo = _to_vo_list(data, batch_id)
        try:
            await self.repository.insert_ohlcv_bulk(vo=vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert OHLCV window data.") from e
        return vo


    async def find_ohlcv(self, vo: OhlcvFilterVo) -> List[DefaultOhlcvVo]:
        try:
            ohlcv = await self.repository.select_ohlcv(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch OHLCV data.") from e
        if not ohlcv:
            raise DataNotFoundException("OHLCV data not found.")
        return ohlcv

    async def find_recent_ohlcv(
        self, symbol_id: str, interval: str, limit: int
    ) -> List[DefaultOhlcvVo]:
        try:
            ohlcv = await self.repository.select_recent_ohlcv(
                symbol_id=symbol_id,
                interval=interval,
                limit=limit,
            )
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch recent OHLCV data.") from e
        if not ohlcv:
            raise DataNotFoundException("Recent OHLCV data not found.")
        return list(reversed(ohlcv))
