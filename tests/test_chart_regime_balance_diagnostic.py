from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.domain.regime import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    ThreeDayChartFeatureVector,
    build_daily_regime_episodes,
)


UTC = timezone.utc
START = datetime(2024, 7, 1, tzinfo=UTC)
END = datetime(2026, 7, 1, tzinfo=UTC)


def test_defaults_and_production_grid_are_frozen() -> None:
    from scripts.chart_regime_balance_diagnostic import build_primary_configs, parse_args

    args = parse_args([])
    assert args.symbol == "BTCUSDT"
    assert args.start == START
    assert args.end == END
    assert args.raw_root == Path(".research-data/binance-usdm")
    assert args.json_output.name.endswith(".json")
    assert args.markdown_output.name.endswith(".md")

    configs = build_primary_configs()
    assert len(configs) == 18
    assert len({config.identity for config in configs}) == 18
    assert {config.model.random_seed for config in configs} == {20260714}
    assert [(item.model.model_type, item.model.cluster_count) for item in configs[:6]] == [
        ("kmeans", count) for count in range(3, 9)
    ]
    assert {
        (item.model.cluster_count, item.model.covariance_type)
        for item in configs[6:]
    } == {(count, covariance) for count in range(3, 9) for covariance in ("diag", "tied")}


@pytest.mark.parametrize(
    "value",
    ["2024-07-01", "2024-07-01T01:00:00Z", "2024-07-01T00:00:00+00:00"],
)
def test_cli_bounds_require_canonical_midnight_z(value: str) -> None:
    from scripts.chart_regime_balance_diagnostic import parse_args

    with pytest.raises(SystemExit):
        parse_args(["--start", value])


def test_direct_script_help_runs_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/chart_regime_balance_diagnostic.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "three-day" in result.stdout.lower()


def _vectors() -> tuple[ThreeDayChartFeatureVector, ...]:
    episodes = build_daily_regime_episodes(START, END)
    names = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    return tuple(
        ThreeDayChartFeatureVector(
            symbol="BTCUSDT",
            anchor_at=episode.anchor_at,
            window_start_at=episode.feature_start_at,
            values={name: float((index + offset) % 97 + 1) for offset, name in enumerate(names)},
        )
        for index, episode in enumerate(episodes)
    )


def test_vector_contract_requires_exact_727_bounds_symbol_and_anchors() -> None:
    from scripts.chart_regime_balance_diagnostic import validate_vectors

    vectors = _vectors()
    assert len(vectors) == 727
    assert validate_vectors(vectors, symbol="BTCUSDT", start=START, end=END) == vectors
    with pytest.raises(ValueError, match="727"):
        validate_vectors(vectors[:-1], symbol="BTCUSDT", start=START, end=END)
    with pytest.raises(ValueError, match="symbol"):
        validate_vectors(vectors, symbol="ETHUSDT", start=START, end=END)
    bad = list(vectors)
    bad[2] = bad[1]
    with pytest.raises(ValueError, match="anchor"):
        validate_vectors(tuple(bad), symbol="BTCUSDT", start=START, end=END)


