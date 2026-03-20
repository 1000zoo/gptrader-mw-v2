from typing import Optional, List, cast, Dict, Any

from loguru import logger
from pydantic import BaseModel

from src.app.usecase.market_data_preparation_usecase import (
    MarketDataPreparationUseCase, PreparedDataDto, PrepareDataDto
)
from src.common.model.types import TF
from src.common.util.class_loader import load_class
from src.strategy.service import StrategyService
from src.strategy.strategies.IStrategy import IStrategy
from src.strategy.strategies.models import StrategyInitConfig, StrategyDecision, StrategyRunInput
from src.strategy.vo import DefaultStrategyVo
from src.strategy.vo.strategy_timeframe.default import DefaultStrategyTimeframeVo


def _dto_to_input(dto_list: List[PreparedDataDto]) -> StrategyRunInput:
    indicator_by_tf: Dict[TF, List[Dict[str, Any]]] = {}
    ohlcv_by_tf: Dict[TF, List[Dict[str, Any]]] = {}

    for dto in dto_list:
        tf = dto.tf

        indicator_by_tf[tf] = [
            ind.model_dump() for ind in dto.indicators
        ]
        ohlcv_by_tf[tf] = [
            ohlcv.model_dump() for ohlcv in dto.ohlcv
        ]

    return StrategyRunInput(
        indicators_by_tf=indicator_by_tf,
        ohlcv_by_tf=ohlcv_by_tf,
    )


class RunStrategyDto(BaseModel):
    symbol_id: str

class StrategyUseCase:
    def __init__(self):
        self.strategy_service = StrategyService()
        self.data_preparation_usecase = MarketDataPreparationUseCase()
        self.strategy : Optional[IStrategy] = None

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
        strategy_vo: DefaultStrategyVo = await self.strategy_service.find_top_active_strategy()
        self.strategy = await self._build_strategy(strategy_vo)
        return self.strategy

    async def run_exit_strategy(self, dto: RunStrategyDto) -> Optional[StrategyDecision]:
        if not self.strategy:
            logger.error("build strategy first")
            raise Exception()


        prepare_dto_list = [PrepareDataDto(
            symbol_id=dto.symbol_id,
            interval=tf,
            limit=limit,
            params_name=self.strategy.params_id
        ) for tf, limit in self.strategy.limit_config.items()]
        data = await self.data_preparation_usecase.prepare_data(prepare_dto_list)

        decision: StrategyDecision = self.strategy.run_exit_strategy(_dto_to_input(data))
        logger.info(f"decision of position ({dto.symbol_id}) => {decision.action} because {decision.reason}")
        return decision

