from collections.abc import Callable, Mapping
from typing import Protocol

from fastapi import APIRouter

from src.interfaces.api.response import execute_boundary, require_dependency


Payload = Mapping[str, object]
CommandFactory = Callable[[Payload], object]


class ExecuteTradeUseCase(Protocol):
    def execute(self, command: object) -> object:
        ...


class ClosePositionUseCase(Protocol):
    def close(self, command: object) -> object:
        ...


def _default_command_factory(payload: Payload) -> object:
    return dict(payload)


def create_trade_router(
    *,
    execute_trade_usecase: ExecuteTradeUseCase | None = None,
    close_position_usecase: ClosePositionUseCase | None = None,
    execute_trade_command_factory: CommandFactory | None = None,
    close_position_command_factory: CommandFactory | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/trade", tags=["trade"])
    execute_factory = execute_trade_command_factory or _default_command_factory
    close_factory = close_position_command_factory or _default_command_factory

    @router.post("/execute")
    def execute_trade(payload: dict[str, object]) -> dict[str, object]:
        usecase = require_dependency(execute_trade_usecase, "execute_trade_usecase")
        return execute_boundary(lambda: usecase.execute(execute_factory(payload)))

    @router.post("/close")
    def close_position(payload: dict[str, object]) -> dict[str, object]:
        usecase = require_dependency(close_position_usecase, "close_position_usecase")
        return execute_boundary(lambda: usecase.close(close_factory(payload)))

    return router
