import asyncio

from src.job.vo.job.default import DefaultJobRunVo
from src.job.vo.job.filter import JobRunFilterVo
from src.job.service.job.job_run_service import JobRunService

service = JobRunService()

default_vo = DefaultJobRunVo(
    batch_id="TESTBTCUSDT202601130005",
    job_type="TEST",
    reg_ymd="20260113",
    status="TEST_CREATE",
    symbol_id='TESTBTCUSDT'
)

symbol_filter_vo = JobRunFilterVo(
    symbol_id="ETHUSDT"
)

status_filter_vo = JobRunFilterVo(
    job_type="1500"
)

symbol_status_filter_vo = JobRunFilterVo(
    job_type="1500",
    symbol_id="ETHUSDT"
)
def test_create():
    asyncio.run(service.create_job_run(default_vo))

def test_get():
    async def _inner():
        vo1 = await service.get_job_runs(symbol_filter_vo)
        vo2 = await service.get_job_runs(status_filter_vo)

        print(vo1)
        print(vo2)
    asyncio.run(_inner())

def test_update():
    default_vo.status = "TEST_UPDATE"
    asyncio.run(service.update_job_run(default_vo))

def test_delete():
    asyncio.run(service.delete_job_run('TESTBTCUSDT202601130001'))

def test_get_newest():
    print(asyncio.run(service.get_newest_job("TESTBTCUSDT")))

def test_get_open_position_job():
    a = asyncio.run(service.get_open_position_job("ETHUSDT"))
    print(a)

def test_get_failed_job():
    a = asyncio.run(service.get_failed_job())
    print(a)