def test_report_assembly_is_deterministic_and_reserves_outcomes(tmp_path: Path) -> None:
    from scripts.chart_regime_balance_diagnostic import (
        assemble_report,
        canonical_json_bytes,
        write_reports_atomic,
    )

    vectors = _vectors()
    candidates = [{
        "identity": "fixture-kmeans-k3",
        "status": "accepted",
        "model": {"model_type": "kmeans", "cluster_count": 3, "random_seed": 20260714,
                  "covariance_type": None, "regularization": 1e-6},
        "fit": {"retained_feature_names": [spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1[:4]]},
        "metrics": {"counts": {"a": 243, "b": 242, "c": 242},
                    "shares": {"a": 243 / 727, "b": 242 / 727, "c": 242 / 727},
                    "normalized_entropy": -sum(share * math.log(share) for share in (243 / 727, 242 / 727, 242 / 727)) / math.log(3),
                    "minimum_ess": 20.0,
                    "quarterly": {}, "seed_stability": {}, "chronological_stability": [],
                    "silhouette": 0.3, "bic": None},
        "rejections": [],
    }]
    provenance = [{"url": "https://example.test/a.zip", "sha256": "a" * 64,
                   "bytes": 123, "period": "2024-07", "status": "cached"}]
    first = assemble_report(vectors=vectors, candidates=candidates, archive_provenance=provenance,
                            start=START, end=END, symbol="BTCUSDT")
    second = assemble_report(vectors=vectors, candidates=candidates, archive_provenance=provenance,
                             start=START, end=END, symbol="BTCUSDT")
    assert hashlib.sha256(canonical_json_bytes(first)).digest() == hashlib.sha256(canonical_json_bytes(second)).digest()
    assert first["sample_count"] == 727
    assert first["strategy_outcomes_read"] is False
    assert first["strategy_outcomes_evaluated"] is False
    assert first["production_model_selected"] is False
    assert first["outcome_evaluation"] == "reserved_not_evaluated"
    assert "following" not in canonical_json_bytes(first).decode().lower()

    json_path, markdown_path = tmp_path / "report.json", tmp_path / "report.md"
    write_reports_atomic(first, json_path=json_path, markdown_path=markdown_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["sample_count"] == 727
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "727 overlapping 3d windows are not independent" in markdown
    assert "no strategy evaluated" in markdown.lower()
    assert "no production model selected" in markdown.lower()


def test_atomic_writer_preserves_both_outputs_if_rendering_fails(tmp_path: Path, monkeypatch) -> None:
    import scripts.chart_regime_balance_diagnostic as module

    json_path, markdown_path = tmp_path / "report.json", tmp_path / "report.md"
    json_path.write_text("old-json", encoding="utf-8")
    markdown_path.write_text("old-markdown", encoding="utf-8")
    monkeypatch.setattr(module, "render_markdown", lambda payload: (_ for _ in ()).throw(ValueError("boom")))
    with pytest.raises(ValueError, match="boom"):
        module.write_reports_atomic({"sample_count": 727}, json_path=json_path, markdown_path=markdown_path)
    assert json_path.read_text(encoding="utf-8") == "old-json"
    assert markdown_path.read_text(encoding="utf-8") == "old-markdown"


def test_kline_rows_reject_duplicate_gap_wrong_symbol_bounds_and_nonfinite() -> None:
    from scripts.chart_regime_balance_diagnostic import candles_from_kline_rows

    start = datetime(2026, 1, 1, tzinfo=UTC)
    millis = int(start.timestamp() * 1000)
    row = [str(millis), "100", "101", "99", "100.5", "2", str(millis + 59_999), "0", "1", "0", "0", "0"]
    assert len(candles_from_kline_rows([row], symbol="BTCUSDT", start=start, end=start + timedelta(minutes=1))) == 1
    with pytest.raises(ValueError, match="duplicate|continuity"):
        candles_from_kline_rows([row, row], symbol="BTCUSDT", start=start, end=start + timedelta(minutes=2))
    with pytest.raises(ValueError, match="bounds"):
        candles_from_kline_rows([row], symbol="BTCUSDT", start=start + timedelta(minutes=1), end=start + timedelta(minutes=2))
    bad = row.copy(); bad[4] = "nan"
    with pytest.raises(ValueError, match="finite"):
        candles_from_kline_rows([bad], symbol="BTCUSDT", start=start, end=start + timedelta(minutes=1))
    with pytest.raises(ValueError, match="symbol"):
        candles_from_kline_rows([row], symbol="btcusdt", start=start, end=start + timedelta(minutes=1))


def test_fixture_orchestration_reports_727_without_archive_downloads(tmp_path: Path) -> None:
    from scripts.chart_regime_balance_diagnostic import (
        build_primary_configs,
        parse_args,
        run_diagnostic,
    )

    vectors = _vectors()
    provenance = [{"url": "https://example.test/BTCUSDT-1m-fixture.zip", "sha256": "f" * 64,
                   "bytes": 1234, "period": "fixture", "status": "cached"}]
    calls = []

    def vector_source(**kwargs):
        calls.append(kwargs)
        return vectors, provenance

    args = parse_args([
        "--json-output", str(tmp_path / "diagnostic.json"),
        "--markdown-output", str(tmp_path / "diagnostic.md"),
    ])
    report = run_diagnostic(args, vector_source=vector_source, configs=build_primary_configs()[:1])
    assert calls == [{"symbol": "BTCUSDT", "start": START, "end": END,
                      "raw_root": Path(".research-data/binance-usdm")}]
    assert report["sample_count"] == 727
    assert len(report["candidate_configs"]) == 1
    assert report["candidate_configs"][0]["status"] == "accepted"
    assert len(report["candidate_configs"][0]["metrics"]["seed_stability"]) == 2
    assert len(report["candidate_configs"][0]["metrics"]["chronological_stability"]) == 2


def test_nonfinite_report_metric_is_rejected_before_output_replacement(tmp_path: Path) -> None:
    from scripts.chart_regime_balance_diagnostic import write_reports_atomic

    json_path, markdown_path = tmp_path / "report.json", tmp_path / "report.md"
    json_path.write_text("old-json", encoding="utf-8")
    markdown_path.write_text("old-markdown", encoding="utf-8")
    with pytest.raises(ValueError, match="finite"):
        write_reports_atomic({"metric": float("nan")}, json_path=json_path, markdown_path=markdown_path)
    assert json_path.read_text(encoding="utf-8") == "old-json"
    assert markdown_path.read_text(encoding="utf-8") == "old-markdown"
