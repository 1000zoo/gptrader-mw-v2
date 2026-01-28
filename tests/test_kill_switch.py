import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("loguru")

from src.ops.service.kill_switch.kill_switch_service import KillSwitchService


def test_kill_switch_trigger(monkeypatch):
    monkeypatch.setenv("ENABLE_KILL_SWITCH", "true")
    monkeypatch.setenv("KILL_EV_WINDOW_N", "2")
    monkeypatch.setenv("KILL_EV_THRESHOLD", "-0.01")
    service = KillSwitchService()

    async def fake_find_recent(limit):
        return [SimpleNamespace(r_multiple=-0.5, pnl_usd=-10, exit_ts=None)]

    async def fake_anomalies(since_ts):
        return 0

    async def fake_latest_state():
        return None

    created = {}

    async def fake_create_state(vo):
        created["state"] = vo
        return 1

    service.trade_fill_service.find_recent_closed_trades = fake_find_recent
    service.execution_anomaly_service.count_recent_anomalies = fake_anomalies
    service.system_state_service.find_latest_state = fake_latest_state
    service.system_state_service.create_system_state = fake_create_state

    allowed = asyncio.run(service.evaluate_and_update())
    assert allowed is False
    assert created["state"].trading_enabled is False
