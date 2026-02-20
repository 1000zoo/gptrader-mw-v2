import asyncio
import types

import pytest

from src.common.exception.data_not_found_exception import DataNotFoundException
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.strategy.service.strategy.strategy_service import StrategyService
from src.strategy.strategies.IStrategy import IStrategy
from src.strategy.vo.strategy.default import DefaultStrategyVo


class DummyLoadedStrategy(IStrategy):
    def run_strategy(self, data):
        return self._hold("ok")


class NotAStrategy:
    pass


def test_build_strategy_instance_success(monkeypatch):
    service = StrategyService()

    async def fake_select(strategy_name, only_active=True):
        assert strategy_name == "dummy"
        assert only_active is True
        return DefaultStrategyVo(
            strategy_name="dummy",
            module_path="tests.dummy_strategy_module",
            module_name="DummyLoadedStrategy",
            use_yn="Y",
        )

    module = types.ModuleType("tests.dummy_strategy_module")
    module.DummyLoadedStrategy = DummyLoadedStrategy

    monkeypatch.setattr(service.repository, "select_strategy_by_name", fake_select)
    monkeypatch.setattr("importlib.import_module", lambda path: module)

    strategy = asyncio.run(service.build_strategy_instance("dummy"))

    assert isinstance(strategy, DummyLoadedStrategy)


def test_build_strategy_instance_raises_on_missing_strategy(monkeypatch):
    service = StrategyService()

    async def fake_select(strategy_name, only_active=True):
        return None

    monkeypatch.setattr(service.repository, "select_strategy_by_name", fake_select)

    with pytest.raises(DataNotFoundException):
        asyncio.run(service.build_strategy_instance("missing"))


def test_build_strategy_instance_raises_on_invalid_class(monkeypatch):
    service = StrategyService()

    async def fake_select(strategy_name, only_active=True):
        return DefaultStrategyVo(
            strategy_name="bad",
            module_path="tests.bad_strategy_module",
            module_name="NotAStrategy",
            use_yn="Y",
        )

    module = types.ModuleType("tests.bad_strategy_module")
    module.NotAStrategy = NotAStrategy

    monkeypatch.setattr(service.repository, "select_strategy_by_name", fake_select)
    monkeypatch.setattr("importlib.import_module", lambda path: module)

    with pytest.raises(InvalidRequestException):
        asyncio.run(service.build_strategy_instance("bad"))
