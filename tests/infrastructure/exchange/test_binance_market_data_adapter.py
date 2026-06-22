from datetime import datetime, timedelta, timezone
from decimal import Decimal

from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.ports import MarketDataPort
from src.infrastructure.exchange.binance.binance_config import BinanceConfig
from src.infrastructure.exchange.binance.market_data import binance_market_data_adapter
from src.infrastructure.exchange.binance.market_data import BinanceMarketDataAdapter


def _kline_rows():
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


def test_binance_market_data_adapter_loads_domain_candles(monkeypatch):
    config = BinanceConfig.default()
    requests = []

    def fake_load_klines_api(
        received_config: BinanceConfig,
        symbol: str,
        interval: str,
        limit: int,
    ):
        requests.append((received_config, symbol, interval, limit))
        return _kline_rows()

    monkeypatch.setattr(
        binance_market_data_adapter,
        "load_klines_api",
        fake_load_klines_api,
    )
    adapter = BinanceMarketDataAdapter(config)
    symbol = Symbol("btc", "usdt")
    timeframe = Timeframe(1, "m")

    candles = adapter.load_candles(symbol, timeframe, limit=2)

    assert isinstance(adapter, MarketDataPort)
    assert requests == [(config, "BTCUSDT", "1m", 2)]
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


def test_binance_market_data_adapter_loads_snapshot(monkeypatch):
    monkeypatch.setattr(
        binance_market_data_adapter,
        "load_klines_api",
        lambda config, symbol, interval, limit: _kline_rows(),
    )
    adapter = BinanceMarketDataAdapter(BinanceConfig.default())

    snapshot = adapter.load_snapshot(Symbol("btc", "usdt"), Timeframe(1, "m"), limit=2)

    assert isinstance(snapshot, MarketSnapshot)
    assert snapshot.closed_at - snapshot.opened_at == timedelta(minutes=2)
    assert snapshot.latest_candle.close_price == Decimal("111.0")


def test_binance_market_data_adapter_loads_candles_between_with_pagination(
    monkeypatch,
):
    config = BinanceConfig.default()
    requests = []

    def fake_load_klines_api(
        received_config: BinanceConfig,
        symbol: str,
        interval: str,
        limit: int,
        start_time: int | None = None,
        end_time: int | None = None,
    ):
        requests.append(
            (received_config, symbol, interval, limit, start_time, end_time)
        )
        if len(requests) == 1:
            return [_kline_rows()[0]]
        return [_kline_rows()[1]]

    monkeypatch.setattr(
        binance_market_data_adapter,
        "load_klines_api",
        fake_load_klines_api,
    )
    adapter = BinanceMarketDataAdapter(config)
    symbol = Symbol("btc", "usdt")
    timeframe = Timeframe(1, "m")

    candles = adapter.load_candles_between(
        symbol=symbol,
        timeframe=timeframe,
        start_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        end_at=datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
        page_limit=1,
    )

    assert tuple(candle.opened_at for candle in candles) == (
        datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert requests == [
        (config, "BTCUSDT", "1m", 1, 1767225600000, 1767225720000),
        (config, "BTCUSDT", "1m", 1, 1767225660000, 1767225720000),
    ]
