from typing import Any, Dict, Optional

from src.binance.repository.position_event.position_event_repo import PositionEventRepository
from src.binance.vo.position_event.default import DefaultPositionEventVo
from src.common.util.date import reg_ymd_now
from src.common.exception.repository_error import RepositoryError

from sqlalchemy.exc import SQLAlchemyError



def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_position_event_vo(message: Dict[str, Any]) -> DefaultPositionEventVo:
    order = message.get("o", {})
    reg_ymd = reg_ymd_now()
    symbol_id = order.get("s")
    order_id = order.get("i")   ## 여기 바꿔야함
    client_order_id = order.get("c")
    batch_id = message.get("batch_id")
    # batch_id = f"{symbol_id}{reg_ymd}{order_id}" if batch_id is None else None

    qty = order.get("l") if order.get("l") not in (None, "0") else order.get("q")
    price = order.get("L") or order.get("ap") or order.get("p")

    return DefaultPositionEventVo(
        reg_ymd=reg_ymd,
        batch_id=batch_id,
        symbol_id=symbol_id,
        event_type=message.get("e"),
        side=order.get("S"),
        qty=_to_float(qty),
        price=_to_float(price),
        order_id=str(order_id) if order_id is not None else None,
        position_side=order.get("ps"),
        execution_type=order.get("x"),
        order_type=order.get("ot"),
        pnl=_to_float(order.get("rp")),
        attr1=client_order_id
    )


class PositionEventService:
    def __init__(self):
        self.repository = PositionEventRepository()

    async def add_position_event(self, message: Dict[str, Any]) -> DefaultPositionEventVo:
        vo = _to_position_event_vo(message)
        try:
            await self.repository.insert_position_event(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert position event.") from e
        return vo

    async def add_position_event_vo(self, vo: DefaultPositionEventVo):
        try:
            await self.repository.insert_position_event(vo)
        except (SQLAlchemyError, ValueError) as e:
            raise RepositoryError("Failed to insert position event.") from e
        return vo