from dataclasses import dataclass
from datetime import datetime

from src.domain.market.candle import Candle
from src.domain.market.symbol import Symbol
from src.domain.market.timeframe import Timeframe


@dataclass(frozen=True)
class MarketSnapshot:
    candles: tuple[Candle, ...]

    def __post_init__(self) -> None:
        if not self.candles:
            raise ValueError("candles are required")

        first = self.candles[0]
        for candle in self.candles:
            if candle.symbol != first.symbol:
                raise ValueError("all candles must have the same symbol")
            if candle.timeframe != first.timeframe:
                raise ValueError("all candles must have the same timeframe")

        opened_times = [candle.opened_at for candle in self.candles]
        if opened_times != sorted(opened_times):
            raise ValueError("candles must be chronological")

    @property
    def symbol(self) -> Symbol:
        return self.candles[0].symbol

    @property
    def timeframe(self) -> Timeframe:
        return self.candles[0].timeframe

    @property
    def opened_at(self) -> datetime:
        return self.candles[0].opened_at

    @property
    def closed_at(self) -> datetime:
        return self.candles[-1].closed_at

    @property
    def latest_candle(self) -> Candle:
        return self.candles[-1]
