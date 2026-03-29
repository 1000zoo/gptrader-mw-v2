import asyncio
import os
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from loguru import logger

from src.app.schedulers.strategy.strategy_scheduler import execute as exit_strategy_execute
from src.common.logger.logger_config import setup_logging
from src.scheduler.executor import execute as scheduler_execute

DEFAULT_EXECUTE_INTERVAL_SECONDS = 3600
DEFAULT_RESEARCH_INTERVAL_SECONDS = 3600
DEFAULT_RISK_EXECUTE_INTERVAL_SECONDS = 60
DEFAULT_EXIT_EXECUTE_INTERVAL_SECONDS = 60


def tznow(scheduler: AsyncIOScheduler) -> datetime:
    return datetime.now(scheduler.timezone)


def _get_interval_seconds(env_key: str, default_value: int) -> int:
    raw_value: Optional[str] = os.getenv(env_key)
    if not raw_value:
        return default_value
    try:
        return max(1, int(raw_value))
    except ValueError:
        logger.warning(f"invalid {env_key}: {raw_value}. using default {default_value}s")
        return default_value


async def setup_scheduler() -> None:
    scheduler = AsyncIOScheduler(
        timezone="Asia/Seoul",
        job_defaults={
            "coalesce": False,
            "misfire_grace_time": 120,
            "max_instances": 1,
        },
    )
    logger.info("scheduler setup start")

    execute_interval = _get_interval_seconds(
        "SCHEDULER_EXECUTE_INTERVAL_SECONDS",
        DEFAULT_EXECUTE_INTERVAL_SECONDS,
    )
    research_interval = _get_interval_seconds(
        "RESEARCH_JOB_INTERVAL_SECONDS",
        DEFAULT_RESEARCH_INTERVAL_SECONDS,
    )
    risk_execute_interval = _get_interval_seconds(
        "RISK_EXECUTE_INTERVAL_SECONDS",
        DEFAULT_RISK_EXECUTE_INTERVAL_SECONDS,
    )
    exit_execute_interval = _get_interval_seconds(
        "EXIT_EXECUTE_INTERVAL_SECONDS",
        DEFAULT_EXIT_EXECUTE_INTERVAL_SECONDS
    )

    scheduler.add_job(
        scheduler_execute,
        "interval",
        seconds=execute_interval,
        id="execute_job",
        next_run_time=tznow(scheduler),
        coalesce=True,
        misfire_grace_time=300,
    )

    # scheduler.add_job(
    #     run_from_env,
    #     "interval",
    #     seconds=research_interval,
    #     id="research_job",
    #     next_run_time=tznow(scheduler),
    #     coalesce=True,
    #     misfire_grace_time=600,
    # )

    scheduler.add_job(
        exit_strategy_execute,
        "interval",
        seconds=exit_execute_interval,
        id="exit_strategy_monitoring",
        next_run_time=tznow(scheduler),
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info("scheduler started")

    await asyncio.Event().wait()


if __name__ == "__main__":
    load_dotenv(dotenv_path=".env")

    LOG_DIR = os.getenv("LOG_DIR")
    LOG_LEVEL = os.getenv("LOG_LEVEL")

    setup_logging(app_name="scheduler", log_dir=LOG_DIR, level=LOG_LEVEL)

    try:
        asyncio.run(setup_scheduler())
    except Exception as e:
        logger.exception(f"[MAIN] Scheduler crashed: {e}")
