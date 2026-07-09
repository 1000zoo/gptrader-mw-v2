from decimal import Decimal

from src.domain.market import Symbol, Timeframe
from src.domain.strategy import StaticStrategyCatalog, StrategySpec
from src.domain.strategy.implementations.atr_take_profit_stop_loss import (
    AtrTakeProfitStopLossStrategy,
)
from src.domain.strategy.implementations.chart_pattern_strategy import (
    ChartPatternStrategy,
    PivotDetector,
)
from src.domain.strategy.implementations.fixed_ratio_take_profit_stop_loss import (
    FixedRatioTakeProfitStopLossStrategy,
)
from src.domain.strategy.implementations.moving_average_strategy import (
    LatestCloseMovingAverageStrategy,
)
from src.domain.strategy.implementations.range_edge_reversion_strategy import (
    RangeEdgeReversionStrategy,
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
            (
                StrategySpec(
                    strategy_id="chart-pattern",
                    name="Chart Pattern",
                    implementation="src.domain.strategy.implementations.ChartPatternStrategy",
                    version="2026.07.07",
                    symbol=Symbol("BTC", "USDT"),
                    timeframe=Timeframe(1, "m"),
                    lookback_candle_limit=120,
                    parameters={
                        "lookback": 120,
                        "pivot_window": 3,
                        "price_tolerance": Decimal("0.01"),
                        "breakout_buffer": Decimal("0.003"),
                        "volume_ma_period": 20,
                        "volume_multiplier": Decimal("1.3"),
                        "min_confidence": Decimal("0.6"),
                        "risk_reward_ratio": Decimal("2.0"),
                    },
                    metadata={"family": "chart_pattern"},
                ),
                ChartPatternStrategy,
            ),
            (
                StrategySpec(
                    strategy_id="tv-range-seed-s1-t1-p2-fixed",
                    name="TV Range Seed S1 T1 P2 Fixed",
                    implementation="src.domain.strategy.implementations.RangeEdgeReversionStrategy",
                    version="2026.07.09",
                    symbol=Symbol("BTC", "USDT"),
                    timeframe=Timeframe(1, "m"),
                    lookback_candle_limit=302,
                    parameters={
                        "range_period": 300,
                        "lower_band": Decimal("0.06"),
                        "upper_band": Decimal("0.94"),
                        "min_range_width": Decimal("0.010"),
                        "reclaim_return": Decimal("0.0007"),
                    },
                    metadata={
                        "family": "range_edge_reversion",
                        "source_combo_id": "tv-range-seed-s1-t1-p2-fixed",
                    },
                ),
                RangeEdgeReversionStrategy,
            ),
        )
    )


__all__ = [
    "AtrTakeProfitStopLossStrategy",
    "ChartPatternStrategy",
    "FixedRatioTakeProfitStopLossStrategy",
    "LatestCloseMovingAverageStrategy",
    "PivotDetector",
    "RangeEdgeReversionStrategy",
    "SessionVolumeProfileStrategy",
    "create_default_strategy_catalog",
]
