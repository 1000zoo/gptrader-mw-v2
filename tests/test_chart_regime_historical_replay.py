from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import subprocess
import sys
import textwrap

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
from src.domain.regime import THREE_DAY_CHART_FEATURE_REGISTRY_V1, ThreeDayChartFeatureVector


UTC = timezone.utc


def test_defaults_freeze_historical_training_and_source_contracts():
    args = parse_args([])
    assert args.historical_start == datetime(2021, 1, 1, tzinfo=UTC)
    assert args.historical_end == datetime(2024, 7, 1, tzinfo=UTC)
    assert args.training_start == datetime(2024, 7, 1, tzinfo=UTC)
    assert args.training_end == datetime(2026, 7, 1, tzinfo=UTC)
    assert args.expected_source_sha256 == SOURCE_SHA256
    assert args.symbol == "BTCUSDT"
    assert args.source_report == Path("docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json")
    assert args.raw_kline_root == Path(".research-data/binance-usdm/raw/klines")
    assert args.output_json == Path("docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.json")
    assert args.output_markdown == Path("docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.md")


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


def test_resolved_destination_alias_is_rejected(tmp_path):
    target = tmp_path / "report"
    target.write_text("old", encoding="utf-8")
    link = tmp_path / "alias"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are not available")
    with pytest.raises(ValueError, match="distinct"):
        write_reports_atomic({}, json_path=target, markdown_path=link)


@pytest.mark.skipif(os.path.normcase("A") != os.path.normcase("a"), reason="case-sensitive platform")
def test_case_normalized_destination_alias_is_rejected(tmp_path):
    destination = tmp_path / "Report.JSON"
    with pytest.raises(ValueError, match="distinct"):
        write_reports_atomic({}, json_path=destination, markdown_path=tmp_path / "report.json")


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


def test_restore_failure_preserves_backup_and_annotates_publication_error(tmp_path, monkeypatch):
    import scripts.chart_regime_balance_diagnostic as shared

    json_path, markdown_path = tmp_path / "report.json", tmp_path / "report.md"
    json_path.write_bytes(b"old-json"); markdown_path.write_bytes(b"old-markdown")
    original_replace = shared.Path.replace
    publish_failed = False

    def replace(path, target):
        nonlocal publish_failed
        if not publish_failed and path.suffix == ".tmp" and Path(target) == markdown_path:
            publish_failed = True
            raise OSError("publication sentinel")
        if publish_failed and path.suffix == ".bak" and Path(target) == markdown_path:
            raise OSError("restore sentinel")
        return original_replace(path, target)

    monkeypatch.setattr(shared.Path, "replace", replace)
    with pytest.raises(OSError, match="publication sentinel") as caught:
        write_reports_atomic(
            {"models": [], "preferred_research_model": "none", "preference_rule": "none"},
            json_path=json_path, markdown_path=markdown_path,
        )
    assert any("restore sentinel" in note for note in caught.value.__notes__)
    backups = tuple(tmp_path.glob(".*.bak"))
    assert len(backups) == 1 and backups[0].read_bytes() == b"old-markdown"


def test_cleanup_failure_does_not_mask_publication_error(tmp_path, monkeypatch):
    import scripts.chart_regime_balance_diagnostic as shared

    original_write_temp = shared._write_temp
    original_unlink = shared.Path.unlink
    calls = 0

    def write_temp(final, content):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("publication sentinel")
        return original_write_temp(final, content)

    def unlink(path, *args, **kwargs):
        if path.suffix == ".tmp":
            raise OSError("cleanup sentinel")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(shared, "_write_temp", write_temp)
    monkeypatch.setattr(shared.Path, "unlink", unlink)
    with pytest.raises(OSError, match="publication sentinel"):
        write_reports_atomic(
            {"models": [], "preferred_research_model": "none", "preference_rule": "none"},
            json_path=tmp_path / "report.json", markdown_path=tmp_path / "report.md",
        )


