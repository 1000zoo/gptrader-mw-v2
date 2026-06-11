from decimal import Decimal

from src.domain.market import Symbol
from src.domain.position import Position
from src.domain.signal import SignalDirection
from src.interfaces.api.position_controller import create_position_router


def test_current_position_returns_serialized_domain_object() -> None:
    position = Position.open(
        symbol=Symbol("BTC", "USDT"),
        direction=SignalDirection.LONG,
        quantity=Decimal("1.5"),
        average_entry_price=Decimal("60000"),
    )
    router = create_position_router(current_position_provider=lambda: position)
    endpoint = next(route for route in router.routes if route.path == "/positions/current").endpoint

    response = endpoint()

    assert response["data"]["symbol"]["base_asset"] == "BTC"
    assert response["data"]["direction"] == "long"
    assert response["data"]["quantity"] == "1.5"
