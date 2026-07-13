from dataclasses import dataclass
from datetime import datetime

from src.domain.position import Position, PositionEvent


@dataclass(frozen=True)
class PositionStreamUpdate:
    stream_name: str
    received_at: datetime
    previous_position: Position
    event: PositionEvent
    position: Position


class PositionEventMapper:
    def apply(
        self,
        *,
        stream_name: str,
        position: Position,
        event: PositionEvent,
        received_at: datetime,
    ) -> PositionStreamUpdate:
        return PositionStreamUpdate(
            stream_name=stream_name,
            received_at=received_at,
            previous_position=position,
            event=event,
            position=position.apply_event(event),
        )
