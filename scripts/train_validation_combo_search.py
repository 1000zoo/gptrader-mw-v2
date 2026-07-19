from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_range_combo_search import RangeEdgeReversionStrategy  # noqa: E402
from scripts.backtest_combo_search import (  # noqa: E402
    Combo,
    FixedRatioTakeProfitStopLossStrategy,
    load_or_fetch_market,
    run_combo_for_period,
)
from src.domain.risk import (  # noqa: E402
    ConfidencePositionSizingStrategy,
    FixedPositionSizingStrategy,
)
from src.observability.logging import configure_runtime_logging  # noqa: E402


RESULTS_PATH = Path("docs/backtests/train-validation-combo-search.jsonl")
DEFAULT_TRAIN_START = datetime(2026, 1, 9, 0, 0, tzinfo=timezone.utc)
DEFAULT_TRAIN_END = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)
DEFAULT_VALIDATION_START = datetime(2026, 5, 9, 0, 0, tzinfo=timezone.utc)
DEFAULT_VALIDATION_END = datetime(2026, 7, 9, 0, 0, tzinfo=timezone.utc)

SEED_STRATEGY_PARAMS = {
    "range_period": 300,
    "lower_band": Decimal("0.06"),
    "upper_band": Decimal("0.94"),
    "min_range_width": Decimal("0.010"),
    "reclaim_return": Decimal("0.0007"),
}
SEED_TPSL_PARAMS = {
    "kind": "fixed",
    "stop_loss_ratio": Decimal("0.09"),
    "reward_risk_ratio": Decimal("0.15"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-path", type=Path, default=RESULTS_PATH)
    parser.add_argument("--grid", choices=("seed", "strategy", "tpsl", "sizing", "all"), default="all")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--train-select-limit", type=int, default=10)
    parser.add_argument("--train-start", type=parse_datetime, default=DEFAULT_TRAIN_START)
    parser.add_argument("--train-end", type=parse_datetime, default=DEFAULT_TRAIN_END)
    parser.add_argument("--validation-start", type=parse_datetime, default=DEFAULT_VALIDATION_START)
    parser.add_argument("--validation-end", type=parse_datetime, default=DEFAULT_VALIDATION_END)
    parser.add_argument("--risk-warning-drawdown", type=Decimal, default=Decimal("0.30"))
    args = parser.parse_args()

    configure_runtime_logging(level="ERROR")
    market = load_or_fetch_market()
    args.results_path.parent.mkdir(parents=True, exist_ok=True)
    seen = load_seen_combo_ids_from(args.results_path)

    candidates = [
        combo for combo in build_train_validation_combos(args.grid)
        if combo.combo_id not in seen
    ]
    candidates = unique_combos(candidates)
    if args.limit > 0:
        candidates = candidates[: args.limit]

    train_results = []
    for combo in candidates:
        train_result = run_combo_for_period(
            market,
            combo,
            start_at=args.train_start,
            end_at=args.train_end,
            cycle_id="train-validation-combo-search:train",
            metadata={"combo_id": combo.combo_id, "split": "train"},
        )
        train_results.append(train_result)
        print("TRAIN " + json.dumps(train_result, ensure_ascii=False, sort_keys=True), flush=True)

    selected = select_train_candidates(train_results, limit=args.train_select_limit)
    combo_by_id = {combo.combo_id: combo for combo in candidates}
    final_results = []
    for train_result in selected:
        combo = combo_by_id[str(train_result["combo_id"])]
        validation_result = run_combo_for_period(
            market,
            combo,
            start_at=args.validation_start,
            end_at=args.validation_end,
            cycle_id="train-validation-combo-search:validation",
            metadata={"combo_id": combo.combo_id, "split": "validation"},
        )
        combined = combine_train_validation_result(
            train_result=train_result,
            validation_result=validation_result,
            train_period=(args.train_start.isoformat(), args.train_end.isoformat()),
            validation_period=(
                args.validation_start.isoformat(),
                args.validation_end.isoformat(),
            ),
            risk_warning_drawdown=args.risk_warning_drawdown,
        )
        append_result_to(args.results_path, combined)
        final_results.append(combined)
        print("VALIDATION " + json.dumps(combined, ensure_ascii=False, sort_keys=True), flush=True)

    best = rank_validation_results(final_results)[:10]
    print("TOP_VALIDATION " + json.dumps(best, ensure_ascii=False, sort_keys=True), flush=True)


def build_seed_train_validation_combos() -> list[Combo]:
    return build_combos(
        "tv-range-seed",
        strategy_grid=[SEED_STRATEGY_PARAMS],
        tpsl_grid=[SEED_TPSL_PARAMS],
        sizing_grid=seed_position_sizing_grid(),
    )


def build_train_validation_combos(grid: str) -> list[Combo]:
    combos = build_seed_train_validation_combos() if grid in {"seed", "all"} else []
    if grid in {"strategy", "all"}:
        combos.extend(
            build_combos(
                "tv-range-strategy",
                strategy_grid=nearby_strategy_grid(),
                tpsl_grid=[SEED_TPSL_PARAMS],
                sizing_grid=seed_position_sizing_grid(),
            )
        )
    if grid in {"tpsl", "all"}:
        combos.extend(
            build_combos(
                "tv-range-tpsl",
                strategy_grid=[SEED_STRATEGY_PARAMS],
                tpsl_grid=nearby_tpsl_grid(),
                sizing_grid=seed_position_sizing_grid(),
            )
        )
    if grid in {"sizing", "all"}:
        combos.extend(
            build_combos(
                "tv-range-sizing",
                strategy_grid=[SEED_STRATEGY_PARAMS],
                tpsl_grid=[SEED_TPSL_PARAMS],
                sizing_grid=expanded_position_sizing_grid(),
            )
        )
    return unique_combos(combos)


def build_combos(
    prefix: str,
    *,
    strategy_grid: Iterable[Mapping[str, object]],
    tpsl_grid: Iterable[Mapping[str, object]],
    sizing_grid: Iterable[Mapping[str, object]],
) -> list[Combo]:
    combos: list[Combo] = []
    for strategy_index, strategy_params in enumerate(strategy_grid, start=1):
        for tpsl_index, tpsl_params in enumerate(tpsl_grid, start=1):
            for sizing_index, sizing_params in enumerate(sizing_grid, start=1):
                combo_id = (
                    f"{prefix}-s{strategy_index}-t{tpsl_index}"
                    f"-p{sizing_index}-{sizing_params['kind']}"
                )
                combos.append(
                    Combo(
                        combo_id=combo_id,
                        strategy_factory=RangeEdgeReversionStrategy,
                        strategy_params=dict(strategy_params),
                        tpsl_factory=lambda params=tpsl_params: FixedRatioTakeProfitStopLossStrategy(
                            stop_loss_ratio=params["stop_loss_ratio"],
                            reward_risk_ratio=params["reward_risk_ratio"],
                        ),
                        tpsl_params=dict(tpsl_params),
                        position_sizing_factory=lambda params=sizing_params: make_position_sizing(params),
                        position_sizing_params=dict(sizing_params),
                    )
                )
    return combos


def seed_position_sizing_grid() -> list[dict[str, object]]:
    return [
        {
            "kind": "confidence",
            "min_equity_ratio": Decimal("0.0025"),
            "max_equity_ratio": Decimal("0.10"),
            "min_leverage": Decimal("1"),
            "max_leverage": Decimal("15"),
        },
        {"kind": "fixed", "equity_ratio": Decimal("0.10"), "leverage": Decimal("15")},
        {"kind": "fixed", "equity_ratio": Decimal("0.15"), "leverage": Decimal("10")},
        {"kind": "fixed", "equity_ratio": Decimal("0.30"), "leverage": Decimal("5")},
        {"kind": "fixed", "equity_ratio": Decimal("0.50"), "leverage": Decimal("3")},
    ]


def expanded_position_sizing_grid() -> list[dict[str, object]]:
    return unique_param_dicts(
        [
            {"kind": "fixed", "equity_ratio": Decimal("0.05"), "leverage": Decimal("15")},
            {"kind": "fixed", "equity_ratio": Decimal("0.20"), "leverage": Decimal("8")},
            {"kind": "fixed", "equity_ratio": Decimal("0.25"), "leverage": Decimal("6")},
            {
                "kind": "confidence",
                "min_equity_ratio": Decimal("0.0010"),
                "max_equity_ratio": Decimal("0.08"),
                "min_leverage": Decimal("1"),
                "max_leverage": Decimal("12"),
            },
            {
                "kind": "confidence",
                "min_equity_ratio": Decimal("0.0050"),
                "max_equity_ratio": Decimal("0.12"),
                "min_leverage": Decimal("1"),
                "max_leverage": Decimal("15"),
            },
            *seed_position_sizing_grid(),
        ]
    )


def nearby_strategy_grid() -> list[dict[str, object]]:
    return unique_param_dicts(
        [
            {**SEED_STRATEGY_PARAMS, "range_period": 240},
            {**SEED_STRATEGY_PARAMS, "range_period": 270},
            {**SEED_STRATEGY_PARAMS, "range_period": 330},
            {**SEED_STRATEGY_PARAMS, "range_period": 360},
            {**SEED_STRATEGY_PARAMS, "lower_band": Decimal("0.055"), "upper_band": Decimal("0.945")},
            {**SEED_STRATEGY_PARAMS, "lower_band": Decimal("0.065"), "upper_band": Decimal("0.935")},
            {**SEED_STRATEGY_PARAMS, "min_range_width": Decimal("0.008")},
            {**SEED_STRATEGY_PARAMS, "min_range_width": Decimal("0.012")},
            {**SEED_STRATEGY_PARAMS, "reclaim_return": Decimal("0.0005")},
            {**SEED_STRATEGY_PARAMS, "reclaim_return": Decimal("0.0009")},
            SEED_STRATEGY_PARAMS,
        ]
    )


def nearby_tpsl_grid() -> list[dict[str, object]]:
    values = []
    for stop_loss_ratio in (
        Decimal("0.075"),
        Decimal("0.08"),
        Decimal("0.085"),
        Decimal("0.09"),
        Decimal("0.095"),
        Decimal("0.10"),
        Decimal("0.105"),
    ):
        for reward_risk_ratio in (
            Decimal("0.12"),
            Decimal("0.13"),
            Decimal("0.14"),
            Decimal("0.15"),
            Decimal("0.16"),
            Decimal("0.18"),
            Decimal("0.20"),
        ):
            values.append(
                {
                    "kind": "fixed",
                    "stop_loss_ratio": stop_loss_ratio,
                    "reward_risk_ratio": reward_risk_ratio,
                }
            )
    return unique_param_dicts([*values, SEED_TPSL_PARAMS])


def make_position_sizing(params: Mapping[str, object]):
    if params["kind"] == "confidence":
        return ConfidencePositionSizingStrategy(
            min_equity_ratio=params["min_equity_ratio"],
            max_equity_ratio=params["max_equity_ratio"],
            min_leverage=params["min_leverage"],
            max_leverage=params["max_leverage"],
        )
    if params["kind"] == "fixed":
        return FixedPositionSizingStrategy(
            equity_ratio=params["equity_ratio"],
            leverage=params["leverage"],
        )
    raise ValueError(f"unknown position sizing kind: {params['kind']}")


def select_train_candidates(
    train_results: Sequence[Mapping[str, object]],
    *,
    limit: int,
) -> list[Mapping[str, object]]:
    passed = [result for result in train_results if result.get("succeeded")]
    ranked = sorted(
        passed,
        key=lambda result: (
            Decimal(str(result["return_ratio"])),
            Decimal(str(result["win_rate"])),
            Decimal(str(result["average_trade_return"])),
            int(result["trade_count"]),
        ),
        reverse=True,
    )
    return ranked[:limit]


def combine_train_validation_result(
    *,
    train_result: Mapping[str, object],
    validation_result: Mapping[str, object],
    train_period: tuple[str, str],
    validation_period: tuple[str, str],
    risk_warning_drawdown: Decimal,
) -> dict[str, object]:
    combo_id = str(train_result["combo_id"])
    validation_drawdown = Decimal(str(validation_result["max_drawdown_ratio"]))
    return {
        "combo_id": combo_id,
        "train_period": {"start_at": train_period[0], "end_at": train_period[1]},
        "validation_period": {
            "start_at": validation_period[0],
            "end_at": validation_period[1],
        },
        "succeeded": bool(train_result.get("succeeded")) and bool(validation_result.get("succeeded")),
        "risk_warning": "high_drawdown" if validation_drawdown >= risk_warning_drawdown else None,
        "strategy_params": train_result.get("strategy_params", {}),
        "tpsl_params": train_result.get("tpsl_params", {}),
        "position_sizing_params": train_result.get("position_sizing_params", {}),
        **prefixed_metrics("train", train_result),
        **prefixed_metrics("validation", validation_result),
        "overfit_gap_return_ratio": decimal_text(
            Decimal(str(train_result["return_ratio"]))
            - Decimal(str(validation_result["return_ratio"]))
        ),
        "overfit_gap_win_rate": decimal_text(
            Decimal(str(train_result["win_rate"]))
            - Decimal(str(validation_result["win_rate"]))
        ),
        "overfit_gap_average_trade_return": decimal_text(
            Decimal(str(train_result["average_trade_return"]))
            - Decimal(str(validation_result["average_trade_return"]))
        ),
    }


def prefixed_metrics(prefix: str, result: Mapping[str, object]) -> dict[str, object]:
    return {
        f"{prefix}_trade_count": int(result["trade_count"]),
        f"{prefix}_win_rate": str(result["win_rate"]),
        f"{prefix}_average_trade_return": str(result["average_trade_return"]),
        f"{prefix}_return_ratio": str(result["return_ratio"]),
        f"{prefix}_net_pnl": str(result["net_pnl"]),
        f"{prefix}_max_drawdown_ratio": str(result["max_drawdown_ratio"]),
    }


def rank_validation_results(
    results: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    return sorted(
        results,
        key=lambda result: (
            Decimal(str(result["validation_return_ratio"])),
            Decimal(str(result["validation_win_rate"])),
            Decimal(str(result.get("validation_average_trade_return", "0"))),
            int(result["validation_trade_count"]),
        ),
        reverse=True,
    )


def load_seen_combo_ids_from(path: Path = RESULTS_PATH) -> set[str]:
    if not path.exists():
        return set()
    return {
        str(json.loads(line)["combo_id"])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def append_result_to(path: Path, result: Mapping[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")


def unique_combos(combos: Iterable[Combo]) -> list[Combo]:
    seen: set[str] = set()
    unique = []
    for combo in combos:
        if combo.combo_id in seen:
            continue
        seen.add(combo.combo_id)
        unique.append(combo)
    return unique


def unique_param_dicts(values: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[tuple[str, str], ...]] = set()
    unique = []
    for value in values:
        key = tuple(sorted((str(item_key), str(item_value)) for item_key, item_value in value.items()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(dict(value))
    return unique


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def decimal_text(value: Decimal) -> str:
    return str(value)


if __name__ == "__main__":
    main()
