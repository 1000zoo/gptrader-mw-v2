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
from src.domain.strategy.implementations.microstructure_alpha_strategy import (
    FlowConfirmedBreakoutStrategy,
    FlowExhaustionReversalStrategy,
    GlobalRatioShockReversalStrategy,
    MicrostructureRegimeRouterStrategy,
    MultiTimeframeTrendPullbackStrategy,
    OpenInterestDivergenceStrategy,
    OpenInterestImpulseStrategy,
    PositioningCrowdingReversalStrategy,
    PremiumFundingReversionStrategy,
    SessionOpeningRangeStrategy,
)
from src.domain.strategy.implementations.range_edge_reversion_strategy import (
    RangeEdgeReversionStrategy,
)
from src.domain.strategy.implementations.regime_router_scalper_strategy import (
    RegimeRouterScalperStrategy,
)
from src.domain.strategy.implementations.session_volume_profile import (
    SessionVolumeProfileStrategy,
)
from src.domain.strategy.implementations.volatility_compression_breakout_strategy import (
    VolatilityCompressionBreakoutStrategy,
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
            (
                StrategySpec(
                    strategy_id="live-compression-s2-sl0030-rr045-balanced",
                    name="Live Compression S2 SL0030 RR045 Balanced",
                    implementation="src.domain.strategy.implementations.VolatilityCompressionBreakoutStrategy",
                    version="2026.07.09",
                    symbol=Symbol("BTC", "USDT"),
                    timeframe=Timeframe(1, "m"),
                    lookback_candle_limit=1442,
                    parameters={
                        "lookback": 180,
                        "compression_period": 45,
                        "compression_ratio": Decimal("0.45"),
                        "breakout_buffer": Decimal("0.0006"),
                        "min_volume_ratio": Decimal("1.00"),
                        "direction_filter_period": 1440,
                        "min_filter_return": Decimal("0.002"),
                    },
                    metadata={
                        "family": "volatility_compression_breakout",
                        "source_combo_id": "final-compression-s2-sl0.030-rr0.45-balanced",
                    },
                ),
                VolatilityCompressionBreakoutStrategy,
            ),
            (
                StrategySpec(
                    strategy_id="live-scalp-multi-t1-r1-b4-tbr-sl0050-rr025-p2",
                    name="Live Scalp Multi T1 R1 B4 TBR SL0050 RR025 P2",
                    implementation="src.domain.strategy.implementations.RegimeRouterScalperStrategy",
                    version="2026.07.10",
                    symbol=Symbol("BTC", "USDT"),
                    timeframe=Timeframe(1, "m"),
                    lookback_candle_limit=262,
                    parameters={
                        "trend_params": {
                            "trend_period": 60,
                            "pullback_period": 5,
                            "trigger_period": 1,
                            "min_trend_return": Decimal("0.002"),
                            "min_pullback": Decimal("0.0006"),
                            "min_trigger_return": Decimal("0.0002"),
                            "min_range_ratio": Decimal("0.0008"),
                        },
                        "range_params": {
                            "range_period": 45,
                            "edge_ratio": Decimal("0.18"),
                            "min_reversal_body_ratio": Decimal("0.15"),
                            "min_range_ratio": Decimal("0.0015"),
                        },
                        "burst_params": {
                            "breakout_period": 12,
                            "impulse_period": 1,
                            "volume_period": 20,
                            "min_impulse_return": Decimal("0.0008"),
                            "min_volume_ratio": Decimal("1.0"),
                            "breakout_buffer": Decimal("0.0000"),
                            "mode": "fade",
                        },
                        "router_order": ("trend", "burst", "range"),
                        "max_abs_trend_for_range": Decimal("0.008"),
                        "range_regime_period": 240,
                        "trend_regime_period": 240,
                    },
                    metadata={
                        "family": "regime_router_scalper",
                        "source_combo_id": "scalp-multi-t1-r1-b4-router-tbr-sl0050-rr0_25-p2",
                        "selection_method": "train-only candidate selection; test metrics reported after selection",
                    },
                ),
                RegimeRouterScalperStrategy,
            ),
        )
    )


__all__ = [
    "AtrTakeProfitStopLossStrategy",
    "ChartPatternStrategy",
    "FixedRatioTakeProfitStopLossStrategy",
    "FlowConfirmedBreakoutStrategy",
    "FlowExhaustionReversalStrategy",
    "GlobalRatioShockReversalStrategy",
    "LatestCloseMovingAverageStrategy",
    "MicrostructureRegimeRouterStrategy",
    "MultiTimeframeTrendPullbackStrategy",
    "OpenInterestDivergenceStrategy",
    "OpenInterestImpulseStrategy",
    "PositioningCrowdingReversalStrategy",
    "PivotDetector",
    "PremiumFundingReversionStrategy",
    "RangeEdgeReversionStrategy",
    "RegimeRouterScalperStrategy",
    "SessionOpeningRangeStrategy",
    "SessionVolumeProfileStrategy",
    "VolatilityCompressionBreakoutStrategy",
    "create_default_strategy_catalog",
]
