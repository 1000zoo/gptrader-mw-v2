from typing import Any

from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.ports import MarketDataPort
from src.infrastructure.exchange.binance.market_data.binance_market_data_mapper import (
    map_binance_kline_to_candle,
)


class BinanceMarketDataAdapter(MarketDataPort):
    def __init__(self, client: Any) -> None:
        self._client = client

    def load_candles(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        limit: int,
    ) -> tuple[Candle, ...]:
        rows = self._client.get_klines(
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
