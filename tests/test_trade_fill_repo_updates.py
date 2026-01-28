import asyncio

import pytest

pytest.importorskip("loguru")

from src.trade.repository.trade_fill.trade_fill_repo import TradeFillRepository


class DummyResult:
    rowcount = 1


class DummySession:
    def __init__(self):
        self.executed = []

    async def execute(self, sql, params=None):
        self.executed.append((str(sql), params))
        return DummyResult()

    async def commit(self):
        return None


class DummySessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_update_entry_fill_sql(monkeypatch):
    repo = TradeFillRepository()
    session = DummySession()
    monkeypatch.setattr(
        "src.trade.repository.trade_fill.trade_fill_repo.SessionLocal",
        lambda: DummySessionContext(session),
    )
    asyncio.run(repo.update_entry_fill("order-1", 100.0, 1.0, 0.1, None))
    assert session.executed
    sql_text, params = session.executed[0]
    assert "UPDATE trade_fill" in sql_text
    assert params["entry_order_id"] == "order-1"


def test_update_exit_fill_sql(monkeypatch):
    repo = TradeFillRepository()
    session = DummySession()
    monkeypatch.setattr(
        "src.trade.repository.trade_fill.trade_fill_repo.SessionLocal",
        lambda: DummySessionContext(session),
    )
    asyncio.run(
        repo.update_exit_fill(
            "order-1",
            "exit-1",
            110.0,
            0.2,
            None,
            5.0,
            0.05,
            1.2,
            "CLOSED",
        )
    )
    sql_text, params = session.executed[0]
    assert "exit_order_id" in sql_text
    assert params["status"] == "CLOSED"
