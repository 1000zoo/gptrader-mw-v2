from __future__ import annotations

import argparse
import html
import json
import sys
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backtest_combo_search import Combo, FixedRatioTakeProfitStopLossStrategy  # noqa: E402
from scripts.novel_train_test_combo_search import (  # noqa: E402
    QualityVolatilitySizingStrategy,
    TEST_END,
    TEST_START,
    TRAIN_END,
    TRAIN_START,
    _simulate_fast,
    load_or_fetch_market,
)
from src.application.usecases.research.dto import BacktestTrade  # noqa: E402
from src.domain.market import MarketSnapshot, Symbol, Timeframe  # noqa: E402
from src.domain.strategy import StrategySpec  # noqa: E402
from src.domain.strategy.implementations import VolatilityCompressionBreakoutStrategy  # noqa: E402


ADOPTED_COMBO_ID = "final-compression-s2-sl0.030-rr0.45-balanced"
TRADE_OUTPUT_PATH = Path(
    "docs/backtests/trades/final-compression-s2-sl0030-rr045-balanced-trades.jsonl"
)
CHART_OUTPUT_PATH = Path(
    "docs/backtests/charts/final-compression-s2-sl0030-rr045-balanced.html"
)
SYMBOL = Symbol("BTC", "USDT")
TIMEFRAME = Timeframe(1, "m")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades-path", type=Path, default=TRADE_OUTPUT_PATH)
    parser.add_argument("--chart-path", type=Path, default=CHART_OUTPUT_PATH)
    parser.add_argument("--fee-rate", type=Decimal, default=Decimal("0.0004"))
    args = parser.parse_args()

    market = load_or_fetch_market()
    combo = adopted_combo()
    train = replay_period(
        market,
        combo,
        split="train",
        start_at=TRAIN_START,
        end_at=TRAIN_END,
        fee_rate=args.fee_rate,
    )
    test = replay_period(
        market,
        combo,
        split="test",
        start_at=TEST_START,
        end_at=TEST_END,
        fee_rate=args.fee_rate,
    )

    write_trade_records(args.trades_path, [*train["trades"], *test["trades"]])
    write_chart(args.chart_path, combo=combo, periods=(train, test))
    print(
        json.dumps(
            {
                "combo_id": combo.combo_id,
                "trades_path": str(args.trades_path),
                "chart_path": str(args.chart_path),
                "train_trade_count": len(train["trades"]),
                "test_trade_count": len(test["trades"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def adopted_combo() -> Combo:
    strategy_params = {
        "lookback": 180,
        "compression_period": 45,
        "compression_ratio": Decimal("0.45"),
        "breakout_buffer": Decimal("0.0006"),
        "min_volume_ratio": Decimal("1.00"),
        "direction_filter_period": 1440,
        "min_filter_return": Decimal("0.002"),
    }
    tpsl_params = {
        "kind": "fixed",
        "stop_loss_ratio": Decimal("0.030"),
        "reward_risk_ratio": Decimal("0.45"),
    }
    sizing_params = {
        "kind": "quality-volatility",
        "min_equity_ratio": Decimal("0.02"),
        "max_equity_ratio": Decimal("0.14"),
        "min_leverage": Decimal("1"),
        "max_leverage": Decimal("8"),
    }
    return Combo(
        combo_id=ADOPTED_COMBO_ID,
        strategy_factory=VolatilityCompressionBreakoutStrategy,
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


def replay_period(
    market: MarketSnapshot,
    combo: Combo,
    *,
    split: str,
    start_at: datetime,
    end_at: datetime,
    fee_rate: Decimal,
) -> dict[str, object]:
    spec = StrategySpec(
        strategy_id=combo.combo_id,
        name=combo.combo_id,
        implementation="src.domain.strategy.implementations.VolatilityCompressionBreakoutStrategy",
        version="chart-replay",
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        lookback_candle_limit=1442,
        parameters=combo.strategy_params,
        metadata={"source": "adopted_strategy_chart"},
    )
    simulation = _simulate_fast(
        market=market,
        spec=spec,
        combo=combo,
        start_at=start_at,
        end_at=end_at,
        fee_rate=fee_rate,
    )
    candles = [
        candle
        for candle in market.candles
        if start_at <= candle.opened_at < end_at
    ]
    trade_records = [
        {**trade_record(index, trade), "split": split}
        for index, trade in enumerate(simulation["trades"], start=1)
    ]
    return {
        "split": split,
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "performance": performance_record(simulation["performance"]),
        "candles": candle_samples(candles),
        "trades": trade_records,
        "equity": equity_curve(trade_records),
    }


def trade_record(trade_no: int, trade: BacktestTrade) -> dict[str, object]:
    notional = trade.entry_price * trade.quantity
    return_ratio = trade.net_pnl / notional if notional > Decimal("0") else Decimal("0")
    return {
        "trade_no": trade_no,
        "direction": trade.direction.name,
        "entry_time": _iso(trade.entry_time),
        "exit_time": _iso(trade.exit_time),
        "entry_price": str(trade.entry_price),
        "exit_price": str(trade.exit_price),
        "quantity": str(trade.quantity),
        "gross_pnl": str(trade.gross_pnl),
        "fee_paid": str(trade.fee_paid),
        "net_pnl": str(trade.net_pnl),
        "return_ratio": str(return_ratio),
        "exit_reason": trade.exit_reason,
    }


def performance_record(performance) -> dict[str, object]:
    return {
        "initial_equity": str(performance.initial_equity),
        "final_equity": str(performance.final_equity),
        "net_pnl": str(performance.net_pnl),
        "return_ratio": str(performance.return_ratio),
        "max_drawdown_ratio": str(performance.max_drawdown_ratio),
        "trade_count": performance.trade_count,
        "winning_trade_count": performance.winning_trade_count,
        "losing_trade_count": performance.losing_trade_count,
        "win_rate": str(performance.win_rate),
    }


def candle_samples(candles: Sequence[object], *, max_points: int = 1800) -> list[dict[str, object]]:
    if not candles:
        return []
    stride = max(1, len(candles) // max_points)
    selected = list(candles[::stride])
    if selected[-1] is not candles[-1]:
        selected.append(candles[-1])
    return [
        {
            "time": candle.opened_at.isoformat(),
            "open": str(candle.open_price),
            "high": str(candle.high_price),
            "low": str(candle.low_price),
            "close": str(candle.close_price),
        }
        for candle in selected
    ]


def equity_curve(trades: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    equity = Decimal("10000")
    points = [{"time": None, "equity": str(equity)}]
    for trade in trades:
        equity += Decimal(str(trade["net_pnl"]))
        points.append({"time": trade["exit_time"], "equity": str(equity)})
    return points


def write_trade_records(path: Path, records: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_chart(
    path: Path,
    *,
    combo: Combo,
    periods: Sequence[Mapping[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "combo_id": combo.combo_id,
        "strategy_params": stringify(combo.strategy_params),
        "tpsl_params": stringify(combo.tpsl_params),
        "position_sizing_params": stringify(combo.position_sizing_params),
        "periods": periods,
    }
    path.write_text(render_html(payload), encoding="utf-8")


def render_html(payload: Mapping[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    title = html.escape(str(payload["combo_id"]))
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} backtest chart</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #17202a; background: #f6f7f9; }}
    header {{ padding: 18px 22px; background: #101820; color: white; }}
    h1 {{ margin: 0; font-size: 20px; letter-spacing: 0; }}
    main {{ padding: 18px 22px 32px; }}
    .tabs {{ display: flex; gap: 8px; margin-bottom: 14px; }}
    button {{ border: 1px solid #b8c1cc; background: white; padding: 7px 12px; cursor: pointer; }}
    button.active {{ background: #1f6feb; color: white; border-color: #1f6feb; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; }}
    .metric {{ background: white; border: 1px solid #d7dde5; padding: 10px; border-radius: 6px; }}
    .metric b {{ display: block; font-size: 12px; color: #5d6b7a; margin-bottom: 4px; }}
    .chart {{ background: white; border: 1px solid #d7dde5; border-radius: 6px; padding: 10px; margin-bottom: 14px; }}
    svg {{ width: 100%; height: 360px; display: block; }}
    table {{ width: 100%; border-collapse: collapse; background: white; border: 1px solid #d7dde5; font-size: 12px; }}
    th, td {{ padding: 7px 8px; border-bottom: 1px solid #e7ebf0; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2), th:nth-child(3), td:nth-child(3) {{ text-align: left; }}
    tr.win td {{ color: #116329; }}
    tr.loss td {{ color: #9a3412; }}
    .params {{ font-size: 12px; color: #405060; margin: 8px 0 16px; }}
  </style>
</head>
<body>
<header><h1>{title}</h1></header>
<main>
  <div class="params" id="params"></div>
  <div class="tabs" id="tabs"></div>
  <section class="summary" id="summary"></section>
  <section class="chart"><svg id="priceChart" viewBox="0 0 1200 360" preserveAspectRatio="none"></svg></section>
  <section class="chart"><svg id="equityChart" viewBox="0 0 1200 260" preserveAspectRatio="none"></svg></section>
  <table id="trades"></table>
</main>
<script>
const payload = {data};
let active = payload.periods[1] ? 1 : 0;

function num(value) {{ return Number(value); }}
function pct(value) {{ return (num(value) * 100).toFixed(2) + "%"; }}
function money(value) {{ return num(value).toFixed(2); }}
function xScale(index, length, width) {{ return length <= 1 ? 0 : index / (length - 1) * width; }}
function yScale(value, min, max, height, pad) {{
  if (max === min) return height / 2;
  return pad + (max - value) / (max - min) * (height - pad * 2);
}}
function setLine(svg, points, color, width=2) {{
  const p = points.map(([x,y]) => `${{x.toFixed(2)}},${{y.toFixed(2)}}`).join(" ");
  svg.insertAdjacentHTML("beforeend", `<polyline points="${{p}}" fill="none" stroke="${{color}}" stroke-width="${{width}}" vector-effect="non-scaling-stroke"/>`);
}}
function render() {{
  const period = payload.periods[active];
  document.getElementById("params").textContent = JSON.stringify({{
    strategy: payload.strategy_params,
    tpsl: payload.tpsl_params,
    sizing: payload.position_sizing_params
  }});
  document.getElementById("tabs").innerHTML = payload.periods.map((p, i) =>
    `<button class="${{i === active ? "active" : ""}}" onclick="active=${{i}};render()">${{p.split}}</button>`
  ).join("");
  const perf = period.performance;
  document.getElementById("summary").innerHTML = [
    ["period", `${{period.start_at}} ~ ${{period.end_at}}`],
    ["trades", perf.trade_count],
    ["win rate", pct(perf.win_rate)],
    ["return", pct(perf.return_ratio)],
    ["max drawdown", pct(perf.max_drawdown_ratio)],
    ["net pnl", money(perf.net_pnl)]
  ].map(([k,v]) => `<div class="metric"><b>${{k}}</b>${{v}}</div>`).join("");
  renderPrice(period);
  renderEquity(period);
  renderTrades(period.trades);
}}
function renderPrice(period) {{
  const svg = document.getElementById("priceChart");
  svg.innerHTML = "";
  const width = 1200, height = 360, pad = 22;
  const candles = period.candles;
  const closes = candles.map(c => num(c.close));
  const min = Math.min(...candles.map(c => num(c.low)));
  const max = Math.max(...candles.map(c => num(c.high)));
  setLine(svg, candles.map((c,i) => [xScale(i, candles.length, width), yScale(num(c.close), min, max, height, pad)]), "#1f6feb", 2);
  const start = new Date(period.start_at).getTime();
  const end = new Date(period.end_at).getTime();
  function timeX(t) {{ return (new Date(t).getTime() - start) / (end - start) * width; }}
  for (const trade of period.trades) {{
    const entryX = timeX(trade.entry_time);
    const exitX = timeX(trade.exit_time);
    const entryY = yScale(num(trade.entry_price), min, max, height, pad);
    const exitY = yScale(num(trade.exit_price), min, max, height, pad);
    const win = num(trade.net_pnl) >= 0;
    const color = win ? "#188038" : "#d93025";
    svg.insertAdjacentHTML("beforeend", `<line x1="${{entryX}}" y1="${{entryY}}" x2="${{exitX}}" y2="${{exitY}}" stroke="${{color}}" stroke-width="1.5" vector-effect="non-scaling-stroke" opacity="0.75"/>`);
    svg.insertAdjacentHTML("beforeend", `<circle cx="${{entryX}}" cy="${{entryY}}" r="4" fill="${{trade.direction === "LONG" ? "#188038" : "#d93025"}}"/>`);
    svg.insertAdjacentHTML("beforeend", `<rect x="${{exitX-3}}" y="${{exitY-3}}" width="6" height="6" fill="${{color}}"/>`);
  }}
}}
function renderEquity(period) {{
  const svg = document.getElementById("equityChart");
  svg.innerHTML = "";
  const width = 1200, height = 260, pad = 20;
  const values = period.equity.map(p => num(p.equity));
  const min = Math.min(...values), max = Math.max(...values);
  setLine(svg, period.equity.map((p,i) => [xScale(i, period.equity.length, width), yScale(num(p.equity), min, max, height, pad)]), "#6f42c1", 2);
}}
function renderTrades(trades) {{
  document.getElementById("trades").innerHTML = `<thead><tr>
    <th>#</th><th>Side</th><th>Reason</th><th>Entry</th><th>Exit</th><th>Entry Px</th><th>Exit Px</th><th>Net PnL</th><th>ROE</th>
  </tr></thead><tbody>` + trades.map(t => `<tr class="${{num(t.net_pnl) >= 0 ? "win" : "loss"}}">
    <td>${{t.trade_no}}</td><td>${{t.direction}}</td><td>${{t.exit_reason}}</td><td>${{t.entry_time}}</td><td>${{t.exit_time}}</td>
    <td>${{money(t.entry_price)}}</td><td>${{money(t.exit_price)}}</td><td>${{money(t.net_pnl)}}</td><td>${{pct(t.return_ratio)}}</td>
  </tr>`).join("") + `</tbody>`;
}}
render();
</script>
</body>
</html>
"""


def stringify(values: Mapping[str, object]) -> dict[str, object]:
    return {key: str(value) for key, value in values.items()}


def _iso(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


if __name__ == "__main__":
    main()
