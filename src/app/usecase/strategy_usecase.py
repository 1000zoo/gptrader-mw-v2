from typing import Optional, List, cast

from src.app.usecase.market_data_preparation_usecase import MarketDataPreparationUseCase
from src.common.model.types import TF
from src.common.util.class_loader import load_class
from src.strategy.service import StrategyService
from src.strategy.strategies.IStrategy import IStrategy
from src.strategy.strategies.models import StrategyInitConfig
from src.strategy.vo import DefaultStrategyVo
from src.strategy.vo.strategy_timeframe.default import DefaultStrategyTimeframeVo


class StrategyPreparationUseCase:
    def __init__(self):
        self.strategy_service = StrategyService()
        self.data_preparation_usecase = MarketDataPreparationUseCase()

    async def _build_strategy(self, vo: DefaultStrategyVo) -> IStrategy:
        strategy_tf: List[DefaultStrategyTimeframeVo] = await self.strategy_service.find_timeframe(
            DefaultStrategyTimeframeVo(strategy_name=vo.strategy_name)
        )
        timeframes = [cast(TF, tf.timeframe) for tf in strategy_tf]
        limit = {cast(TF, tf.timeframe): tf.c_limit for tf in strategy_tf}
        lookback = {cast(TF, tf.timeframe): tf.lookback for tf in strategy_tf}
        strategy: IStrategy = load_class(vo.module_path, vo.module_name, IStrategy)
        strategy.init_strategy(StrategyInitConfig(
            strategy_name=vo.strategy_name,
            timeframes=timeframes,
            lookback_by_tf=lookback,
            limit=limit,
            params_id=vo.params_id
        ))
        return strategy


    async def load_strategy_by_priority(self) -> Optional[IStrategy]:
        strategy: DefaultStrategyVo = await self.strategy_service.find_top_active_strategy()
        return await self._build_strategy(strategy)
