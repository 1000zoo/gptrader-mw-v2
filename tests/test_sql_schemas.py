from pathlib import Path


def test_signal_log_schema_idempotency():
    content = Path("sql/001_create_signal_log.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS signal_log" in content
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_signal_log_decision" in content


def test_scheduler_schema_idempotency():
    content = Path("sql/012_create_scheduler.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS scheduler" in content
    assert "UNIQUE (name)" in content


def test_scheduler_schema_exists_in_init_sql():
    content = Path("sql/init.sql").read_text()
    assert "CREATE TABLE public.scheduler (" in content
    assert "last_run_dt timestamp with time zone" in content
