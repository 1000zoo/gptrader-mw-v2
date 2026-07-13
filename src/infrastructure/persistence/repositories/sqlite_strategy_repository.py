import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.domain.lifecycle import (
    SignalGeneratorDefinition,
    StrategyDefinition,
    StrategyEvaluation,
)
from src.domain.ports import StrategyRepositoryPort
from src.infrastructure.persistence.models.lifecycle_records import (
    dumps_payload,
    loads_payload,
    signal_generator_definition_from_payload,
    signal_generator_definition_to_payload,
    strategy_definition_from_payload,
    strategy_definition_to_payload,
    strategy_evaluation_from_payload,
    strategy_evaluation_to_payload,
)


class SqliteStrategyRepository(StrategyRepositoryPort):
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._create_schema()

    def save_strategy_definition(self, definition: StrategyDefinition) -> None:
        now = _now()
        payload = dumps_payload(strategy_definition_to_payload(definition))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_definitions (
                    strategy_id, name, implementation, version, payload,
                    reg_ymd, reg_dt, upd_dt, use_yn
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Y')
                ON CONFLICT(strategy_id) DO UPDATE SET
                    name = excluded.name,
                    implementation = excluded.implementation,
                    version = excluded.version,
                    payload = excluded.payload,
                    upd_dt = excluded.upd_dt,
                    use_yn = 'Y'
                """,
                (
                    definition.strategy_id,
                    definition.name,
                    definition.implementation,
                    definition.version,
                    payload,
                    now[:10].replace("-", ""),
                    now,
                    now,
                ),
            )

    def load_strategy_definition(self, strategy_id: str) -> StrategyDefinition | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM strategy_definitions
                WHERE strategy_id = ? AND use_yn = 'Y'
                """,
                (strategy_id,),
            ).fetchone()
        if row is None:
            return None
        return strategy_definition_from_payload(loads_payload(row["payload"]))

    def save_signal_generator_definition(
        self,
        definition: SignalGeneratorDefinition,
    ) -> None:
        now = _now()
        payload = dumps_payload(signal_generator_definition_to_payload(definition))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO signal_generator_definitions (
                    generator_id, name, payload, reg_ymd, reg_dt, upd_dt, use_yn
                )
                VALUES (?, ?, ?, ?, ?, ?, 'Y')
                ON CONFLICT(generator_id) DO UPDATE SET
                    name = excluded.name,
                    payload = excluded.payload,
                    upd_dt = excluded.upd_dt,
                    use_yn = 'Y'
                """,
                (
                    definition.generator_id,
                    definition.name,
                    payload,
                    now[:10].replace("-", ""),
                    now,
                    now,
                ),
            )

    def load_signal_generator_definition(
        self,
        generator_id: str,
    ) -> SignalGeneratorDefinition | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM signal_generator_definitions
                WHERE generator_id = ? AND use_yn = 'Y'
                """,
                (generator_id,),
            ).fetchone()
        if row is None:
            return None
        return signal_generator_definition_from_payload(loads_payload(row["payload"]))

    def save_strategy_evaluation(self, evaluation: StrategyEvaluation) -> None:
        now = _now()
        payload = dumps_payload(strategy_evaluation_to_payload(evaluation))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_evaluations (
                    evaluation_id, target_id, status, payload,
                    reg_ymd, reg_dt, upd_dt, use_yn
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Y')
                """,
                (
                    evaluation.evaluation_id,
                    evaluation.target_id,
                    evaluation.status.value,
                    payload,
                    now[:10].replace("-", ""),
                    now,
                    now,
                ),
            )

    def list_strategy_evaluations(self, target_id: str) -> tuple[StrategyEvaluation, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM strategy_evaluations
                WHERE target_id = ? AND use_yn = 'Y'
                ORDER BY reg_dt ASC, evaluation_id ASC
                """,
                (target_id,),
            ).fetchall()
        return tuple(
            strategy_evaluation_from_payload(loads_payload(row["payload"]))
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
                CREATE TABLE IF NOT EXISTS strategy_definitions (
                    strategy_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    implementation TEXT NOT NULL,
                    version TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    reg_ymd TEXT NOT NULL,
                    reg_dt TEXT NOT NULL,
                    upd_dt TEXT NOT NULL,
                    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N'))
                );

                CREATE TABLE IF NOT EXISTS signal_generator_definitions (
                    generator_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    reg_ymd TEXT NOT NULL,
                    reg_dt TEXT NOT NULL,
                    upd_dt TEXT NOT NULL,
                    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N'))
                );

                CREATE TABLE IF NOT EXISTS strategy_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    reg_ymd TEXT NOT NULL,
                    reg_dt TEXT NOT NULL,
                    upd_dt TEXT NOT NULL,
                    use_yn TEXT NOT NULL DEFAULT 'Y' CHECK (use_yn IN ('Y', 'N'))
                );

                CREATE INDEX IF NOT EXISTS idx_strategy_evaluations_target_reg_ymd
                    ON strategy_evaluations (target_id, reg_ymd, reg_dt);
                """
            )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
