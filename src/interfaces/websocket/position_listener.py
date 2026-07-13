import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from src.domain.position import Position, PositionEvent
from src.interfaces.websocket.event_mapper import PositionEventMapper, PositionStreamUpdate


PositionEventHandler = Callable[[PositionEvent], object | Awaitable[object]]
PositionUpdateHandler = Callable[[PositionStreamUpdate], object | Awaitable[object]]


class PositionEventStream(Protocol):
    async def consume(
        self,
        handler: PositionEventHandler,
        *,
        max_reconnects: int | None = None,
    ) -> None:
        ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PositionStreamRun:
    stream_name: str
    started_at: datetime
    finished_at: datetime
    initial_position: Position
    position: Position
    updates: tuple[PositionStreamUpdate, ...]
    error: Exception | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class PositionListener:
    def __init__(
        self,
        stream: PositionEventStream,
        *,
        mapper: PositionEventMapper | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._stream = stream
        self._mapper = mapper or PositionEventMapper()
        self._now = now or _utc_now

    async def listen(
        self,
        *,
        stream_name: str,
        initial_position: Position,
        update_handler: PositionUpdateHandler | None = None,
        max_reconnects: int | None = None,
    ) -> PositionStreamRun:
        started_at = self._now()
        position = initial_position
        updates: list[PositionStreamUpdate] = []
        error: Exception | None = None

        async def handle_event(event: PositionEvent) -> None:
            nonlocal position
            update = self._mapper.apply(
                stream_name=stream_name,
                position=position,
                event=event,
                received_at=self._now(),
            )
            position = update.position
            updates.append(update)
            if update_handler is not None:
                await _call_update_handler(update_handler, update)

        try:
            await self._stream.consume(handle_event, max_reconnects=max_reconnects)
        except Exception as exc:
            error = exc

        return PositionStreamRun(
            stream_name=stream_name,
            started_at=started_at,
            finished_at=self._now(),
            initial_position=initial_position,
            position=position,
            updates=tuple(updates),
            error=error,
        )


async def _call_update_handler(
    handler: PositionUpdateHandler,
    update: PositionStreamUpdate,
) -> None:
    result = handler(update)
    if inspect.isawaitable(result):
        await result
