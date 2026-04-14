from unittest.mock import Mock

import pytest

from src.binance.service.trader.trade_service import TradeService
from src.common.exception.external_api_error import ExternalApiError


def test_close_position_delegates_to_trade_api():
    service = object.__new__(TradeService)
    service.tradeApi = Mock()
    service.tradeApi.close_position.return_value = {"orderId": "123"}

    result = service.close_position("BTCUSDT")

    service.tradeApi.close_position.assert_called_once_with("BTCUSDT")
    assert result == {"orderId": "123"}


def test_close_position_raises_external_api_error_when_api_fails():
    service = object.__new__(TradeService)
    service.tradeApi = Mock()
    service.tradeApi.close_position.side_effect = ExternalApiError("boom")

    with pytest.raises(ExternalApiError, match="Failed to close position"):
        service.close_position("BTCUSDT")
