from pathlib import Path


def test_signal_log_schema_idempotency():
    content = Path("sql/001_create_signal_log.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS signal_log" in content
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_log_decision" in content
