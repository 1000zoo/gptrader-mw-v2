from datetime import date

from src.observability.logging import configure_runtime_logging, runtime_logger


def test_configure_runtime_logging_writes_to_dated_file(tmp_path) -> None:
    log_file = configure_runtime_logging(
        log_root=tmp_path,
        current_date=date(2026, 6, 21),
    )

    runtime_logger.info("dry-run started", symbol="BTCUSDT", mode="dry-run")

    assert log_file == tmp_path / "2026-06-21" / "runtime.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "dry-run started" in content
    assert "BTCUSDT" in content
    assert "dry-run" in content


def test_runtime_logger_records_exception_details(tmp_path) -> None:
    log_file = configure_runtime_logging(
        log_root=tmp_path,
        current_date=date(2026, 6, 21),
    )

    try:
        raise RuntimeError("exchange rejected order: insufficient margin")
    except RuntimeError:
        runtime_logger.exception("dry-run execution failed", signal_id="signal-1")

    content = log_file.read_text(encoding="utf-8")
    assert "dry-run execution failed" in content
    assert "signal-1" in content
    assert "RuntimeError" in content
    assert "insufficient margin" in content