def test_direct_entrypoint_help_is_utf8():
    completed = subprocess.run(
        [sys.executable, "scripts/chart_regime_historical_replay.py", "--help"],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    assert "research only" in completed.stdout


def test_canonical_payload_is_identical_across_external_thread_limits():
    code = textwrap.dedent("""
        from dataclasses import dataclass
        from datetime import timedelta
        import sys
        import scripts.chart_regime_historical_replay as c
        from src.domain.regime import THREE_DAY_CHART_FEATURE_REGISTRY_V1, ThreeDayChartFeatureVector
        from src.infrastructure.regime.historical_replay_source import load_historical_replay_source
        names=tuple(s.name for s in THREE_DAY_CHART_FEATURE_REGISTRY_V1); values={n:0. for n in names}
        def vectors(start,end):
            return tuple(ThreeDayChartFeatureVector('BTCUSDT',start+timedelta(days=d),start+timedelta(days=d-3),values) for d in range(3,(end-start).days))
        @dataclass(frozen=True)
        class Ref:
            sample_count:int; quantile_method:str; posterior_fifth_percentile:float; margin_fifth_percentile:float
            component_distance_995:dict; posterior_quantiles:dict; margin_quantiles:dict; distance_quantiles:dict
        @dataclass(frozen=True)
        class Result:
            identity:str; balance:dict
        c.diagnose_gmm_assignments=lambda fit,rows,registry: ('training' if len(rows)==727 else 'historical',)
        c.build_confidence_reference=lambda rows,fps: Ref(727,'linear',.5,.2,{n:2. for n in fps},{'p05':.5},{'p05':.2},{'p05':1.})
        c.summarize_historical_replay_candidate=lambda **kw: Result(kw['identity'],{'counts':{n:1 for n in kw['fit'].fingerprints},'shares':{n:1/len(kw['fit'].fingerprints) for n in kw['fit'].fingerprints}})
        c.rank_historical_replay_candidates=lambda rows: tuple(rows)
        def provenance(period):
            member=f'BTCUSDT-1m-{period}.zip'; return ({'period':period,'url':f'https://data.binance.vision/{member}','sha256':'a'*64,'bytes':123,'member_identity':member},)
        source=load_historical_replay_source('docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json',expected_sha256=c.SOURCE_SHA256)
        report=c.build_report(symbol='BTCUSDT',historical_start=c.HISTORICAL_START,historical_end=c.HISTORICAL_END,training_start=c.HISTORICAL_END,training_end=c.TRAINING_END,source=source,historical_vectors=vectors(c.HISTORICAL_START,c.HISTORICAL_END),historical_provenance=provenance('2021-01'),training_vectors=vectors(c.HISTORICAL_END,c.TRAINING_END),training_provenance=provenance('2024-07'))
        sys.stdout.buffer.write(c.canonical_json_bytes(report))
    """)
    outputs = []
    for limit in ("1", "4"):
        env = dict(os.environ, OMP_NUM_THREADS=limit, OPENBLAS_NUM_THREADS=limit, MKL_NUM_THREADS=limit)
        outputs.append(subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, env=env).stdout)
    assert outputs[0] == outputs[1]


