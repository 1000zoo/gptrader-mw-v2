from __future__ import annotations

from typing import Optional

from loguru import logger

from src.binance.service.ohlcv.ohlcv_service import OhlcvService
from src.binance.service.trader.account_service import AccountService
from src.indicators.service.indicator.indicator_service import IndicatorService
from src.strategy.service.strategy.strategy_service import StrategyService
from src.strategy.strategies.models import StrategyDecision, StrategyInitConfig, StrategyRunInput
from src.trade.service.trade_fill.trade_fill_service import TradeFillService
from src.trade.vo.trade_fill.default import DefaultTradeFillVo


class PositionRiskExecutor:
    def __init__(self):
        self.account_service = AccountService()
        self.trade_fill_service = TradeFillService()
        self.strategy_service = StrategyService()
        self.ohlcv_service = OhlcvService()
        self.indicator_service = IndicatorService()

    async def execute(self) -> Optional[StrategyDecision]:
        if not self.account_service.has_position():
            return None

        open_positions = await self.trade_fill_service.find_open_positions()
        if not open_positions:
            return None

        strategy_info = await self.strategy_service.find_top_active_strategy()
        if strategy_info is None or not strategy_info.strategy_name:
            logger.warning("position risk executor: no active strategy found.")
            return None

        strategy = await self.strategy_service.build_strategy_instance(strategy_info.strategy_name)
        params = strategy_info.params or {}
        timeframe = str(params.get("timeframe", "5m"))
        lookback = max(1, int(params.get("lookback", 1)))

        last_hold: Optional[StrategyDecision] = None
        for position in open_positions:
            if not position.symbol_id:
                continue

            strategy.init_strategy(
                StrategyInitConfig(
                    strategy_name=strategy_info.strategy_name,
                    symbol=position.symbol_id,
                    timeframes=[timeframe],
                    lookback_by_tf={timeframe: lookback},
                    params=params,
                )
            )
            run_input = await self._build_strategy_input(position.symbol_id, timeframe, lookback)
            decision = strategy.run_exit_strategy(run_input)
            decision.metadata["symbol_id"] = position.symbol_id
            decision.metadata["position_side"] = position.side

            if self._is_exit_decision(position, decision):
                logger.info(
                    f"position risk decision: symbol={position.symbol_id} "
                    f"side={position.side} action={decision.action} reason={decision.reason}"
                )
                return decision
            last_hold = decision

        return last_hold

    async def _build_strategy_input(self, symbol_id: str, timeframe: str, lookback: int) -> StrategyRunInput:
        ohlcv_rows = await self.ohlcv_service.find_recent_ohlcv(
            symbol_id=symbol_id,
            interval=timeframe,
            limit=lookback,
        )
        indicator_rows = await self.indicator_service.find_recent_indicators(
            symbol_id=symbol_id,
            interval=timeframe,
            limit=lookback,
        )
        latest_ohlcv = ohlcv_rows[-1]
        return StrategyRunInput(
            indicators_by_tf={timeframe: [row.dump_for_prompt() for row in indicator_rows]},
            ohlcv_by_tf={timeframe: StrategyRunInput.ohlcv_vo_to_dict(latest_ohlcv)},
            recent_analyzes=[],
        )

    @staticmethod
    def _is_exit_decision(position: DefaultTradeFillVo, decision: StrategyDecision) -> bool:
        if decision.action == "HOLD":
            return False

        side = (position.side or "").upper()
        if side == "LONG":
            return decision.action == "SELL"
        if side == "SHORT":
            return decision.action == "BUY"
        return True


async def execute():
    executor = PositionRiskExecutor()
    return await executor.execute()
