import json
from decimal import Decimal

from scripts.train_validation_combo_search import (
    build_seed_train_validation_combos,
    build_train_validation_combos,
    combine_train_validation_result,
    load_seen_combo_ids_from,
    rank_validation_results,
    select_train_candidates,
)


def _result(combo_id: str, *, return_ratio: str, win_rate: str = "0.5") -> dict:
    return {
        "combo_id": combo_id,
        "succeeded": True,
        "trade_count": 10,
        "win_rate": win_rate,
        "average_trade_return": "0.01",
        "return_ratio": return_ratio,
        "net_pnl": "100",
        "max_drawdown_ratio": "0.1",
    }


def test_seed_grid_includes_requested_confidence_and_fixed_position_sizing() -> None:
    combos = build_seed_train_validation_combos()

    sizing_params = [combo.position_sizing_params for combo in combos]

    assert {
        "kind": "confidence",
        "min_equity_ratio": Decimal("0.0025"),
        "max_equity_ratio": Decimal("0.10"),
        "min_leverage": Decimal("1"),
        "max_leverage": Decimal("15"),
    } in sizing_params
    assert {
        "kind": "fixed",
        "equity_ratio": Decimal("0.10"),
        "leverage": Decimal("15"),
    } in sizing_params
    assert {
        "kind": "fixed",
        "equity_ratio": Decimal("0.50"),
        "leverage": Decimal("3"),
    } in sizing_params
    assert all(combo.strategy_params["range_period"] == 300 for combo in combos)
    assert all(combo.tpsl_params["stop_loss_ratio"] == Decimal("0.09") for combo in combos)


def test_seen_combo_ids_are_loaded_from_train_validation_jsonl(tmp_path) -> None:
    path = tmp_path / "train-validation.jsonl"
    path.write_text(
        json.dumps({"combo_id": "tv-range-seed-confidence"}) + "\n",
        encoding="utf-8",
    )

    assert load_seen_combo_ids_from(path) == {"tv-range-seed-confidence"}


def test_specific_expansion_grids_do_not_start_with_seed_combos() -> None:
    strategy_combo = build_train_validation_combos("strategy")[0]
    tpsl_combo = build_train_validation_combos("tpsl")[0]
    sizing_combo = build_train_validation_combos("sizing")[0]

    assert strategy_combo.combo_id.startswith("tv-range-strategy-")
    assert tpsl_combo.combo_id.startswith("tv-range-tpsl-")
    assert sizing_combo.combo_id.startswith("tv-range-sizing-")
    assert strategy_combo.strategy_params["range_period"] != 300
    assert tpsl_combo.tpsl_params["stop_loss_ratio"] != Decimal("0.09")
    assert sizing_combo.position_sizing_params != build_seed_train_validation_combos()[
        0
    ].position_sizing_params


def test_select_train_candidates_sorts_by_return_ratio_and_limits() -> None:
    results = [
        _result("weak", return_ratio="0.01"),
        _result("best", return_ratio="0.03"),
        _result("middle", return_ratio="0.02"),
    ]

    selected = select_train_candidates(results, limit=2)

    assert [result["combo_id"] for result in selected] == ["best", "middle"]


def test_combine_train_validation_result_adds_gap_metrics_and_risk_warning() -> None:
    train = _result("combo-a", return_ratio="0.30", win_rate="0.70")
    train["average_trade_return"] = "0.03"
    validation = _result("combo-a", return_ratio="0.10", win_rate="0.55")
    validation["average_trade_return"] = "0.01"
    validation["max_drawdown_ratio"] = "0.35"

    combined = combine_train_validation_result(
        train_result=train,
        validation_result=validation,
        train_period=("2026-01-09T00:00:00+00:00", "2026-05-09T00:00:00+00:00"),
        validation_period=("2026-05-09T00:00:00+00:00", "2026-07-09T00:00:00+00:00"),
        risk_warning_drawdown=Decimal("0.30"),
    )

    assert combined["train_return_ratio"] == "0.30"
    assert combined["validation_return_ratio"] == "0.10"
    assert combined["overfit_gap_return_ratio"] == "0.20"
    assert combined["overfit_gap_win_rate"] == "0.15"
    assert combined["overfit_gap_average_trade_return"] == "0.02"
    assert combined["risk_warning"] == "high_drawdown"


def test_rank_validation_results_uses_validation_metrics_first() -> None:
    results = [
        {"combo_id": "train-star", "validation_return_ratio": "0.01", "validation_win_rate": "0.90", "validation_trade_count": 50},
        {"combo_id": "validation-star", "validation_return_ratio": "0.02", "validation_win_rate": "0.60", "validation_trade_count": 20},
    ]

    ranked = rank_validation_results(results)

    assert [result["combo_id"] for result in ranked] == ["validation-star", "train-star"]
