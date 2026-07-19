from decimal import Decimal

from src.domain.ports import SignalLogEntry, SignalLogRepositoryPort
from src.domain.signal import Signal, SignalDirection, SignalReason
from src.domain.signal_generator import GeneratedSignal
from src.domain.strategy import StrategyResult
from src.infrastructure.persistence.repositories import SqliteSignalLogRepository


def test_sqlite_signal_log_repository_round_trips_generated_signals(tmp_path):
    repository = SqliteSignalLogRepository(tmp_path / "signals.sqlite3")
    generated = GeneratedSignal(
        signal=Signal(
            direction=SignalDirection.LONG,
            confidence=Decimal("0.82"),
            reasons=(
                SignalReason(
                    code="trend",
                    message="trend confirmed",
                    metadata={"ema": "aligned"},
                ),
            ),
            metadata={"timeframe": "1m"},
        ),
        strategy_results=(
            StrategyResult(
                name="trend-following",
                signal=Signal(direction=SignalDirection.LONG, confidence=Decimal("0.8")),
                metadata={"score": "high"},
            ),
        ),
        metadata={"source": "dry-run"},
    )
    entry = SignalLogEntry(
        signal_id="signal-1",
        generator_id="generator-1",
        generated_signal=generated,
    )

    repository.append_signal(entry)

    assert isinstance(repository, SignalLogRepositoryPort)
    assert repository.list_signals_for_generator("generator-1") == (entry,)
    assert repository.list_signals_for_generator("unknown") == ()
