from datetime import datetime, timezone
from inspect import signature
from typing import Protocol, get_type_hints

from src.domain.market import Symbol, Timeframe
from src.domain.market_feature import MarketFeatureSet
from src.domain.ports import MarketFeatureProviderPort


class EmptyMarketFeatureProvider:
    def load_features(
        self,
        symbol: Symbol,
        timeframe: Timeframe,
        as_of: datetime,
    ) -> MarketFeatureSet:
        return MarketFeatureSet(symbol, timeframe, as_of, ())


def test_market_feature_provider_port_is_runtime_checkable_protocol():
    provider = EmptyMarketFeatureProvider()

    assert issubclass(MarketFeatureProviderPort, Protocol)
    assert isinstance(provider, MarketFeatureProviderPort)
    assert provider.load_features(
        Symbol("BTC", "USDT"),
        Timeframe(1, "m"),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    ).values == ()


def test_market_feature_provider_port_load_features_signature():
    load_features_signature = signature(MarketFeatureProviderPort.load_features)
    type_hints = get_type_hints(MarketFeatureProviderPort.load_features)

    assert tuple(load_features_signature.parameters) == (
        "self",
        "symbol",
        "timeframe",
        "as_of",
    )
    assert type_hints["symbol"] is Symbol
    assert type_hints["timeframe"] is Timeframe
    assert type_hints["as_of"] is datetime
    assert type_hints["return"] is MarketFeatureSet
