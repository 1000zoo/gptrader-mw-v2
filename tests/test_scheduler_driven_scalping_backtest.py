from datetime import datetime, timedelta, timezone
from decimal import Decimal

from scripts.scheduler_driven_scalping_backtest import run_scheduler_driven_backtest
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe


def test_scheduler_driven_backtest_uses_scheduler_path_without_external_io() -> None:
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    candles = tuple(
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            opened_at=opened_at + timedelta(minutes=index),
            closed_at=opened_at + timedelta(minutes=index + 1),
            open_price=Decimal("100"),
            high_price=Decimal("100"),
            low_price=Decimal("100"),
            close_price=Decimal("100"),
            volume=Decimal("10"),
        )
        for index in range(300)
    )

    result = run_scheduler_driven_backtest(
        MarketSnapshot(candles),
        start_at=candles[0].opened_at,
        end_at=candles[-1].closed_at,
    )

    assert result["engine"] == "scheduler_driven"
    assert result["scheduler_path"] == "TradeScheduler.run_trade_execution -> ExecuteTradeUseCase.execute"
    assert result["signal_count"] == 39
    assert result["trade_count"] == 0
