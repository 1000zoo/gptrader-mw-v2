from datetime import datetime, timezone
from decimal import Decimal

from scripts.validate_scalping_external_periods import (
    PeriodSpec,
    candle_from_record,
    end_exclusive,
    summarize_period_result,
)


def test_end_exclusive_includes_requested_end_date() -> None:
    assert end_exclusive("2022/1/31") == datetime(2022, 2, 1, tzinfo=timezone.utc)


def test_summarize_period_result_marks_missing_data() -> None:
    result = summarize_period_result(
        PeriodSpec("ETHUSDT", "missing", "2019/2/1", "2019/3/31"),
        None,
    )

    assert result["status"] == "no_data"
    assert result["symbol"] == "ETHUSDT"


def test_summarize_period_result_includes_scalping_metrics() -> None:
    metrics = {
        "trade_count": 31,
        "gross_win_rate": Decimal("0.75"),
        "net_win_rate": Decimal("0.60"),
        "average_gross_trade_return": Decimal("0.001"),
        "average_gross_trade_roe": Decimal("0.004"),
        "average_net_trade_return": Decimal("0.0002"),
        "return_ratio": Decimal("0.12"),
        "max_drawdown_ratio": Decimal("0.03"),
        "gross_pnl": Decimal("1210"),
        "fee_paid": Decimal("10"),
        "net_pnl": Decimal("1200"),
    }

    result = summarize_period_result(
        PeriodSpec("BTCUSDT", "jan-2022", "2022/1/1", "2022/1/31"),
        metrics,
    )

    assert result["status"] == "ok"
    assert result["trade_count"] == 31
    assert result["trades_per_day"] == "1"
    assert result["average_gross_trade_roe"] == "0.004"


def test_candle_from_record_restores_symbol_and_closed_at() -> None:
    candle = candle_from_record(
        {
            "opened_at": "2020-12-01T00:00:00+00:00",
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100.5",
            "volume": "10",
        },
        "ETHUSDT",
    )

    assert candle.symbol.pair == "ETHUSDT"
    assert candle.closed_at.isoformat() == "2020-12-01T00:01:00+00:00"
