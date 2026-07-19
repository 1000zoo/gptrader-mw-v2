from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from src.domain.market import Candle, Symbol, Timeframe


def map_binance_kline_to_candle(
    row: Sequence[object],
    symbol: Symbol,
    timeframe: Timeframe,
) -> Candle:
    opened_at = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(seconds=timeframe.duration_seconds),
        open_price=Decimal(str(row[1])),
        high_price=Decimal(str(row[2])),
        low_price=Decimal(str(row[3])),
        close_price=Decimal(str(row[4])),
        volume=Decimal(str(row[5])),
    )
