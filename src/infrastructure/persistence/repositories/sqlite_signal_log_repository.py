import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.domain.ports import SignalLogEntry, SignalLogRepositoryPort
from src.infrastructure.persistence.models.signal_log_records import (
    dumps_signal_payload,
    loads_signal_payload,
    signal_log_entry_from_payload,
    signal_log_entry_to_payload,
)


class SqliteSignalLogRepository(SignalLogRepositoryPort):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._create_schema()

    def append_signal(self, entry: SignalLogEntry) -> None:
        now = _now()
        payload = dumps_signal_payload(signal_log_entry_to_payload(entry))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO signal_logs (
                    signal_id, generator_id, payload,
                    reg_ymd, reg_dt, upd_dt, use_yn
                )
                VALUES (?, ?, ?, ?, ?, ?, 'Y')
                """,
                (
                    entry.signal_id,
                    entry.generator_id,
                    payload,
                    now[:10].replace("-", ""),
                    now,
                    now,
                ),
            )

    def list_signals_for_generator(
        self,
        generator_id: str,
    ) -> tuple[SignalLogEntry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM signal_logs
                WHERE generator_id = ? AND use_yn = 'Y'
                ORDER BY reg_dt ASC, signal_id ASC
                """,
                (generator_id,),
            ).fetchall()
        return tuple(
            signal_log_entry_from_payload(loads_signal_payload(row["payload"]))
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
                CREATE TABLE IF NOT EXISTS signal_logs (
                    signal_id TEXT PRIMARY KEY,
                    generator_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    reg_ymd TEXT NOT NULL,
                    reg_dt TEXT NOT NULL,
                    upd_dt TEXT NOT NULL,
                    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N'))
                );

                CREATE INDEX IF NOT EXISTS idx_signal_logs_generator_reg_ymd
                    ON signal_logs (generator_id, reg_ymd, reg_dt);
                """
            )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
