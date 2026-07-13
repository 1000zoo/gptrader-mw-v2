import json
from decimal import Decimal

from scripts.position_sizing_combo_search import (
    RESULTS_PATH,
    build_position_sizing_combos,
    load_seen_combo_ids_from,
)


def test_build_position_sizing_combos_varies_only_fixed_sizing() -> None:
    combos = build_position_sizing_combos(
        equity_ratios=(Decimal("0.02"), Decimal("0.50")),
        leverages=(Decimal("1"), Decimal("15")),
    )

    assert [combo.combo_id for combo in combos] == [
        "position-sizing-agent-range-wide4-s1-t1-fixed-er002-l01",
        "position-sizing-agent-range-wide4-s1-t1-fixed-er002-l15",
        "position-sizing-agent-range-wide4-s1-t1-fixed-er050-l01",
        "position-sizing-agent-range-wide4-s1-t1-fixed-er050-l15",
    ]
    assert {tuple(combo.strategy_params.items()) for combo in combos} == {
        (
            ("range_period", 300),
            ("lower_band", Decimal("0.06")),
            ("upper_band", Decimal("0.94")),
            ("min_range_width", Decimal("0.010")),
            ("reclaim_return", Decimal("0.0007")),
        )
    }
    assert {tuple(combo.tpsl_params.items()) for combo in combos} == {
        (
            ("kind", "fixed"),
            ("stop_loss_ratio", Decimal("0.09")),
            ("reward_risk_ratio", Decimal("0.15")),
        )
    }
    assert combos[-1].position_sizing_params == {
        "kind": "fixed",
        "equity_ratio": Decimal("0.50"),
        "leverage": Decimal("15"),
    }


def test_load_seen_combo_ids_from_uses_position_sizing_results(tmp_path) -> None:
    result_path = tmp_path / RESULTS_PATH.name
    result_path.write_text(
        json.dumps({"combo_id": "position-sizing-agent-range-wide4-s1-t1-fixed-er002-l01"})
        + "\n",
        encoding="utf-8",
    )

    assert load_seen_combo_ids_from(result_path) == {
        "position-sizing-agent-range-wide4-s1-t1-fixed-er002-l01"
    }
