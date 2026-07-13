from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import zipfile

import pytest

from scripts.validate_scalping_external_periods import (
    BTC_RECHECK_PERIODS,
    PeriodSpec,
    candle_from_record,
    download_archive_candles,
    end_exclusive,
    summarize_period_result,
)


def test_download_archive_candles_prefers_local_binance_raw_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_root = tmp_path / "raw" / "klines"
    archive_path = archive_root / "BTCUSDT" / "BTCUSDT-1m-2025-07.zip"
    archive_path.parent.mkdir(parents=True)
    csv_path = "BTCUSDT-1m-2025-07.csv"
    row = [
        "1751328000000",
        "100",
        "101",
        "99",
        "100.5",
        "10",
        "1751328059999",
        "1000",
        "20",
        "5",
        "500",
        "0",
    ]
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(csv_path, ",".join(row) + "\n")

    def fail_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network should not be used for a cached archive")

    monkeypatch.setattr(
        "scripts.validate_scalping_external_periods.urlopen",
        fail_network,
    )

    candles = download_archive_candles(
        "https://data.binance.vision/data/futures/um/monthly/klines/"
        "BTCUSDT/1m/BTCUSDT-1m-2025-07.zip",
        "BTCUSDT",
        archive_cache_root=archive_root,
    )

    assert len(candles) == 1
    assert candles[0].open_price == Decimal("100")
    assert candles[0].closed_at == datetime(2025, 7, 1, 0, 1, tzinfo=timezone.utc)


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


def test_btc_recheck_periods_match_requested_windows() -> None:
    assert len(BTC_RECHECK_PERIODS) == 10
    assert BTC_RECHECK_PERIODS[0] == (
        "BTCUSDT",
        "btc-recheck-2020-11-01_2021-01-31",
        "2020/11/1",
        "2021/1/31",
    )
    assert BTC_RECHECK_PERIODS[-1] == (
        "BTCUSDT",
        "btc-recheck-2025-10-06_2025-12-01",
        "2025/10/6",
        "2025/12/1",
    )


def test_summarize_period_result_records_cost_model() -> None:
    result = summarize_period_result(
        PeriodSpec("BTCUSDT", "costed", "2025/1/1", "2025/1/1"),
        None,
        cost_model={
            "venue": "binance_usd_m_futures",
            "fee_rate_per_side": "0.0004",
            "slippage_rate_per_side": "0.0002",
        },
    )

    assert result["cost_model"]["venue"] == "binance_usd_m_futures"
    assert result["cost_model"]["fee_rate_per_side"] == "0.0004"
    assert result["cost_model"]["slippage_rate_per_side"] == "0.0002"


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
