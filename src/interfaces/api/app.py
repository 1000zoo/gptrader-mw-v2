from collections.abc import Callable, Mapping

from fastapi import FastAPI

from src.interfaces.api.position_controller import create_position_router
from src.interfaces.api.strategy_controller import create_strategy_router
from src.interfaces.api.trade_controller import create_trade_router


HealthProvider = Callable[[], Mapping[str, object]]


def create_app(
    *,
    health_provider: HealthProvider | None = None,
    strategy_router=None,
    trade_router=None,
    position_router=None,
) -> FastAPI:
    app = FastAPI(title="Gptrader API")

    @app.get("/health")
    def health() -> dict[str, object]:
        details = dict(health_provider() if health_provider is not None else {})
        return {"ok": True, "status": "healthy", "details": details}

    app.include_router(strategy_router or create_strategy_router())
    app.include_router(trade_router or create_trade_router())
    app.include_router(position_router or create_position_router())
    return app
