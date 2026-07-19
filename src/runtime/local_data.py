from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.domain.indicator import IndicatorSet, IndicatorValue
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.strategy import StrategyContext
from src.domain.strategy.implementations import LatestCloseMovingAverageStrategy
from src.runtime.config import RuntimeSettings


def parse_symbol(value: str) -> Symbol:
    normalized = value.strip().upper()
    if normalized.endswith("USDT") and len(normalized) > 4:
        return Symbol(normalized[:-4], "USDT")
    raise ValueError("local runtime currently expects a USDT symbol, such as BTCUSDT")


def parse_timeframe(value: str) -> Timeframe:
    normalized = value.strip().lower()
    return Timeframe(int(normalized[:-1]), normalized[-1])


def build_local_market_snapshot(settings: RuntimeSettings) -> MarketSnapshot:
    symbol = parse_symbol(settings.symbol)
    timeframe = parse_timeframe(settings.timeframe)
    closed_at = datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc)
    interval = timedelta(seconds=timeframe.duration_seconds)
    closes = (Decimal("100"), Decimal("101"), Decimal("103"))
    candles = []
    for index, close_price in enumerate(closes):
        candle_closed_at = closed_at - interval * (len(closes) - index - 1)
        candles.append(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                opened_at=candle_closed_at - interval,
                closed_at=candle_closed_at,
                open_price=close_price - Decimal("1"),
                high_price=close_price + Decimal("1"),
                low_price=close_price - Decimal("2"),
                close_price=close_price,
                volume=Decimal("10"),
            )
        )
    return MarketSnapshot(tuple(candles))


def build_local_indicator_set(snapshot: MarketSnapshot) -> IndicatorSet:
    closes = [candle.close_price for candle in snapshot.candles[-3:]]
    moving_average = sum(closes, Decimal("0")) / Decimal(len(closes))
    measured_at = snapshot.latest_candle.closed_at
    return IndicatorSet(
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        measured_at=measured_at,
        values=(
            IndicatorValue(
                name="moving_average",
                value=moving_average,
                measured_at=measured_at,
                parameters={"period": 3},
            ),
        ),
    )


def build_local_strategy_context(settings: RuntimeSettings) -> StrategyContext:
    snapshot = build_local_market_snapshot(settings)
    return StrategyContext(
        market=snapshot,
        indicators=build_local_indicator_set(snapshot),
        metadata={"runtime_mode": settings.mode.value},
    )


def evaluate_local_example_strategy(settings: RuntimeSettings):
    return LatestCloseMovingAverageStrategy().evaluate(
        build_local_strategy_context(settings)
    )
