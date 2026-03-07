import asyncio
from datetime import datetime, timezone

from src.binance.vo.ohlcv.default import DefaultOhlcvVo
from src.indicators.vo.indicator.default import DefaultIndicatorVo
from src.scheduler.position_risk_executor import PositionRiskExecutor
from src.strategy.strategies.IStrategy import IStrategy
from src.strategy.strategies.models import StrategyDecision
from src.strategy.vo.strategy.default import DefaultStrategyVo
from src.trade.vo.trade_fill.default import DefaultTradeFillVo


class FakeExitStrategy(IStrategy):
    def __init__(self):
        super().__init__()
        self.exit_called = False

    def run_strategy(self, data):
        return self._hold("entry_unused")

    def run_exit_strategy(self, data):
        self.exit_called = True
        return StrategyDecision(action="HOLD", confidence=0.6, reason="keep_position", metadata={})


def test_execute_returns_none_when_account_has_no_position():
    executor = PositionRiskExecutor()
    executor.account_service.has_position = lambda: False

    result = asyncio.run(executor.execute())

    assert result is None


def test_execute_runs_exit_strategy_for_open_position():
    executor = PositionRiskExecutor()
    strategy = FakeExitStrategy()
    now = datetime.now(timezone.utc)

    executor.account_service.has_position = lambda: True

    async def fake_find_open_positions():
        return [
            DefaultTradeFillVo(
                symbol_id="BTCUSDT",
                side="LONG",
                status="OPEN",
                entry_order_id="entry-1",
            )
        ]

    async def fake_find_top_active_strategy():
        return DefaultStrategyVo(
            strategy_name="vol_breakout",
            module_path="src.strategy.strategies.volatility_breakout_regime_strategy",
            module_name="VolatilityBreakoutRegimeStrategy",
            use_yn="Y",
            params={"timeframe": "5m", "lookback": 1},
        )

    async def fake_build_strategy_instance(strategy_name: str):
        assert strategy_name == "vol_breakout"
        return strategy

    async def fake_find_recent_ohlcv(symbol_id: str, interval: str, limit: int):
        assert symbol_id == "BTCUSDT"
        assert interval == "5m"
        assert limit == 1
        return [
            DefaultOhlcvVo(
                symbol_id=symbol_id,
                c_interval=interval,
                ts=now,
                c_open=100.0,
                c_high=101.0,
                c_low=99.0,
                c_close=100.5,
                volume=10.0,
                quote_volume=20.0,
            )
        ]

    async def fake_find_recent_indicators(symbol_id: str, interval: str, limit: int):
        assert symbol_id == "BTCUSDT"
        assert interval == "5m"
        assert limit == 1
        return [
            DefaultIndicatorVo(
                symbol_id=symbol_id,
                c_interval=interval,
                ts=now,
                ema_fast=101.0,
                ema_slow=100.0,
                dmi_adx=25.0,
                atr=0.4,
                rsi=50.0,
                bollinger_upper=102.0,
                bollinger_lower=99.0,
            )
        ]

    executor.trade_fill_service.find_open_positions = fake_find_open_positions
    executor.strategy_service.find_top_active_strategy = fake_find_top_active_strategy
    executor.strategy_service.build_strategy_instance = fake_build_strategy_instance
    executor.ohlcv_service.find_recent_ohlcv = fake_find_recent_ohlcv
    executor.indicator_service.find_recent_indicators = fake_find_recent_indicators

    result = asyncio.run(executor.execute())

    assert strategy.exit_called is True
    assert result is not None
    assert result.action == "HOLD"
    assert result.reason == "keep_position"
