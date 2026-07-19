import pytest
from fastapi import HTTPException

from src.interfaces.api.trade_controller import create_trade_router


class RecordingExecuteUseCase:
    def __init__(self) -> None:
        self.commands = []

    def execute(self, command):
        self.commands.append(command)
        return {"status": "order_submitted"}


class RecordingCloseUseCase:
    def __init__(self) -> None:
        self.commands = []

    def close(self, command):
        self.commands.append(command)
        return {"status": "skipped"}


def _endpoint(router, path: str):
    route = next(route for route in router.routes if route.path == path)
    return route.endpoint


def test_execute_trade_uses_command_factory_and_usecase() -> None:
    usecase = RecordingExecuteUseCase()
    router = create_trade_router(
        execute_trade_usecase=usecase,
        execute_trade_command_factory=lambda payload: ("command", payload["symbol"]),
    )

    response = _endpoint(router, "/trade/execute")({"symbol": "BTCUSDT"})

    assert response == {"ok": True, "data": {"status": "order_submitted"}}
    assert usecase.commands == [("command", "BTCUSDT")]


def test_missing_trade_dependency_returns_503() -> None:
    endpoint = _endpoint(create_trade_router(), "/trade/execute")

    with pytest.raises(HTTPException) as exc_info:
        endpoint({"symbol": "BTCUSDT"})

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "execute_trade_usecase is not configured"
