import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from src.domain.market import Symbol
from src.domain.position import Position, PositionEvent, PositionEventType, PositionStatus
from src.domain.signal import SignalDirection


@dataclass(frozen=True)
class RuntimeRecord:
    record_type: str
    record_id: str
    payload: Mapping[str, object]
    recorded_at: datetime


class SqliteRuntimeStateRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._create_schema()

    def save_position(self, position_id: str, position: Position) -> None:
        now = _now()
        payload = _dumps(_position_to_payload(position))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_positions (
                    position_id, symbol, status, payload,
                    reg_ymd, reg_dt, upd_dt, use_yn
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Y')
                ON CONFLICT(position_id) DO UPDATE SET
                    symbol = excluded.symbol,
                    status = excluded.status,
                    payload = excluded.payload,
                    upd_dt = excluded.upd_dt,
                    use_yn = 'Y'
                """,
                (
                    position_id,
                    position.symbol.pair,
                    position.status.value,
                    payload,
                    now[:10].replace("-", ""),
                    now,
                    now,
                ),
            )

    def load_position(self, position_id: str) -> Position | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM runtime_positions
                WHERE position_id = ? AND use_yn = 'Y'
                """,
                (position_id,),
            ).fetchone()
        if row is None:
            return None
        return _position_from_payload(_loads(row["payload"]))

    def append_position_event(self, position_id: str, event: PositionEvent) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_position_events (
                    position_id, event_type, payload,
                    reg_ymd, reg_dt, upd_dt, use_yn
                )
                VALUES (?, ?, ?, ?, ?, ?, 'Y')
                """,
                (
                    position_id,
                    event.event_type.value,
                    _dumps(_position_event_to_payload(event)),
                    now[:10].replace("-", ""),
                    now,
                    now,
                ),
            )

    def list_position_events(self, position_id: str) -> tuple[PositionEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM runtime_position_events
                WHERE position_id = ? AND use_yn = 'Y'
                ORDER BY reg_dt ASC, event_id ASC
                """,
                (position_id,),
            ).fetchall()
        return tuple(_position_event_from_payload(_loads(row["payload"])) for row in rows)

    def append_runtime_record(
        self,
        *,
        record_type: str,
        record_id: str,
        payload: Mapping[str, object],
    ) -> None:
        record_type = record_type.strip()
        record_id = record_id.strip()
        if not record_type:
            raise ValueError("record_type is required")
        if not record_id:
            raise ValueError("record_id is required")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_records (
                    record_type, record_id, payload,
                    reg_ymd, reg_dt, upd_dt, use_yn
                )
                VALUES (?, ?, ?, ?, ?, ?, 'Y')
                """,
                (
                    record_type,
                    record_id,
                    _dumps(dict(payload)),
                    now[:10].replace("-", ""),
                    now,
                    now,
                ),
            )

    def list_runtime_records(self, record_type: str) -> tuple[RuntimeRecord, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT record_type, record_id, payload, reg_dt
                FROM runtime_records
                WHERE record_type = ? AND use_yn = 'Y'
                ORDER BY reg_dt ASC, runtime_record_id ASC
                """,
                (record_type,),
            ).fetchall()
        return tuple(
            RuntimeRecord(
                record_type=row["record_type"],
                record_id=row["record_id"],
                payload=_loads(row["payload"]),
                recorded_at=datetime.fromisoformat(row["reg_dt"]),
            )
            for row in rows
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runtime_positions (
                    position_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    reg_ymd TEXT NOT NULL,
                    reg_dt TEXT NOT NULL,
                    upd_dt TEXT NOT NULL,
                    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N'))
                );

                CREATE TABLE IF NOT EXISTS runtime_position_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    reg_ymd TEXT NOT NULL,
                    reg_dt TEXT NOT NULL,
                    upd_dt TEXT NOT NULL,
                    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N'))
                );

                CREATE INDEX IF NOT EXISTS idx_runtime_position_events_position_reg_ymd
                    ON runtime_position_events (position_id, reg_ymd, reg_dt);

                CREATE TABLE IF NOT EXISTS runtime_records (
                    runtime_record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    reg_ymd TEXT NOT NULL,
                    reg_dt TEXT NOT NULL,
                    upd_dt TEXT NOT NULL,
                    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N'))
                );

                CREATE INDEX IF NOT EXISTS idx_runtime_records_type_reg_ymd
                    ON runtime_records (record_type, reg_ymd, reg_dt);
                """
            )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _dumps(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True)


def _loads(payload: str) -> dict[str, object]:
    return json.loads(payload)


def _position_to_payload(position: Position) -> dict[str, object]:
    return {
        "symbol": {
            "base_asset": position.symbol.base_asset,
            "quote_asset": position.symbol.quote_asset,
        },
        "direction": position.direction.value,
        "quantity": str(position.quantity),
        "average_entry_price": str(position.average_entry_price),
        "status": position.status.value,
    }


def _position_from_payload(payload: Mapping[str, object]) -> Position:
    symbol = payload["symbol"]
    if not isinstance(symbol, Mapping):
        raise ValueError("position payload symbol is invalid")
    return Position(
        symbol=Symbol(str(symbol["base_asset"]), str(symbol["quote_asset"])),
        direction=SignalDirection(str(payload["direction"])),
        quantity=Decimal(str(payload["quantity"])),
        average_entry_price=Decimal(str(payload["average_entry_price"])),
        status=PositionStatus(str(payload["status"])),
    )


def _position_event_to_payload(event: PositionEvent) -> dict[str, object]:
    return {
        "event_type": event.event_type.value,
        "quantity": str(event.quantity),
        "price": None if event.price is None else str(event.price),
        "direction": None if event.direction is None else event.direction.value,
    }


def _position_event_from_payload(payload: Mapping[str, object]) -> PositionEvent:
    price = payload.get("price")
    direction = payload.get("direction")
    return PositionEvent(
        event_type=PositionEventType(str(payload["event_type"])),
        quantity=Decimal(str(payload["quantity"])),
        price=None if price is None else Decimal(str(price)),
        direction=None if direction is None else SignalDirection(str(direction)),
    )