def test_markdown_is_compact_and_states_research_limitations():
    model = {
        "identity": "gmm-diag-k4",
        "reference_cutoffs": {"dominant_posterior_p05": .6, "posterior_margin_p05": .2},
        "training_distribution": {"counts": {"a": 7}, "shares": {"a": 1.0}},
        "historical_distribution": {"counts": {"a": 9}, "shares": {"a": 1.0}, "prevalence_delta_vs_training": {"a": 0.0}},
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
    assert "training counts/shares" in text and "historical-training deltas" in text


def test_provenance_boundary_rejects_empty_duplicate_and_ephemeral_fields():
    import scripts.chart_regime_historical_replay as cli

    with pytest.raises(ValueError, match="nonempty"):
        cli._canonical_provenance((), interval_name="historical")
    row = _provenance("2021-01")[0]
    with pytest.raises(ValueError, match="unique"):
        cli._canonical_provenance((row, dict(row)), interval_name="historical")
    with pytest.raises(ValueError, match="field order"):
        cli._canonical_provenance(({**row, "status": "cached"},), interval_name="historical")


def test_vector_boundary_rejects_count_symbol_anchor_and_window():
    import scripts.chart_regime_historical_replay as cli

    vectors = _vectors(HISTORICAL_START, HISTORICAL_END)
    with pytest.raises(ValueError, match="1274"):
        cli._validate_vectors(vectors[:-1], symbol="BTCUSDT", start=HISTORICAL_START, end=HISTORICAL_END, count=1274, name="historical")
    bad_symbol = (replace(vectors[0], symbol="ETHUSDT"), *vectors[1:])
    with pytest.raises(ValueError, match="symbol"):
        cli._validate_vectors(bad_symbol, symbol="BTCUSDT", start=HISTORICAL_START, end=HISTORICAL_END, count=1274, name="historical")
    bad_anchor = (replace(
        vectors[0], anchor_at=vectors[0].anchor_at + timedelta(days=1),
        window_start_at=vectors[0].window_start_at + timedelta(days=1),
    ), *vectors[1:])
    with pytest.raises(ValueError, match="anchors"):
        cli._validate_vectors(bad_anchor, symbol="BTCUSDT", start=HISTORICAL_START, end=HISTORICAL_END, count=1274, name="historical")
    with pytest.raises(ValueError, match="window start"):
        replace(vectors[0], window_start_at=vectors[0].window_start_at + timedelta(minutes=1))


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
    balance: dict


def _vectors(start, end):
    names = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    values = {name: 0.0 for name in names}
    return tuple(
        ThreeDayChartFeatureVector("BTCUSDT", anchor, anchor - timedelta(days=3), values)
        for anchor in (
            start + timedelta(days=day)
            for day in range(3, (end - start).days)
        )
    )


def _provenance(period):
    member = f"BTCUSDT-1m-{period}.zip"
    return ({
        "period": period,
        "url": f"https://data.binance.vision/{member}",
        "sha256": "a" * 64,
        "bytes": 123,
        "member_identity": member,
    },)


def test_build_report_uses_training_only_for_reference_and_sets_false_flags(monkeypatch):
    import scripts.chart_regime_historical_replay as cli

    source = load_historical_replay_source(
        "docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json",
        expected_sha256=SOURCE_SHA256,
    )
    historical = _vectors(HISTORICAL_START, HISTORICAL_END)
    training = _vectors(HISTORICAL_END, TRAINING_END)
    calls = []
    from src.infrastructure.regime.sklearn_cluster_diagnostic import SklearnClusterDiagnostic
    monkeypatch.setattr(SklearnClusterDiagnostic, "fit", lambda *args, **kwargs: pytest.fail("fixed replay refit"))

    def diagnose(_fit, vectors, _registry):
        marker = "training" if vectors is training else "historical"
        return (marker,)

    def reference(rows, fingerprints):
        calls.append(rows)
        return _Reference(727, "linear", .5, .2, {name: 2. for name in fingerprints},
                          {"p05": .5}, {"p05": .2}, {"p05": 1.})

    monkeypatch.setattr(cli, "diagnose_gmm_assignments", diagnose)
    monkeypatch.setattr(cli, "build_confidence_reference", reference)
    monkeypatch.setattr(cli, "summarize_historical_replay_candidate", lambda **kw: _Result(
        kw["identity"], {"counts": {name: 1 for name in kw["fit"].fingerprints},
                         "shares": {name: 1 / len(kw["fit"].fingerprints) for name in kw["fit"].fingerprints}},
    ))
    monkeypatch.setattr(cli, "rank_historical_replay_candidates", lambda values: tuple(values))
    report = build_report(
        symbol="BTCUSDT", historical_start=HISTORICAL_START, historical_end=HISTORICAL_END,
        training_start=HISTORICAL_END, training_end=TRAINING_END, source=source,
        historical_vectors=historical, historical_provenance=_provenance("2021-01"),
        training_vectors=training, training_provenance=_provenance("2024-07"),
    )
    assert calls == [("training",), ("training",)]
    assert [item["identity"] for item in report["models"]] == ["gmm-diag-k4", "gmm-diag-k8"]
    assert all(report[key] is False for key in (
        "models_refit", "runtime_thresholds_present", "historical_cutoffs_fitted",
        "strategy_outcomes_read", "strategy_outcomes_evaluated", "production_model_selected",
    ))
    assert report["historical_first_anchor"] == "2021-01-04T00:00:00Z"
    assert report["historical_last_anchor"] == "2024-06-30T00:00:00Z"
    assert report["training_reference_first_anchor"] == "2024-07-04T00:00:00Z"
    assert report["training_reference_last_anchor"] == "2026-06-30T00:00:00Z"
    assert set(report["archive_combined_sha256"]) == {"historical", "training_reference", "overall"}
    assert all(len(item["source_fit_sha256"]) == 64 for item in report["models"])


def test_run_wires_source_and_exactly_two_interval_loads(monkeypatch):
    import scripts.chart_regime_historical_replay as cli

    args = parse_args([])
    source = object()
    calls = []
    monkeypatch.setattr(cli, "load_historical_replay_source", lambda path, expected_sha256: source)

    def loader(**kwargs):
        calls.append(kwargs)
        count = kwargs["expected_anchor_count"]
        return tuple(range(count)), _provenance("2021-01" if count == 1274 else "2024-07")

    sentinel = {"ok": True}
    monkeypatch.setattr(cli, "load_three_day_feature_history", loader)
    monkeypatch.setattr(cli, "build_report", lambda **kwargs: sentinel)
    assert cli.run(args) is sentinel
    assert [(call["start"], call["end"], call["expected_anchor_count"]) for call in calls] == [
        (HISTORICAL_START, HISTORICAL_END, 1274), (HISTORICAL_END, TRAINING_END, 727),
    ]
    assert all(call["symbol"] == "BTCUSDT" and call["raw_root"] == args.raw_kline_root for call in calls)


def test_run_propagates_source_and_archive_failures(monkeypatch):
    import scripts.chart_regime_historical_replay as cli

    args = parse_args([])
    monkeypatch.setattr(cli, "load_historical_replay_source", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("source sentinel")))
    with pytest.raises(ValueError, match="source sentinel"):
        cli.run(args)
    monkeypatch.setattr(cli, "load_historical_replay_source", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "load_three_day_feature_history", lambda **kwargs: (_ for _ in ()).throw(ValueError("archive sentinel")))
    with pytest.raises(ValueError, match="archive sentinel"):
        cli.run(args)


def test_main_wires_run_to_pair_publication(monkeypatch):
    import scripts.chart_regime_historical_replay as cli

    report = {"sentinel": True}
    captured = {}
    monkeypatch.setattr(cli, "run", lambda args: report)
    monkeypatch.setattr(cli, "write_reports_atomic", lambda payload, **kwargs: captured.update(payload=payload, **kwargs))
    assert cli.main([]) == 0
    assert captured == {
        "payload": report,
        "json_path": Path("docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.json"),
        "markdown_path": Path("docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.md"),
    }
