import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from src.domain.ports.regime_selection_state_repository_port import (
    ConcurrentSelectionStateError,
    RegimeSelectionStateRepositoryPort,
)
from src.domain.regime.selection import (
    RegimeSelectionState,
    SelectionEventType,
    SelectStrategyResult,
)


_STATE_KEYS = {
    "symbol",
    "artifact_version",
    "current_cluster_fingerprint",
    "active_strategy_profile_id",
    "pending_cluster_fingerprint",
    "pending_confirmation_count",
    "consecutive_low_confidence_count",
    "new_entries_enabled",
    "last_boundary_at",
    "state_version",
    "pending_artifact_version",
}
_RESULT_KEYS = {
    "evaluated_artifact_identity",
    "expected_state_version",
    "state",
    "events",
    "selection_input_hash",
}


class SqliteRegimeSelectionStateRepository(RegimeSelectionStateRepositoryPort):
    """Atomic, content-verified storage for dynamic selection decisions."""

    def __init__(self, database_path: str | Path) -> None:
        path = Path(database_path)
        if path.exists() and path.is_dir():
            raise ValueError("database path must point to a file")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = str(path)
        self._create_schema()

    def load(self, symbol: str) -> RegimeSelectionState | None:
        symbol = _canonical_symbol(symbol)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT symbol, state_version, state_json, state_hash, boundary_at
                FROM regime_selection_states
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
        if row is None:
            return None
        return _state_from_row(row)

    def commit(
        self,
        expected_state_version: int,
        result: SelectStrategyResult,
    ) -> SelectStrategyResult:
        expected = _expected_version(expected_state_version)
        if not isinstance(result, SelectStrategyResult):
            raise ValueError("result must be a SelectStrategyResult")
        if result.expected_state_version != expected:
            raise ValueError("result expected_state_version must match commit argument")
        if result.state.state_version != expected + 1:
            raise ValueError("result state_version must increment expected_state_version")

        symbol = _canonical_symbol(result.state.symbol)
        boundary_at = _utc_iso(result.state.last_boundary_at)
        evaluated_artifact_identity = result.evaluated_artifact_identity
        result_json = _encode_result(result)
        decision_hash = _sha256(result_json)
        events_json = _canonical_json([event.value for event in result.events])
        state_json = _encode_state(result.state)
        state_hash = _sha256(state_json)

        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                """
                SELECT symbol, boundary_at, artifact_version, expected_version,
                       committed_version, result_json, decision_hash, events_json
                FROM regime_selection_events
                WHERE symbol = ? AND boundary_at = ? AND artifact_version = ?
                """,
                (symbol, boundary_at, evaluated_artifact_identity),
            ).fetchone()
            if prior is not None:
                original = _result_from_event_row(prior)
                if prior["decision_hash"] == decision_hash:
                    connection.commit()
                    return original
                raise ValueError("conflicting boundary commit")

            current = connection.execute(
                """
                SELECT symbol, state_version, state_json, state_hash, boundary_at
                FROM regime_selection_states
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()
            current_version = 0
            if current is not None:
                current_state = _state_from_row(current)
                current_version = current_state.state_version
                if current_state.last_boundary_at >= result.state.last_boundary_at:
                    raise ValueError("selection boundary must be strictly after current state")
            if current_version != expected:
                raise ConcurrentSelectionStateError(
                    f"stale selection state: expected {expected}, current {current_version}"
                )

            connection.execute(
                """
                INSERT INTO regime_selection_events (
                    symbol, boundary_at, artifact_version, expected_version,
                    committed_version, result_json, decision_hash, events_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    boundary_at,
                    evaluated_artifact_identity,
                    expected,
                    result.state.state_version,
                    result_json,
                    decision_hash,
                    events_json,
                ),
            )

            if current is None:
                cursor = connection.execute(
                    """
                    INSERT INTO regime_selection_states (
                        symbol, state_version, state_json, state_hash,
                        boundary_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        result.state.state_version,
                        state_json,
                        state_hash,
                        boundary_at,
                        _now(),
                    ),
                )
            else:
                cursor = connection.execute(
                    """
                    UPDATE regime_selection_states
                    SET state_version = ?, state_json = ?, state_hash = ?,
                        boundary_at = ?, updated_at = ?
                    WHERE symbol = ? AND state_version = ?
                    """,
                    (
                        result.state.state_version,
                        state_json,
                        state_hash,
                        boundary_at,
                        _now(),
                        symbol,
                        expected,
                    ),
                )
            if cursor.rowcount != 1:
                raise ConcurrentSelectionStateError("selection state compare-and-set failed")
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def find_committed_result(
        self,
        symbol: str,
        boundary_at: datetime,
        evaluated_artifact_identity: str,
    ) -> SelectStrategyResult | None:
        symbol = _canonical_symbol(symbol)
        boundary = _utc_iso(boundary_at)
        artifact = _sha256_text(
            evaluated_artifact_identity, "evaluated_artifact_identity"
        )
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT symbol, boundary_at, artifact_version, expected_version,
                       committed_version, result_json, decision_hash, events_json
                FROM regime_selection_events
                WHERE symbol = ? AND boundary_at = ? AND artifact_version = ?
                """,
                (symbol, boundary, artifact),
            ).fetchone()
        return None if row is None else _result_from_event_row(row)

    def list_events(self, symbol: str) -> tuple[SelectionEventType, ...]:
        symbol = _canonical_symbol(symbol)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT symbol, boundary_at, artifact_version, expected_version,
                       committed_version, result_json, decision_hash, events_json
                FROM regime_selection_events
                WHERE symbol = ?
                ORDER BY boundary_at ASC, event_id ASC
                """,
                (symbol,),
            ).fetchall()
        return tuple(
            event
            for row in rows
            for event in _result_from_event_row(row).events
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=10,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _create_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS regime_selection_states (
                    symbol TEXT PRIMARY KEY,
                    state_version INTEGER NOT NULL CHECK (
                        typeof(state_version) = 'integer' AND state_version > 0
                    ),
                    state_json TEXT NOT NULL,
                    state_hash TEXT NOT NULL,
                    boundary_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS regime_selection_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    boundary_at TEXT NOT NULL,
                    artifact_version TEXT NOT NULL,
                    expected_version INTEGER NOT NULL CHECK (
                        typeof(expected_version) = 'integer' AND expected_version >= 0
                    ),
                    committed_version INTEGER NOT NULL CHECK (
                        typeof(committed_version) = 'integer' AND committed_version > 0
                    ),
                    result_json TEXT NOT NULL,
                    decision_hash TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    UNIQUE (symbol, boundary_at, artifact_version)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_regime_selection_events_order
                    ON regime_selection_events (symbol, boundary_at, event_id)
                """
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _state_to_payload(state: RegimeSelectionState) -> dict[str, object]:
    return {
        "active_strategy_profile_id": state.active_strategy_profile_id,
        "artifact_version": state.artifact_version,
        "consecutive_low_confidence_count": state.consecutive_low_confidence_count,
        "current_cluster_fingerprint": state.current_cluster_fingerprint,
        "last_boundary_at": _utc_iso(state.last_boundary_at),
        "new_entries_enabled": state.new_entries_enabled,
        "pending_artifact_version": state.pending_artifact_version,
        "pending_cluster_fingerprint": state.pending_cluster_fingerprint,
        "pending_confirmation_count": state.pending_confirmation_count,
        "state_version": state.state_version,
        "symbol": state.symbol,
    }


