from decimal import Decimal

from src.domain.market import Symbol
from src.domain.position import Position, PositionEvent, PositionStatus
from src.domain.signal import SignalDirection
from src.infrastructure.persistence import SqliteRuntimeStateRepository


def _position() -> Position:
    return Position.open(
        symbol=Symbol("BTC", "USDT"),
        direction=SignalDirection.LONG,
        quantity=Decimal("1.5"),
        average_entry_price=Decimal("60000"),
    )


def test_sqlite_runtime_state_repository_round_trips_current_position(tmp_path) -> None:
    repository = SqliteRuntimeStateRepository(tmp_path / "runtime.sqlite3")

    repository.save_position("btc-main", _position())
    loaded = repository.load_position("btc-main")

    assert loaded == _position()


def test_sqlite_runtime_state_repository_appends_position_events(tmp_path) -> None:
    repository = SqliteRuntimeStateRepository(tmp_path / "runtime.sqlite3")
    increase = PositionEvent.increase(
        direction=SignalDirection.LONG,
        quantity=Decimal("0.5"),
        price=Decimal("62000"),
    )
    decrease = PositionEvent.decrease(quantity=Decimal("0.25"))

    repository.append_position_event("btc-main", increase)
    repository.append_position_event("btc-main", decrease)

    assert repository.list_position_events("btc-main") == (increase, decrease)


def test_sqlite_runtime_state_repository_records_runtime_payloads(tmp_path) -> None:
    repository = SqliteRuntimeStateRepository(tmp_path / "runtime.sqlite3")

    repository.append_runtime_record(
        record_type="scheduler_run",
        record_id="run-1",
        payload={"status": "succeeded", "position_status": PositionStatus.OPEN.value},
    )

    records = repository.list_runtime_records("scheduler_run")
    assert len(records) == 1
    assert records[0].record_id == "run-1"
    assert records[0].payload == {
        "status": "succeeded",
        "position_status": "open",
    }
