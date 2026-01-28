import asyncio
import os
from typing import Optional

from dotenv import load_dotenv
from loguru import logger

from src.common.logger.logger_config import setup_logging
from src.scheduler.executor import execute as scheduler_execute

INTERVAL_SECONDS=600

class SchedulerRunner:
    def __init__(self, interval_seconds: int = INTERVAL_SECONDS):
        self.interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()

    async def run_once(self):
        return await scheduler_execute()

    async def execute(self):
        logger.info("scheduler started")
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except Exception as exc:
                logger.exception(f"scheduler execution failed: {exc}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue

    def stop(self):
        self._stop_event.set()


def _get_interval_seconds() -> int:
    raw_value: Optional[str] = os.getenv("SCHEDULER_INTERVAL_SECONDS")
    if not raw_value:
        return INTERVAL_SECONDS
    try:
        return max(1, int(raw_value))
    except ValueError:
        logger.warning(f"invalid SCHEDULER_INTERVAL_SECONDS: {raw_value}. using default 60s")
        return INTERVAL_SECONDS


async def _main():
    runner = SchedulerRunner(interval_seconds=_get_interval_seconds())
    await runner.execute()


if __name__ == "__main__":
    load_dotenv(dotenv_path=".env")

    LOG_DIR = os.getenv("LOG_DIR")
    LOG_LEVEL = os.getenv("LOG_LEVEL")

    setup_logging(app_name="scheduler", log_dir=LOG_DIR, level=LOG_LEVEL)

    asyncio.run(_main())
