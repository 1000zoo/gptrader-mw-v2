from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep as default_sleep
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.runtime import RuntimeSettings, create_local_runtime  # noqa: E402


Emit = Callable[[str], None]
Sleep = Callable[[float], None]
Now = Callable[[], datetime]


@dataclass(frozen=True)
class SchedulerConfig:
    interval_seconds: int
    signal_id_prefix: str


def parse_interval_seconds(value: str) -> int:
    interval_seconds = int(value)
    if interval_seconds <= 0:
        raise ValueError("scheduler interval must be positive")
    return interval_seconds


def build_signal_id(prefix: str, now: datetime, sequence: int) -> str:
    timestamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{timestamp}-{sequence:06d}"


def run_scheduler(
    *,
    runtime,
    config: SchedulerConfig,
    max_runs: int | None = None,
    now: Now | None = None,
    sleep: Sleep | None = None,
    emit: Emit | None = None,
) -> None:
    now = now or _utc_now
    sleep = sleep or default_sleep
    emit = emit or print
    sequence = 0

    emit(
        "live strategy scheduler started "
        f"interval_seconds={config.interval_seconds} "
        f"signal_id_prefix={config.signal_id_prefix}"
    )
    while max_runs is None or sequence < max_runs:
        sequence += 1
        signal_id = build_signal_id(config.signal_id_prefix, now(), sequence)
        started_at = now().astimezone(timezone.utc).isoformat()
        try:
            result = runtime.run_trade_execution_once(signal_id)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            emit(f"{started_at} signal_id={signal_id} error={exc}")
        else:
            status = getattr(result.status, "value", str(result.status))
            order_result = getattr(result, "order_result", None)
            order_status = (
                None
                if order_result is None
                else getattr(order_result.status, "value", str(order_result.status))
            )
            reason = getattr(result, "reason", None)
            emit(
                f"{started_at} signal_id={signal_id} "
                f"status={status} order_status={order_status} reason={reason}"
            )

        if max_runs is None or sequence < max_runs:
            sleep(config.interval_seconds)


def main() -> int:
    settings = RuntimeSettings.from_env(os.environ)
    interval_seconds = parse_interval_seconds(
        os.getenv("GPTRADER_SCHEDULER_INTERVAL_SECONDS", "60")
    )
    config = SchedulerConfig(
        interval_seconds=interval_seconds,
        signal_id_prefix=settings.signal_id_prefix,
    )
    runtime = create_local_runtime(settings)
    try:
        run_scheduler(runtime=runtime, config=config)
    except KeyboardInterrupt:
        print("live strategy scheduler stopped")
    return 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


if __name__ == "__main__":
    raise SystemExit(main())