def _encode_state(state: RegimeSelectionState) -> str:
    return _canonical_json(_state_to_payload(state))


def _encode_result(result: SelectStrategyResult) -> str:
    return _canonical_json(
        {
            "evaluated_artifact_identity": result.evaluated_artifact_identity,
            "events": [event.value for event in result.events],
            "expected_state_version": result.expected_state_version,
            "state": _state_to_payload(result.state),
            "selection_input_hash": result.selection_input_hash,
        }
    )


def _decode_state(payload: object) -> RegimeSelectionState:
    if not isinstance(payload, dict) or set(payload) != _STATE_KEYS:
        raise ValueError("selection state keys are invalid")
    boundary = payload["last_boundary_at"]
    if not isinstance(boundary, str):
        raise ValueError("selection state boundary is invalid")
    try:
        last_boundary_at = datetime.fromisoformat(boundary)
    except ValueError as error:
        raise ValueError("selection state boundary is invalid") from error
    try:
        return RegimeSelectionState(
            symbol=payload["symbol"],
            artifact_version=payload["artifact_version"],
            current_cluster_fingerprint=payload["current_cluster_fingerprint"],
            active_strategy_profile_id=payload["active_strategy_profile_id"],
            pending_cluster_fingerprint=payload["pending_cluster_fingerprint"],
            pending_confirmation_count=payload["pending_confirmation_count"],
            consecutive_low_confidence_count=payload[
                "consecutive_low_confidence_count"
            ],
            new_entries_enabled=payload["new_entries_enabled"],
            last_boundary_at=last_boundary_at,
            state_version=payload["state_version"],
            pending_artifact_version=payload["pending_artifact_version"],
        )
    except (TypeError, ValueError) as error:
        raise ValueError("selection state payload is invalid") from error


