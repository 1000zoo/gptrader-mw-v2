from collections.abc import Callable, Mapping
from typing import Protocol

from fastapi import APIRouter

from src.interfaces.api.response import execute_boundary, require_dependency


Payload = Mapping[str, object]
CommandFactory = Callable[[Payload], object]


class ExecuteUseCase(Protocol):
    def execute(self, command: object) -> object:
        ...


def _default_command_factory(payload: Payload) -> object:
    return dict(payload)


def create_strategy_router(
    *,
    register_usecase: ExecuteUseCase | None = None,
    promote_usecase: ExecuteUseCase | None = None,
    run_lifecycle_usecase: ExecuteUseCase | None = None,
    register_command_factory: CommandFactory | None = None,
    promote_command_factory: CommandFactory | None = None,
    run_lifecycle_command_factory: CommandFactory | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/strategies", tags=["strategies"])
    register_factory = register_command_factory or _default_command_factory
    promote_factory = promote_command_factory or _default_command_factory
    run_factory = run_lifecycle_command_factory or _default_command_factory

    @router.post("/register")
    def register(payload: dict[str, object]) -> dict[str, object]:
        usecase = require_dependency(register_usecase, "register_usecase")
        return execute_boundary(lambda: usecase.execute(register_factory(payload)))

    @router.post("/promote")
    def promote(payload: dict[str, object]) -> dict[str, object]:
        usecase = require_dependency(promote_usecase, "promote_usecase")
        return execute_boundary(lambda: usecase.execute(promote_factory(payload)))

    @router.post("/lifecycle/run")
    def run_lifecycle(payload: dict[str, object]) -> dict[str, object]:
        usecase = require_dependency(run_lifecycle_usecase, "run_lifecycle_usecase")
        return execute_boundary(lambda: usecase.execute(run_factory(payload)))

    return router
