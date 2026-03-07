from src.common.util.class_loader import *
from src.strategy.strategies.IStrategy import IStrategy


def test_load_class():
    s = load_class('src.strategy.strategies.volatility_breakout_regime_strategy', 'VolatilityBreakoutRegimeStrategy', IStrategy)
