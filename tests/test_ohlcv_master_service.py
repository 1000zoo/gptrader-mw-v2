from __future__ import annotations

import pytest

from src.binance.service.ohlcv.ohlcv_master_service import OhlcvMasterService

pytestmark = pytest.mark.asyncio


async def test_delete_candles_deletes_in_10000_chunks(monkeypatch):
    service = OhlcvMasterService()
    calls: list[tuple[int, str]] = []

    async def fake_count_total_candles() -> int:
        return 25000

    async def fake_delete_candles(limit: int = 10000, symbol: str = "%") -> int:
        calls.append((limit, symbol))
        return limit

    monkeypatch.setattr(service.ohlcvService, "count_total_candles", fake_count_total_candles)
    monkeypatch.setattr(service.ohlcvService, "delete_candles", fake_delete_candles)

    deleted = await service.delete_candles()

    assert deleted == 25000
    assert calls == [(10000, "%"), (10000, "%"), (5000, "%")]


async def test_delete_candles_returns_zero_when_no_rows(monkeypatch):
    service = OhlcvMasterService()
    calls: list[tuple[int, str]] = []

    async def fake_count_total_candles() -> int:
        return 0

    async def fake_delete_candles(limit: int = 10000, symbol: str = "%") -> int:
        calls.append((limit, symbol))
        return limit

    monkeypatch.setattr(service.ohlcvService, "count_total_candles", fake_count_total_candles)
    monkeypatch.setattr(service.ohlcvService, "delete_candles", fake_delete_candles)

    deleted = await service.delete_candles()

    assert deleted == 0
    assert calls == []
