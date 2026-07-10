from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


RESULTS_PATH = Path("docs/backtests/scalping-train-test-combo-search.jsonl")
VALIDATION_PATH = Path("docs/backtests/scalping-train-selection-validation.json")
SELECTED_COMBO_PATH = Path("docs/backtests/scalping-selected-combo.json")


def train_candidate_score(result: Mapping[str, object]) -> tuple[Decimal, ...]:
    return (
        Decimal(str(result["train_return_ratio"])),
        Decimal(str(result["train_average_gross_trade_roe"])),
        Decimal(str(result["train_gross_win_rate"])),
        Decimal(str(result["train_trades_per_day"])),
        -Decimal(str(result["train_max_drawdown_ratio"])),
    )


def select_train_candidates(
    results: Sequence[Mapping[str, object]],
    *,
    min_train_trades_per_day: Decimal = Decimal("10"),
    min_train_gross_win_rate: Decimal = Decimal("0.60"),
    min_train_average_gross_trade_roe: Decimal = Decimal("0.003"),
    min_train_return_ratio: Decimal = Decimal("0"),
    limit: int = 20,
) -> list[Mapping[str, object]]:
    filtered = [
        result
        for result in results
        if Decimal(str(result["train_trades_per_day"])) >= min_train_trades_per_day
        and Decimal(str(result["train_gross_win_rate"])) >= min_train_gross_win_rate
        and Decimal(str(result["train_average_gross_trade_roe"]))
        >= min_train_average_gross_trade_roe
        and Decimal(str(result["train_return_ratio"])) > min_train_return_ratio
    ]
    return sorted(filtered, key=train_candidate_score, reverse=True)[:limit]


def main() -> None:
    results = _read_jsonl(RESULTS_PATH)
    selected = select_train_candidates(results)
    top = selected[0] if selected else None
    validation = {
        "method": "train-only candidate selection; test metrics reported after selection",
        "source_results": str(RESULTS_PATH),
        "thresholds": {
            "min_train_trades_per_day": "10",
            "min_train_gross_win_rate": "0.60",
            "min_train_average_gross_trade_roe": "0.003",
            "min_train_return_ratio": "0",
        },
        "candidate_count": len(results),
        "selected_count": len(selected),
        "selected_by_train": selected,
        "top_selected_combo_id": None if top is None else top["combo_id"],
        "top_selected_test_result": None if top is None else _test_summary(top),
    }
    VALIDATION_PATH.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if top is not None:
        SELECTED_COMBO_PATH.write_text(
            json.dumps(
                {
                    "combo_id": top["combo_id"],
                    "selection_method": validation["method"],
                    "strategy_params": top["strategy_params"],
                    "tpsl_params": top["tpsl_params"],
                    "position_sizing_params": top["position_sizing_params"],
                    "train_summary": _train_summary(top),
                    "test_summary_after_train_selection": _test_summary(top),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    print(json.dumps(validation["top_selected_test_result"], ensure_ascii=False))


def _read_jsonl(path: Path) -> list[Mapping[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _train_summary(result: Mapping[str, object]) -> dict[str, object]:
    return {
        "return_ratio": result["train_return_ratio"],
        "trades_per_day": result["train_trades_per_day"],
        "gross_win_rate": result["train_gross_win_rate"],
        "average_gross_trade_roe": result["train_average_gross_trade_roe"],
        "max_drawdown_ratio": result["train_max_drawdown_ratio"],
    }


def _test_summary(result: Mapping[str, object]) -> dict[str, object]:
    return {
        "return_ratio": result["test_return_ratio"],
        "trades_per_day": result["test_trades_per_day"],
        "gross_win_rate": result["test_gross_win_rate"],
        "average_gross_trade_roe": result["test_average_gross_trade_roe"],
        "max_drawdown_ratio": result["test_max_drawdown_ratio"],
    }


if __name__ == "__main__":
    main()
