import importlib
from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError

from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.common.exception.repository_error import RepositoryError
from src.strategy.repository.strategy.strategy_repo import StrategyRepository
from src.strategy.strategies.IStrategy import IStrategy
from src.strategy.vo.strategy.default import DefaultStrategyVo
from src.strategy.vo.strategy.filter import StrategyFilterVo


class StrategyService:
    def __init__(self):
        self.repository = StrategyRepository()

    async def create_strategy(self, vo: DefaultStrategyVo) -> int:
        try:
            return await self.repository.insert_strategy(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert strategy.") from e

    async def find_strategies(self, vo: StrategyFilterVo) -> List[DefaultStrategyVo]:
        try:
            return await self.repository.select_strategies(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select strategy.") from e

    async def find_strategy_by_name(
        self, strategy_name: str, only_active: bool = True
    ) -> Optional[DefaultStrategyVo]:
        try:
            return await self.repository.select_strategy_by_name(strategy_name, only_active)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select strategy by name.") from e

    async def find_top_active_strategy(self) -> Optional[DefaultStrategyVo]:
        try:
            return await self.repository.select_top_active_strategy()
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to select top active strategy.") from e

    async def update_strategy(self, vo: DefaultStrategyVo) -> int:
        try:
            return await self.repository.update_strategy(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to update strategy.") from e

    async def delete_strategy(self, strategy_name: str) -> int:
        try:
            return await self.repository.delete_strategy(strategy_name)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to delete strategy.") from e

    async def build_strategy_instance(self, strategy_name: str) -> IStrategy:
        strategy_info = await self.find_strategy_by_name(strategy_name, only_active=True)
        if strategy_info is None:
            raise DataNotFoundException(f"Active strategy not found: {strategy_name}")

        try:
            module = importlib.import_module(strategy_info.module_path)
        except Exception as exc:
            raise InvalidRequestException(
                f"Failed to import strategy module: {strategy_info.module_path}"
            ) from exc

        strategy_cls = getattr(module, strategy_info.module_name, None)
        if strategy_cls is None:
            raise InvalidRequestException(
                f"Strategy class not found: {strategy_info.module_name}"
            )

        if not isinstance(strategy_cls, type) or not issubclass(strategy_cls, IStrategy):
            raise InvalidRequestException(
                f"Strategy class must inherit IStrategy: {strategy_info.module_name}"
            )

        try:
            return strategy_cls()
        except Exception as exc:
            raise InvalidRequestException(
                f"Failed to instantiate strategy class: {strategy_info.module_name}"
            ) from exc
