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


def load_klines_api(
    config: BinanceConfig,
    symbol: str,
    interval: str,
    limit: int,
) -> list[Sequence[object]]:
    return cast(
        list[Sequence[object]],
        request_json(
            config,
            "GET",
            "/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        ),
    )
