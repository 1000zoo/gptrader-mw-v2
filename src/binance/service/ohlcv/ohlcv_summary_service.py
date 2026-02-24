from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from src.binance.repository.ohlcv.ohlcv_summary_repo import OhlcvSummaryRepository
from src.binance.vo.ohlcv.summary_default import OhlcvSummaryVo
from src.binance.vo.ohlcv.summary_filter import OhlcvSummaryFilterVo
from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.repository_error import RepositoryError
from src.common.util.date import reg_ymd_now

_INTERVAL_DELTA = {
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
    "M": timedelta(days=30),
}


def _interval_to_delta(interval: str) -> timedelta:
    if not interval:
        raise ValueError("Interval is required.")
    unit = interval[-1]
    value = int(interval[:-1])
    if unit not in _INTERVAL_DELTA:
        raise ValueError(f"Unsupported interval unit: {unit}")
    return value * _INTERVAL_DELTA[unit]


class OhlcvSummaryService:
    def __init__(self):
        self.repository = OhlcvSummaryRepository()

    async def create_ohlcv_summary(self, vo: OhlcvSummaryVo) -> OhlcvSummaryVo:
        try:
            await self.repository.insert_ohlcv_summary(vo=vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert OHLCV summary.") from e
        return vo

    async def load_ohlcv_summary(
        self,
        symbol_name: str,
        interval: str,
        limit: int,
        batch_id: str,
        start_time: Optional[datetime] = None,
    ) -> OhlcvSummaryVo:
        delta = _interval_to_delta(interval) * limit
        end_ts = datetime.now(timezone.utc)
        start_ts = start_time if start_time else (end_ts - delta)
        if start_ts.tzinfo is None:
            start_ts = start_ts.replace(tzinfo=timezone.utc)

        vo = OhlcvSummaryVo(
            batch_id=batch_id,
            reg_ymd=reg_ymd_now(),
            symbol_id=symbol_name,
            c_interval=interval,
            c_limit=limit,
            start_ts=start_ts,
            end_ts=end_ts,
            attr1="Y",
        )
        return await self.create_ohlcv_summary(vo)

    async def find_ohlcv_summary(self, vo: OhlcvSummaryFilterVo) -> List[OhlcvSummaryVo]:
        try:
            summary = await self.repository.select_ohlcv_summary(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch OHLCV summary.") from e
        if not summary:
            raise DataNotFoundException("OHLCV summary not found.")
        return summary

    async def find_recent_ohlcv_summary(
        self, symbol_id: str, interval: str, limit: int
    ) -> List[OhlcvSummaryVo]:
        try:
            summary = await self.repository.select_recent_ohlcv_summary(
                symbol_id=symbol_id,
                interval=interval,
                limit=limit,
            )
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to fetch recent OHLCV summary.") from e
        if not summary:
            raise DataNotFoundException("Recent OHLCV summary not found.")
        return summary
