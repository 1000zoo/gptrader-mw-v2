import pytest

from src.domain.market import Symbol


def test_symbol_normalizes_assets_and_exposes_pair():
    symbol = Symbol("btc", "usdt")

    assert symbol.base_asset == "BTC"
    assert symbol.quote_asset == "USDT"
    assert symbol.pair == "BTCUSDT"


def test_symbol_rejects_blank_assets():
    with pytest.raises(ValueError, match="base_asset"):
        Symbol("", "USDT")

    with pytest.raises(ValueError, match="quote_asset"):
        Symbol("BTC", " ")


def test_symbol_rejects_same_base_and_quote_assets():
    with pytest.raises(ValueError, match="different"):
        Symbol("BTC", "btc")
