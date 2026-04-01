import asyncio

from src.ops.service.scheduler.scheduler_service import SchedulerService


def test_find_by_name():
    async def _inner():
        service = SchedulerService()
        return await service.find_by_name("MainScheduler")
    ret = asyncio.run(_inner())
    assert ret.name == "MainScheduler"

