from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.agent_range_combo_search import RangeEdgeReversionStrategy  # noqa: E402
from scripts.backtest_combo_search import (  # noqa: E402
    CACHE_PATH,
    Combo,
    FixedRatioTakeProfitStopLossStrategy,
    load_or_fetch_market,
    run_combo,
)
from src.domain.risk import FixedPositionSizingStrategy  # noqa: E402
from src.observability.logging import configure_runtime_logging  # noqa: E402


RESULTS_PATH = Path("docs/backtests/position-sizing-combo-search.jsonl")
BASE_COMBO_ID = "agent-range-wide4-s1-t1-fixed"
STRATEGY_PARAMS = {
    "range_period": 300,
    "lower_band": Decimal("0.06"),
    "upper_band": Decimal("0.94"),
    "min_range_width": Decimal("0.010"),
    "reclaim_return": Decimal("0.0007"),
}
TPSL_PARAMS = {
    "kind": "fixed",
    "stop_loss_ratio": Decimal("0.09"),
    "reward_risk_ratio": Decimal("0.15"),
}
DEFAULT_EQUITY_RATIOS = (
    Decimal("0.02"),
    Decimal("0.05"),
    Decimal("0.10"),
    Decimal("0.15"),
    Decimal("0.20"),
    Decimal("0.25"),
    Decimal("0.30"),
    Decimal("0.35"),
    Decimal("0.40"),
    Decimal("0.45"),
    Decimal("0.50"),
)
DEFAULT_LEVERAGES = tuple(Decimal(value) for value in range(1, 16))
_WORKER_MARKET = None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    args = parser.parse_args()

    configure_runtime_logging(level="ERROR")
    if not CACHE_PATH.exists():
        raise FileNotFoundError(f"required cache file is missing: {CACHE_PATH}")

    market = load_or_fetch_market()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen = load_seen_combo_ids_from(RESULTS_PATH)
    candidates = [
        combo for combo in build_position_sizing_combos() if combo.combo_id not in seen
    ]
    if args.limit > 0:
        candidates = candidates[: args.limit]

    best: dict[str, object] | None = None
    if args.workers <= 1:
        for combo in candidates:
            result = run_combo(market, combo)
            best = _record_result(result, best)
    else:
        with ProcessPoolExecutor(
            max_workers=args.workers,
            initializer=_init_worker,
        ) as executor:
            futures = [
                executor.submit(
                    _run_combo_for_sizing,
                    str(combo.position_sizing_params["equity_ratio"]),
                    str(combo.position_sizing_params["leverage"]),
                )
                for combo in candidates
            ]
            for future in as_completed(futures):
                result = future.result()
                best = _record_result(result, best)

    if best is not None:
        print("BEST " + json.dumps(best, ensure_ascii=False, sort_keys=True))


def build_position_sizing_combos(
    *,
    equity_ratios: Iterable[Decimal] = DEFAULT_EQUITY_RATIOS,
    leverages: Iterable[Decimal] = DEFAULT_LEVERAGES,
) -> list[Combo]:
    combos: list[Combo] = []
    for equity_ratio in equity_ratios:
        for leverage in leverages:
            combo_id = (
                f"position-sizing-{BASE_COMBO_ID}"
                f"-er{_ratio_id(equity_ratio)}"
                f"-l{int(leverage):02d}"
            )
            sizing_params = {
                "kind": "fixed",
                "equity_ratio": equity_ratio,
                "leverage": leverage,
            }
            combos.append(
                Combo(
                    combo_id=combo_id,
                    strategy_factory=RangeEdgeReversionStrategy,
                    strategy_params=STRATEGY_PARAMS,
                    tpsl_factory=lambda: FixedRatioTakeProfitStopLossStrategy(
                        stop_loss_ratio=Decimal("0.09"),
                        reward_risk_ratio=Decimal("0.15"),
                    ),
                    tpsl_params=TPSL_PARAMS,
                    position_sizing_factory=lambda sizing_params=sizing_params: FixedPositionSizingStrategy(
                        equity_ratio=sizing_params["equity_ratio"],
                        leverage=sizing_params["leverage"],
                    ),
                    position_sizing_params=sizing_params,
                )
            )
    return combos


def _init_worker() -> None:
    configure_runtime_logging(level="ERROR")
    global _WORKER_MARKET
    _WORKER_MARKET = load_or_fetch_market()


def _run_combo_for_sizing(equity_ratio_text: str, leverage_text: str) -> dict[str, object]:
    if _WORKER_MARKET is None:
        _init_worker()
    combo = build_position_sizing_combos(
        equity_ratios=(Decimal(equity_ratio_text),),
        leverages=(Decimal(leverage_text),),
    )[0]
    return run_combo(_WORKER_MARKET, combo)


def _record_result(
    result: dict[str, object],
    best: dict[str, object] | None,
) -> dict[str, object]:
    append_result_to(RESULTS_PATH, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    if best is None or _score(result) > _score(best):
        return result
    return best


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


def _score(result: Mapping[str, object]) -> tuple[Decimal, Decimal]:
    return Decimal(str(result["net_pnl"])), Decimal(str(result["return_ratio"]))


def _ratio_id(value: Decimal) -> str:
    return f"{int(value * Decimal('100')):03d}"


if __name__ == "__main__":
    main()
