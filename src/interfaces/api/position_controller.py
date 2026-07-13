from collections.abc import Callable, Mapping
from typing import Protocol

from fastapi import APIRouter

from src.interfaces.api.response import (
    execute_boundary,
    require_dependency,
    to_response_payload,
)


Payload = Mapping[str, object]
CommandFactory = Callable[[Payload], object]
PositionProvider = Callable[[], object]


class SyncPositionUseCase(Protocol):
    def sync(self, command: object) -> object:
        ...


def _default_command_factory(payload: Payload) -> object:
    return dict(payload)


def create_position_router(
    *,
    current_position_provider: PositionProvider | None = None,
    sync_position_usecase: SyncPositionUseCase | None = None,
    sync_position_command_factory: CommandFactory | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/positions", tags=["positions"])
    sync_factory = sync_position_command_factory or _default_command_factory

    @router.get("/current")
    def current_position() -> dict[str, object]:
        provider = require_dependency(
            current_position_provider,
            "current_position_provider",
        )
        return {"ok": True, "data": to_response_payload(provider())}

    @router.post("/sync")
    def sync_position(payload: dict[str, object]) -> dict[str, object]:
        usecase = require_dependency(sync_position_usecase, "sync_position_usecase")
        return execute_boundary(lambda: usecase.sync(sync_factory(payload)))

    return router