def _decode_result(result_json: str) -> SelectStrategyResult:
    payload = _strict_loads(result_json, "selection decision")
    if not isinstance(payload, dict) or set(payload) != _RESULT_KEYS:
        raise ValueError("selection decision keys are invalid")
    events_payload = payload["events"]
    if not isinstance(events_payload, list):
        raise ValueError("selection decision events are invalid")
    try:
        events = tuple(SelectionEventType(value) for value in events_payload)
        return SelectStrategyResult(
            evaluated_artifact_identity=payload["evaluated_artifact_identity"],
            expected_state_version=payload["expected_state_version"],
            state=_decode_state(payload["state"]),
            events=events,
            selection_input_hash=payload["selection_input_hash"],
        )
    except (TypeError, ValueError) as error:
        raise ValueError("selection decision payload is invalid") from error


def _state_from_row(row: sqlite3.Row) -> RegimeSelectionState:
    state_json = row["state_json"]
    if not isinstance(state_json, str) or row["state_hash"] != _sha256(state_json):
        raise ValueError("selection state integrity check failed")
    payload = _strict_loads(state_json, "selection state")
    state = _decode_state(payload)
    if (
        state.symbol != row["symbol"]
        or state.state_version != row["state_version"]
        or _utc_iso(state.last_boundary_at) != row["boundary_at"]
    ):
        raise ValueError("selection state row does not match its payload")
    return state


def _result_from_event_row(row: sqlite3.Row) -> SelectStrategyResult:
    result_json = row["result_json"]
    if not isinstance(result_json, str) or row["decision_hash"] != _sha256(result_json):
        raise ValueError("selection decision integrity check failed")
    result = _decode_result(result_json)
    events_json = row["events_json"]
    events_payload = _strict_loads(events_json, "selection events")
    if events_payload != [event.value for event in result.events]:
        raise ValueError("selection decision events do not match result")
    if (
        result.state.symbol != row["symbol"]
        or _utc_iso(result.state.last_boundary_at) != row["boundary_at"]
        or result.evaluated_artifact_identity != row["artifact_version"]
        or result.expected_state_version != row["expected_version"]
        or result.state.state_version != row["committed_version"]
    ):
        raise ValueError("selection decision coordinate row does not match its payload")
    return result


def _strict_loads(payload: str, label: str) -> object:
    if not isinstance(payload, str):
        raise ValueError(f"{label} JSON must be text")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} JSON contains duplicate keys")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"{label} JSON contains nonstandard constant {value}")

    try:
        decoded = json.loads(
            payload,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} JSON is invalid") from error
    if _canonical_json(decoded) != payload:
        raise ValueError(f"{label} JSON is not canonical")
    return decoded


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _expected_version(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("expected_state_version must be a nonnegative integer")
    return value


def _canonical_symbol(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or value != value.upper()
    ):
        raise ValueError("symbol must be canonical uppercase")
    return value


def _utc_iso(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is not timezone.utc:
        raise ValueError("selection boundary must use canonical UTC")
    return value.isoformat()


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256_text(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA256 hash")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["SqliteRegimeSelectionStateRepository"]
