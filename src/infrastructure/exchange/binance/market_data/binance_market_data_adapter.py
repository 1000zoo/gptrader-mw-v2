from datetime import datetime
from typing import Sequence, cast

from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.ports import MarketDataPort
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.binance_rest import request_json
from src.infrastructure.exchange.binance.market_data.binance_market_data_mapper import (
    map_binance_kline_to_candle,
)


class BinanceMarketDataAdapter(MarketDataPort):
    def __init__(self, config: BinanceConfig | None = None) -> None:
        self._config = config or BinanceConfig.from_env()

    def load_candles(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        rows = load_klines_api(
            self._config,
            symbol=symbol.pair,
            interval=timeframe.label,
            limit=limit,
        )
        return tuple(
            map_binance_kline_to_candle(row, symbol, timeframe)
            for row in rows
        )

    def load_snapshot(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        limit: int,
    ) -> MarketSnapshot:
        return MarketSnapshot(self.load_candles(symbol, timeframe, limit))

    def load_candles_between(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        start_at: datetime,
        end_at: datetime,
        page_limit: int = 1500,
    ) -> tuple[Candle, ...]:
        if end_at <= start_at:
            raise ValueError("end_at must be after start_at")
        if page_limit <= 0:
            raise ValueError("page_limit must be positive")

        start_ms = _to_epoch_millis(start_at)
        end_ms = _to_epoch_millis(end_at)
        interval_ms = timeframe.duration_seconds * 1000
        rows: list[Sequence[object]] = []
        cursor_ms = start_ms

        while cursor_ms < end_ms:
            page = load_klines_api(
                self._config,
                symbol=symbol.pair,
                interval=timeframe.label,
                limit=page_limit,
                start_time=cursor_ms,
                end_time=end_ms,
            )
            if not page:
                break

            rows.extend(page)
            last_open_time = int(page[-1][0])
            next_cursor = last_open_time + interval_ms
            if next_cursor <= cursor_ms:
                break
            cursor_ms = next_cursor
            if len(page) < page_limit:
                break

        candles = tuple(
            map_binance_kline_to_candle(row, symbol, timeframe)
            for row in rows
        )
        return tuple(
            candle
            for candle in candles
            if start_at <= candle.opened_at < end_at
        )


def load_klines_api(
    config: BinanceConfig,
    symbol: str,
    interval: str,
    limit: int,
    start_time: int | None = None,
    end_time: int | None = None,
) -> list[Sequence[object]]:
    params: dict[str, object] = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit,
    }
    if start_time is not None:
        params["startTime"] = start_time
    if end_time is not None:
        params["endTime"] = end_time
    return cast(
        list[Sequence[object]],
        request_json(
            config,
            "GET",
            "/fapi/v1/klines",
            params=params,
        ),
    )


def _to_epoch_millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)
