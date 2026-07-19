import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _apply_sql_ddl(connection: sqlite3.Connection) -> None:
    for section in ("tables", "constraints", "indexes"):
        for path in sorted((ROOT / "sql" / "ddl").glob(f"*/{section}/*.sql")):
            connection.executescript(path.read_text(encoding="utf-8"))


def test_sql_ddl_includes_runtime_state_tables() -> None:
    connection = sqlite3.connect(":memory:")
    _apply_sql_ddl(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }

    assert {
        "runtime_positions",
        "runtime_position_events",
        "runtime_records",
    } <= tables


def test_persistence_schema_checks_do_not_report_common_column_false_positives() -> None:
    connection = sqlite3.connect(":memory:")
    _apply_sql_ddl(connection)
    statements = [
        statement.strip()
        for statement in (ROOT / "sql" / "tests" / "persistence_schema_checks.sql")
        .read_text(encoding="utf-8")
        .split(";")
        if statement.strip()
    ]

    violation_rows = []
    for statement in statements:
        rows = connection.execute(statement).fetchall()
        if rows and len(rows[0]) >= 2 and str(rows[0][0]).startswith("missing_"):
            violation_rows.extend(rows)

    assert violation_rows == []
