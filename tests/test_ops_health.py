import asyncio

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("loguru")

from src.ops.mw import ops_mw


class DummyResult:
    def scalar_one_or_none(self):
        return 1


class DummySession:
    async def execute(self, sql):
        return DummyResult()


class DummySessionContext:
    async def __aenter__(self):
        return DummySession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_ops_health_response(monkeypatch):
    monkeypatch.setattr("src.ops.mw.ops_mw.SessionLocal", lambda: DummySessionContext())
    response = asyncio.run(ops_mw.health_check())
    assert response["db"] is True
