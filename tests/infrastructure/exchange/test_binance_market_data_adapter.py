from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.ports import MarketDataPort
from src.infrastructure.exchange.binance.market_data import BinanceMarketDataAdapter


class FakeBinanceMarketClient:
    def __init__(self) -> None:
        self.requests = []

    def get_klines(self, symbol: str, interval: str, limit: int):
        self.requests.append((symbol, interval, limit))
        return [
            [
                1767225600000,
                "100.0",
                "110.0",
                "90.0",
                "105.0",
                "12.5",
                1767225659999,
            ],
            [
                1767225660000,
                "105.0",
                "115.0",
                "95.0",
                "111.0",
                "8.25",
                1767225719999,
            ],
        ]


def test_binance_market_data_adapter_loads_domain_candles():
    client = FakeBinanceMarketClient()
    adapter = BinanceMarketDataAdapter(client)
    symbol = Symbol("btc", "usdt")
    timeframe = Timeframe(1, "m")

    candles = adapter.load_candles(symbol, timeframe, limit=2)

    assert isinstance(adapter, MarketDataPort)
    assert client.requests == [("BTCUSDT", "1m", 2)]
    assert candles == (
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            opened_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            closed_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            open_price=Decimal("100.0"),
            high_price=Decimal("110.0"),
            low_price=Decimal("90.0"),
            close_price=Decimal("105.0"),
            volume=Decimal("12.5"),
        ),
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            opened_at=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            closed_at=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            open_price=Decimal("105.0"),
            high_price=Decimal("115.0"),
            low_price=Decimal("95.0"),
            close_price=Decimal("111.0"),
            volume=Decimal("8.25"),
        ),
    )


def test_binance_market_data_adapter_loads_snapshot():
    adapter = BinanceMarketDataAdapter(FakeBinanceMarketClient())

    snapshot = adapter.load_snapshot(Symbol("btc", "usdt"), Timeframe(1, "m"), limit=2)

    assert isinstance(snapshot, MarketSnapshot)
    assert snapshot.closed_at - snapshot.opened_at == timedelta(minutes=2)
    assert snapshot.latest_candle.close_price == Decimal("111.0")
