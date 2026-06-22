from decimal import Decimal

from src.domain.market import Symbol, Timeframe
from src.domain.strategy import StaticStrategyCatalog, StrategySpec
from src.domain.strategy.implementations.atr_take_profit_stop_loss import (
    AtrTakeProfitStopLossStrategy,
)
from src.domain.strategy.implementations.moving_average_strategy import (
    LatestCloseMovingAverageStrategy,
)
from src.domain.strategy.implementations.session_volume_profile import (
    SessionVolumeProfileStrategy,
)


def create_default_strategy_catalog() -> StaticStrategyCatalog:
    return StaticStrategyCatalog(
        entries=(
            (
                StrategySpec(
                    strategy_id="latest-close-moving-average",
                    name="Latest Close Moving Average",
                    implementation="src.domain.strategy.implementations.LatestCloseMovingAverageStrategy",
                    version="2026.06.17",
                    symbol=Symbol("BTC", "USDT"),
                    timeframe=Timeframe(1, "m"),
                    lookback_candle_limit=240,
                    indicator_keys=("moving_average.period_3",),
                ),
                LatestCloseMovingAverageStrategy,
            ),
            (
                StrategySpec(
                    strategy_id="session-volume-profile",
                    name="Session Volume Profile",
                    implementation="src.domain.strategy.implementations.SessionVolumeProfileStrategy",
                    version="2026.06.17",
                    symbol=Symbol("BTC", "USDT"),
                    timeframe=Timeframe(5, "m"),
                    lookback_candle_limit=25920,
                    parameters={
                        "price_bin_size": Decimal("10"),
                        "profile_min_candles": 3,
                    },
                    metadata={"family": "volume_profile"},
                ),
                SessionVolumeProfileStrategy,
            ),
        )
    )


__all__ = [
    "AtrTakeProfitStopLossStrategy",
    "LatestCloseMovingAverageStrategy",
    "SessionVolumeProfileStrategy",
    "create_default_strategy_catalog",
]
