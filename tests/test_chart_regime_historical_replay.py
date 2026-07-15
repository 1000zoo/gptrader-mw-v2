from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.chart_regime_historical_replay import (
    HISTORICAL_END,
    HISTORICAL_START,
    SOURCE_SHA256,
    TRAINING_END,
    build_report,
    parse_args,
    render_markdown,
    write_reports_atomic,
)
from src.infrastructure.regime.historical_replay_source import load_historical_replay_source


UTC = timezone.utc


def test_defaults_freeze_historical_training_and_source_contracts():
    args = parse_args([])
    assert args.historical_start == datetime(2021, 1, 1, tzinfo=UTC)
    assert args.historical_end == datetime(2024, 7, 1, tzinfo=UTC)
    assert args.training_start == datetime(2024, 7, 1, tzinfo=UTC)
    assert args.training_end == datetime(2026, 7, 1, tzinfo=UTC)
    assert args.expected_source_sha256 == SOURCE_SHA256
    assert args.symbol == "BTCUSDT"


def test_build_report_rejects_non_adjacent_intervals():
    with pytest.raises(ValueError, match="adjacent"):
        build_report(
            symbol="BTCUSDT",
            historical_start=datetime(2021, 1, 1, tzinfo=UTC),
            historical_end=datetime(2024, 6, 30, tzinfo=UTC),
            training_start=datetime(2024, 7, 1, tzinfo=UTC),
            training_end=datetime(2026, 7, 1, tzinfo=UTC),
            source=None,
            historical_vectors=(),
            historical_provenance=(),
            training_vectors=(),
            training_provenance=(),
        )


def test_source_contract_loads_fixed_k4_and_k8():
    source = load_historical_replay_source(
        "docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json",
        expected_sha256=SOURCE_SHA256,
    )
    assert tuple(source.fits) == ("gmm-diag-k4", "gmm-diag-k8")


def test_output_alias_rejected_before_directory_creation(tmp_path):
    destination = tmp_path / "missing" / "report.json"
    with pytest.raises(ValueError, match="distinct"):
        write_reports_atomic({}, json_path=destination, markdown_path=destination.parent / "." / destination.name)
    assert not destination.parent.exists()


def test_nonfinite_payload_rejected(tmp_path):
    with pytest.raises(ValueError, match="finite"):
        write_reports_atomic(
            {"bad": float("nan")},
            json_path=tmp_path / "a.json",
            markdown_path=tmp_path / "a.md",
        )


def test_second_publish_failure_rolls_back_both_originals(tmp_path, monkeypatch):
    import scripts.chart_regime_historical_replay as cli

    json_path, markdown_path = tmp_path / "report.json", tmp_path / "report.md"
    json_path.write_bytes(b"old-json")
    markdown_path.write_bytes(b"old-markdown")
    original_replace = cli.Path.replace
    failed = False

    def replace(path, target):
        nonlocal failed
        if not failed and path.suffix == ".tmp" and Path(target) == markdown_path:
            failed = True
            raise OSError("second publication failed")
        return original_replace(path, target)

    monkeypatch.setattr(cli.Path, "replace", replace)
    with pytest.raises(OSError, match="second publication"):
        write_reports_atomic(
            {"models": [], "preferred_research_model": "none", "preference_rule": "none"},
            json_path=json_path, markdown_path=markdown_path,
        )
    assert json_path.read_bytes() == b"old-json"
    assert markdown_path.read_bytes() == b"old-markdown"
    assert not tuple(tmp_path.glob(".*.tmp"))
    assert not tuple(tmp_path.glob(".*.bak"))


def test_direct_entrypoint_help_is_utf8():
    completed = subprocess.run(
        [sys.executable, "scripts/chart_regime_historical_replay.py", "--help"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    assert "research only" in completed.stdout


def test_markdown_is_compact_and_states_research_limitations():
    model = {
        "identity": "gmm-diag-k4",
        "reference_cutoffs": {"dominant_posterior_p05": .6, "posterior_margin_p05": .2},
        "historical": {
            "envelope": {"any_feature_exceedance_share": .1, "clipped_dimension_quantiles": {"p50": 0., "p95": 1., "max": 2.}},
            "confidence": {"posterior_below_reference_share": .1, "margin_below_reference_share": .2, "component_distance_above_reference_share": .03},
            "jensen_shannon_divergence": .04,
            "effective_sample_sizes": {"minimum": 80.},
            "quarter_warnings": [],
        },
    }
    text = render_markdown({
        "models": [model], "preferred_research_model": "gmm-diag-k4",
        "preference_rule": "frozen rule",
    })
    assert "Reverse-time" in text and "not forward validation" in text
    assert "No strategy outcomes" in text and "no production model was selected" in text
    assert "14-quarter warnings" in text and "per-anchor" not in text


@dataclass(frozen=True)
class _Reference:
    sample_count: int
    quantile_method: str
    posterior_fifth_percentile: float
    margin_fifth_percentile: float
    component_distance_995: dict
    posterior_quantiles: dict
    margin_quantiles: dict
    distance_quantiles: dict


@dataclass(frozen=True)
class _Result:
    identity: str


def test_build_report_uses_training_only_for_reference_and_sets_false_flags(monkeypatch):
    import scripts.chart_regime_historical_replay as cli

    source = load_historical_replay_source(
        "docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json",
        expected_sha256=SOURCE_SHA256,
    )
    historical = tuple(object() for _ in range(1274))
    training = tuple(object() for _ in range(727))
    calls = []

    def diagnose(_fit, vectors, _registry):
        marker = "training" if vectors is training else "historical"
        return (marker,)

    def reference(rows, fingerprints):
        calls.append(rows)
        return _Reference(727, "linear", .5, .2, {name: 2. for name in fingerprints},
                          {"p05": .5}, {"p05": .2}, {"p05": 1.})

    monkeypatch.setattr(cli, "diagnose_gmm_assignments", diagnose)
    monkeypatch.setattr(cli, "build_confidence_reference", reference)
    monkeypatch.setattr(cli, "summarize_historical_replay_candidate", lambda **kw: _Result(kw["identity"]))
    monkeypatch.setattr(cli, "rank_historical_replay_candidates", lambda values: tuple(values))
    report = build_report(
        symbol="BTCUSDT", historical_start=HISTORICAL_START, historical_end=HISTORICAL_END,
        training_start=HISTORICAL_END, training_end=TRAINING_END, source=source,
        historical_vectors=historical, historical_provenance=(),
        training_vectors=training, training_provenance=(),
    )
    assert calls == [("training",), ("training",)]
    assert [item["identity"] for item in report["models"]] == ["gmm-diag-k4", "gmm-diag-k8"]
    assert all(report[key] is False for key in (
        "models_refit", "runtime_thresholds_present", "historical_cutoffs_fitted",
        "strategy_outcomes_read", "strategy_outcomes_evaluated", "production_model_selected",
    ))
