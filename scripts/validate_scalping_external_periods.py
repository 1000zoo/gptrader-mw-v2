from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO, TextIOWrapper
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_combo_search import Combo, FixedRatioTakeProfitStopLossStrategy, candle_record  # noqa: E402
from scripts.scalping_train_test_combo_search import (  # noqa: E402
    RegimeRouterScalper,
    QualityVolatilitySizingStrategy,
    _simulate_scalping_fast,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe  # noqa: E402


TIMEFRAME = Timeframe(1, "m")
RESULTS_PATH = Path("docs/backtests/scalping-external-period-validation.json")
SUMMARY_PATH = Path("docs/backtests/scalping-external-period-validation.md")
CACHE_DIR = Path("docs/backtests/cache/external-periods")


PERIODS = (
    ("BTCUSDT", "btc-2020-12-01_2021-01-31", "2020/12/1", "2021/1/31"),
    ("BTCUSDT", "btc-2021-05-01_2021-07-31", "2021/5/1", "2021/7/31"),
    ("BTCUSDT", "btc-2022-01-01_2022-01-31", "2022/1/1", "2022/1/31"),
    ("BTCUSDT", "btc-2023-03-01_2023-05-31", "2023/3/1", "2023/5/31"),
    ("BTCUSDT", "btc-2024-08-01_2024-09-01", "2024/8/1", "2024/9/1"),
    ("BTCUSDT", "btc-2025-08-03_2025-10-31", "2025/8/3", "2025/10/31"),
    ("ETHUSDT", "eth-2019-02-01_2019-03-31", "2019/2/1", "2019/3/31"),
    ("ETHUSDT", "eth-2019-05-01_2019-06-30", "2019/5/1", "2019/6/30"),
    ("ETHUSDT", "eth-2020-12-01_2021-01-31", "2020/12/1", "2021/1/31"),
    ("ETHUSDT", "eth-2021-09-01_2021-11-30", "2021/9/1", "2021/11/30"),
    ("ETHUSDT", "eth-2022-03-01_2022-03-31", "2022/3/1", "2022/3/31"),
    ("ETHUSDT", "eth-2022-06-01_2022-06-30", "2022/6/1", "2022/6/30"),
    ("ETHUSDT", "eth-2023-09-01_2023-09-30", "2023/9/1", "2023/9/30"),
    ("ETHUSDT", "eth-2024-05-01_2024-05-31", "2024/5/1", "2024/5/31"),
    ("ETHUSDT", "eth-2025-06-01_2025-09-30", "2025/6/1", "2025/9/30"),
)


@dataclass(frozen=True)
class PeriodSpec:
    symbol: str
    label: str
    start: str
    end: str

    @property
    def start_at(self) -> datetime:
        return parse_date(self.start)

    @property
    def end_at(self) -> datetime:
        return end_exclusive(self.end)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", choices=("BTCUSDT", "ETHUSDT"), default="")
    args = parser.parse_args()

    selected = [
        PeriodSpec(*period)
        for period in PERIODS
        if not args.symbol or period[0] == args.symbol
    ]
    results = []
    for period in selected:
        print(f"running {period.symbol} {period.start}~{period.end}", flush=True)
        market = load_period_market(period)
        metrics = None if market is None else run_selected_combo(market, period)
        result = summarize_period_result(period, metrics)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if args.symbol:
        path = RESULTS_PATH.with_name(
            f"{RESULTS_PATH.stem}-{args.symbol.lower()}{RESULTS_PATH.suffix}"
        )
        summary_path = SUMMARY_PATH.with_name(
            f"{SUMMARY_PATH.stem}-{args.symbol.lower()}{SUMMARY_PATH.suffix}"
        )
    else:
        path = RESULTS_PATH
        summary_path = SUMMARY_PATH
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    summary_path.write_text(markdown_summary(results), encoding="utf-8")
    print(f"RESULTS {path}")
    print(f"SUMMARY {summary_path}")


def run_selected_combo(market: MarketSnapshot, period: PeriodSpec) -> dict[str, object]:
    combo = selected_combo()
    return _simulate_scalping_fast(
        market=market,
        combo=combo,
        start_at=period.start_at,
        end_at=period.end_at,
        fee_rate=0.0004,
    )


def selected_combo() -> Combo:
    strategy_params = {
        "trend_params": {
            "trend_period": 60,
            "pullback_period": 5,
            "trigger_period": 1,
            "min_trend_return": Decimal("0.002"),
            "min_pullback": Decimal("0.0006"),
            "min_trigger_return": Decimal("0.0002"),
            "min_range_ratio": Decimal("0.0008"),
        },
        "range_params": {
            "range_period": 45,
            "edge_ratio": Decimal("0.18"),
            "min_reversal_body_ratio": Decimal("0.15"),
            "min_range_ratio": Decimal("0.0015"),
        },
        "burst_params": {
            "breakout_period": 12,
            "impulse_period": 1,
            "volume_period": 20,
            "min_impulse_return": Decimal("0.0008"),
            "min_volume_ratio": Decimal("1.0"),
            "breakout_buffer": Decimal("0.0000"),
            "mode": "fade",
        },
        "router_order": ("trend", "burst", "range"),
        "max_abs_trend_for_range": Decimal("0.008"),
        "range_regime_period": 240,
        "trend_regime_period": 240,
    }
    tpsl_params = {
        "kind": "fixed",
        "stop_loss_ratio": Decimal("0.0050"),
        "reward_risk_ratio": Decimal("0.25"),
    }
    sizing_params = {
        "kind": "quality-volatility",
        "min_equity_ratio": Decimal("0.02"),
        "max_equity_ratio": Decimal("0.12"),
        "min_leverage": Decimal("2"),
        "max_leverage": Decimal("8"),
    }
    return Combo(
        combo_id="scalp-multi-t1-r1-b4-router-tbr-sl0050-rr0_25-p2",
        strategy_factory=RegimeRouterScalper,
        strategy_params=strategy_params,
        tpsl_factory=lambda: FixedRatioTakeProfitStopLossStrategy(
            stop_loss_ratio=tpsl_params["stop_loss_ratio"],
            reward_risk_ratio=tpsl_params["reward_risk_ratio"],
        ),
        tpsl_params=tpsl_params,
        position_sizing_factory=lambda: QualityVolatilitySizingStrategy(
            min_equity_ratio=sizing_params["min_equity_ratio"],
            max_equity_ratio=sizing_params["max_equity_ratio"],
            min_leverage=sizing_params["min_leverage"],
            max_leverage=sizing_params["max_leverage"],
        ),
        position_sizing_params=sizing_params,
    )


def summarize_period_result(period: PeriodSpec, metrics: dict[str, object] | None) -> dict[str, object]:
    days = Decimal(str((period.end_at - period.start_at).total_seconds())) / Decimal("86400")
    base = {
        "symbol": period.symbol,
        "label": period.label,
        "start_at": period.start_at.isoformat(),
        "end_at": period.end_at.isoformat(),
        "days": str(days),
    }
    if metrics is None:
        return {**base, "status": "no_data"}
    trade_count = int(metrics["trade_count"])
    trades_per_day = Decimal(trade_count) / days if days else Decimal("0")
    return {
        **base,
        "status": "ok",
        "trade_count": trade_count,
        "trades_per_day": str(trades_per_day),
        "gross_win_rate": str(metrics["gross_win_rate"]),
        "net_win_rate": str(metrics["net_win_rate"]),
        "average_gross_trade_return": str(metrics["average_gross_trade_return"]),
        "average_gross_trade_roe": str(metrics["average_gross_trade_roe"]),
        "average_net_trade_return": str(metrics["average_net_trade_return"]),
        "return_ratio": str(metrics["return_ratio"]),
        "max_drawdown_ratio": str(metrics["max_drawdown_ratio"]),
        "net_pnl": str(metrics["net_pnl"]),
        "fee_paid": str(metrics["fee_paid"]),
        "gross_pnl": str(metrics["gross_pnl"]),
    }


def load_period_market(period: PeriodSpec) -> MarketSnapshot | None:
    cache_path = CACHE_DIR / f"{period.label}-{period.symbol.lower()}-1m.jsonl"
    if cache_path.exists():
        candles = read_cache(cache_path, period.symbol)
        return MarketSnapshot(candles) if candles else None
    candles = load_public_futures_archives(
        symbol=period.symbol,
        start_at=period.start_at,
        end_at=period.end_at,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8") as handle:
        for candle in candles:
            handle.write(json.dumps(candle_record(candle), sort_keys=True) + "\n")
    return MarketSnapshot(candles) if candles else None


def load_public_futures_archives(*, symbol: str, start_at: datetime, end_at: datetime) -> tuple[Candle, ...]:
    candles = []
    for year, month in months_between(start_at, end_at):
        candles.extend(download_archive_candles(monthly_url(symbol, year, month), symbol))
        time.sleep(0.05)
    selected = [candle for candle in candles if start_at <= candle.opened_at < end_at]
    selected.sort(key=lambda candle: candle.opened_at)
    unique = {candle.opened_at: candle for candle in selected}
    return tuple(unique.values())


def download_archive_candles(url: str, symbol_value: str) -> tuple[Candle, ...]:
    try:
        with urlopen(url, timeout=60) as response:
            payload = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return ()
        raise
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as raw:
            reader = csv.reader(TextIOWrapper(raw, encoding="utf-8"))
            return tuple(
                candle_from_csv_row(row, symbol_value)
                for row in reader
                if row and row[0] != "open_time"
            )


def candle_from_csv_row(row: list[str], symbol_value: str) -> Candle:
    symbol = parse_symbol(symbol_value)
    opened_at = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
    return Candle(
        symbol=symbol,
        timeframe=TIMEFRAME,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=1),
        open_price=Decimal(row[1]),
        high_price=Decimal(row[2]),
        low_price=Decimal(row[3]),
        close_price=Decimal(row[4]),
        volume=Decimal(row[5]),
    )


def read_cache(path: Path, symbol_value: str) -> tuple[Candle, ...]:
    return tuple(
        candle_from_record(json.loads(line), symbol_value)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def candle_from_record(record: dict[str, object], symbol_value: str) -> Candle:
    opened_at = datetime.fromisoformat(str(record["opened_at"]))
    return Candle(
        symbol=parse_symbol(symbol_value),
        timeframe=TIMEFRAME,
        opened_at=opened_at,
        closed_at=opened_at + timedelta(minutes=1),
        open_price=Decimal(str(record["open"])),
        high_price=Decimal(str(record["high"])),
        low_price=Decimal(str(record["low"])),
        close_price=Decimal(str(record["close"])),
        volume=Decimal(str(record["volume"])),
    )


def markdown_summary(results: list[dict[str, object]]) -> str:
    lines = [
        "# Scalping External Period Validation",
        "",
        "| Symbol | Period | Status | Trades/day | Gross win | Avg gross ROE | Return | Max DD | Trades |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        if result["status"] != "ok":
            lines.append(
                f"| {result['symbol']} | {result['label']} | no_data |  |  |  |  |  |  |"
            )
            continue
        lines.append(
            "| {symbol} | {label} | ok | {trades_per_day} | {gross_win_rate} | "
            "{average_gross_trade_roe} | {return_ratio} | {max_drawdown_ratio} | {trade_count} |".format(
                **result
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_date(value: str) -> datetime:
    year, month, day = (int(part) for part in value.split("/"))
    return datetime(year, month, day, tzinfo=timezone.utc)


def end_exclusive(value: str) -> datetime:
    return parse_date(value) + timedelta(days=1)


def parse_symbol(value: str) -> Symbol:
    normalized = value.upper()
    if normalized.endswith("USDT"):
        return Symbol(normalized[:-4], "USDT")
    raise ValueError(f"unsupported symbol: {value}")


def monthly_url(symbol: str, year: int, month: int) -> str:
    return (
        "https://data.binance.vision/data/futures/um/monthly/klines/"
        f"{symbol}/1m/{symbol}-1m-{year}-{month:02d}.zip"
    )


def months_between(start_at: datetime, end_at: datetime):
    cursor = datetime(start_at.year, start_at.month, 1, tzinfo=timezone.utc)
    end_month = datetime(end_at.year, end_at.month, 1, tzinfo=timezone.utc)
    while cursor <= end_month:
        yield cursor.year, cursor.month
        if cursor.month == 12:
            cursor = datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            cursor = datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)


if __name__ == "__main__":
    main()
