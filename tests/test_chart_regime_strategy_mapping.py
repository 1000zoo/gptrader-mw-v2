from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path
import hashlib
import json
from io import BytesIO
import subprocess
import sys
import zipfile
from types import SimpleNamespace

import pytest

from scripts.chart_regime_strategy_mapping import (
    BTCUSDT_FIRST_FOLD,
    PRODUCTION_WALK_FORWARD_GRID,
    WalkForwardDependencies,
    WalkForwardGrid,
    WalkForwardInputs,
    parse_walk_forward_args,
    run_chart_regime_walk_forward,
    run_mapping_episodes,
    run_scheduler_driven_regime_backtest,
    write_walk_forward_reports,
)
from scripts.chart_regime_strategy_mapping import _canonical_hash
from scripts.chart_regime_strategy_mapping import _normalize_bounded_metric
from scripts.chart_regime_strategy_mapping import _gmm_bic, _gmm_parameter_count
from scripts.chart_regime_strategy_mapping import _chronological_block_stability
from scripts.chart_regime_strategy_mapping import _continuous_diagnostics
from scripts.chart_regime_strategy_mapping import _manual_router_candidate
from scripts.chart_regime_strategy_mapping import _mapping_feature_coverage
from scripts.chart_regime_strategy_mapping import _project_centroids_to_primary_coordinates
from scripts.chart_regime_strategy_mapping import _run_mapping_coverage_filtered_evidence
from scripts.chart_regime_strategy_mapping import _manual_router_for_replay
from scripts.chart_regime_strategy_mapping import _default_replay_test
from scripts.scheduler_driven_scalping_backtest import (
    FEE_RATE,
    SchedulerBacktestCandidate,
    StrategyCandidateSpec,
    feature_provider_config_hash,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe


def _required_test_provenance(freeze) -> dict[str, object]:
    payload = freeze.canonical_payload
    return {
        "pre_test_freeze_hash": freeze.pre_test_freeze_hash,
        "model_artifact_hash": payload["model"].get("artifact_hash"),
        "candidate_manifest_hash": payload["candidate_manifest"].get("manifest_hash"),
        "candidate_universe_hash": payload["candidate_manifest"].get("candidate_universe_hash"),
        "mapping_artifact_hash": payload["mapping"].get("artifact_hash"),
        "profile_id": payload["profile"].get("profile_id"),
    }


def test_mapping_module_exposes_scheduler_driven_regime_replay() -> None:
    from scripts.scheduler_driven_scalping_backtest import (
        run_scheduler_driven_regime_backtest as canonical_replay,
    )

    assert run_scheduler_driven_regime_backtest is canonical_replay


def test_chart_regime_cli_help_runs_as_a_direct_script() -> None:
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "chart_regime_strategy_mapping.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Leakage-safe BTCUSDT regime walk-forward" in completed.stdout


def test_partial_walk_forward_fold_dates_are_rejected() -> None:
    with pytest.raises(SystemExit) as error:
        parse_walk_forward_args([
            "--symbol", "BTCUSDT", "--cluster-fit-start", "2021-01-01",
            "--output-json", "report.json", "--output-markdown", "report.md",
        ])
    assert error.value.code == 2


def test_no_walk_forward_fold_dates_keeps_default_selection_available() -> None:
    args = parse_walk_forward_args([
        "--symbol", "BTCUSDT", "--output-json", "report.json",
        "--output-markdown", "report.md",
    ])
    assert all(
        getattr(args, name) is None
        for name in (
            "cluster_fit_start", "cluster_fit_end", "mapping_fit_start", "mapping_fit_end",
            "validation_start", "validation_end", "test_start", "test_end",
        )
    )


def test_three_day_profile_has_frozen_default_outputs_and_requires_explicit_profile() -> None:
    args = parse_walk_forward_args([
        "--profile", "three-day-daily-k4-v1", "--symbol", "BTCUSDT",
        "--evidence-rows-path", "evidence.jsonl", "--resume",
    ])

    root = Path("docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily")
    assert args.profile == "three-day-daily-k4-v1"
    assert args.evidence_rows_path == Path("evidence.jsonl")
    assert args.resume is True
    assert args.output_json == root.with_suffix(".json")
    assert args.output_markdown == root.with_suffix(".md")
    assert args.output_model == root.with_name(root.name + "-model.json")
    assert args.output_mapping == root.with_name(root.name + "-mapping.json")

    with pytest.raises(SystemExit):
        parse_walk_forward_args([
            "--symbol", "BTCUSDT", "--evidence-rows-path", "evidence.jsonl",
            "--output-json", "report.json", "--output-markdown", "report.md",
        ])


def test_three_day_profile_rejects_weekly_tuning_arguments() -> None:
    with pytest.raises(SystemExit):
        parse_walk_forward_args([
            "--profile", "three-day-daily-k4-v1", "--symbol", "BTCUSDT",
            "--candidate-group", "all",
        ])


def test_pre_test_freeze_is_immutable_and_excludes_test_results() -> None:
    from scripts.chart_regime_strategy_mapping import create_pre_test_freeze

    model = {"artifact_hash": "a" * 64, "gates": {"passed": True}}
    freeze = create_pre_test_freeze(
        model=model,
        candidate_manifest={"candidate_count": 459, "manifest_hash": "b" * 64},
        evidence={"mapping": {"ledger_hash": "c" * 64}, "validation": {"ledger_hash": "d" * 64}},
        mapping={"artifact_hash": "e" * 64, "risk_policy": "strict"},
        global_fixed_baseline={"decision": "cash", "candidate_id": None},
        profile={"profile_id": "three-day-daily-k4-v1"},
        chronology={"validation_end_at": "2026-04-01T00:00:00Z"},
    )
    original_hash = freeze.pre_test_freeze_hash

    model["gates"]["passed"] = False
    assert freeze.pre_test_freeze_hash == original_hash
    assert "test_results" not in freeze.canonical_payload
    with pytest.raises(TypeError):
        freeze.canonical_payload["profile"] = {}


def test_test_loader_requires_validated_freeze_and_records_first_read() -> None:
    from scripts.chart_regime_strategy_mapping import (
        ThreeDayExperimentStage,
        ThreeDayExperimentState,
        create_pre_test_freeze,
        load_test_after_freeze,
    )

    state = ThreeDayExperimentState()
    calls = []
    with pytest.raises(RuntimeError, match="freeze"):
        load_test_after_freeze(state=state, freeze=None, loader=lambda: calls.append(True))
    assert calls == []

    freeze = create_pre_test_freeze(
        model={"artifact_hash": "a" * 64}, candidate_manifest={"candidate_count": 459},
        evidence={}, mapping={"artifact_hash": "b" * 64},
        global_fixed_baseline={"decision": "cash"},
        profile={"profile_id": "three-day-daily-k4-v1"}, chronology={},
    )
    state = ThreeDayExperimentState(stage=ThreeDayExperimentStage.PRE_TEST_FROZEN)
    sentinel = {"provenance": _required_test_provenance(freeze)}
    assert load_test_after_freeze(state=state, freeze=freeze, loader=lambda: sentinel) is sentinel
    assert state.stage is ThreeDayExperimentStage.TEST_LOADED
    assert state.events[-1][0] == "first_test_read"
    assert state.events[-1][1:] == (1, "TEST_LOADED", "2026-04-04T00:00:00Z")


def test_failing_test_loader_leaves_freeze_stage_and_no_read_event() -> None:
    from scripts.chart_regime_strategy_mapping import (
        ThreeDayExperimentStage, ThreeDayExperimentState,
        create_pre_test_freeze, load_test_after_freeze,
    )
    freeze = create_pre_test_freeze(
        model={"artifact_hash": "a" * 64}, candidate_manifest={"candidate_count": 459},
        evidence={}, mapping={"artifact_hash": "b" * 64},
        global_fixed_baseline={"decision": "cash"},
        profile={"profile_id": "three-day-daily-k4-v1"}, chronology={},
    )
    state = ThreeDayExperimentState(stage=ThreeDayExperimentStage.PRE_TEST_FROZEN)
    with pytest.raises(OSError, match="read failed"):
        load_test_after_freeze(
            state=state, freeze=freeze,
            loader=lambda: (_ for _ in ()).throw(OSError("read failed")),
        )
    assert state.stage is ThreeDayExperimentStage.PRE_TEST_FROZEN
    assert state.events == []


@pytest.mark.parametrize("supplied", (None, "b" * 64, "A" * 64, "malformed"))
def test_test_loader_rejects_missing_wrong_or_malformed_freeze_hash(supplied) -> None:
    from scripts.chart_regime_strategy_mapping import (
        ThreeDayExperimentStage, ThreeDayExperimentState,
        create_pre_test_freeze, load_test_after_freeze,
    )
    freeze = create_pre_test_freeze(
        model={"artifact_hash": "a" * 64}, candidate_manifest={"candidate_count": 459},
        evidence={}, mapping={"artifact_hash": "c" * 64},
        global_fixed_baseline={"decision": "cash"},
        profile={"profile_id": "three-day-daily-k4-v1"}, chronology={},
    )
    provenance = {} if supplied is None else {"pre_test_freeze_hash": supplied}
    state = ThreeDayExperimentState(stage=ThreeDayExperimentStage.PRE_TEST_FROZEN)
    with pytest.raises(ValueError, match="freeze hash"):
        load_test_after_freeze(
            state=state, freeze=freeze,
            loader=lambda: {"provenance": provenance},
        )
    assert state.stage is ThreeDayExperimentStage.PRE_TEST_FROZEN
    assert state.events == []


@pytest.mark.parametrize(
    "identity",
    (
        "model_artifact_hash", "candidate_manifest_hash",
        "candidate_universe_hash", "mapping_artifact_hash", "profile_id",
    ),
)
def test_test_loader_rejects_any_supplied_identity_that_disagrees_with_freeze(identity) -> None:
    from scripts.chart_regime_strategy_mapping import (
        ThreeDayExperimentStage, ThreeDayExperimentState,
        create_pre_test_freeze, load_test_after_freeze,
    )
    freeze = create_pre_test_freeze(
        model={"artifact_hash": "a" * 64},
        candidate_manifest={
            "manifest_hash": "b" * 64,
            "candidate_universe_hash": "c" * 64,
        },
        evidence={}, mapping={"artifact_hash": "d" * 64},
        global_fixed_baseline={"decision": "cash"},
        profile={"profile_id": "three-day-daily-k4-v1"}, chronology={},
    )
    provenance = {
        "pre_test_freeze_hash": freeze.pre_test_freeze_hash,
        "model_artifact_hash": "a" * 64,
        "candidate_manifest_hash": "b" * 64,
        "candidate_universe_hash": "c" * 64,
        "mapping_artifact_hash": "d" * 64,
        "profile_id": "three-day-daily-k4-v1",
    }
    provenance[identity] = "wrong"
    state = ThreeDayExperimentState(stage=ThreeDayExperimentStage.PRE_TEST_FROZEN)

    with pytest.raises(ValueError, match=identity):
        load_test_after_freeze(
            state=state, freeze=freeze,
            loader=lambda: {"provenance": provenance},
        )

    assert state.stage is ThreeDayExperimentStage.PRE_TEST_FROZEN
    assert state.events == []


def test_test_loader_requires_every_non_null_frozen_identity() -> None:
    from scripts.chart_regime_strategy_mapping import (
        ThreeDayExperimentStage, ThreeDayExperimentState,
        create_pre_test_freeze, load_test_after_freeze,
    )
    freeze = create_pre_test_freeze(
        model={"artifact_hash": "a" * 64},
        candidate_manifest={
            "manifest_hash": "b" * 64,
            "candidate_universe_hash": "c" * 64,
        },
        evidence={}, mapping={"artifact_hash": "d" * 64},
        global_fixed_baseline={"decision": "cash"},
        profile={"profile_id": "three-day-daily-k4-v1"}, chronology={},
    )
    state = ThreeDayExperimentState(stage=ThreeDayExperimentStage.PRE_TEST_FROZEN)

    with pytest.raises(ValueError, match="model_artifact_hash"):
        load_test_after_freeze(
            state=state,
            freeze=freeze,
            loader=lambda: {"provenance": {
                "pre_test_freeze_hash": freeze.pre_test_freeze_hash,
            }},
        )

    assert state.stage is ThreeDayExperimentStage.PRE_TEST_FROZEN
    assert state.events == []


def test_pretest_freeze_recursively_rejects_test_material() -> None:
    from scripts.chart_regime_strategy_mapping import create_pre_test_freeze

    with pytest.raises(ValueError, match="Test"):
        create_pre_test_freeze(
            model={"artifact_hash": "a" * 64}, candidate_manifest={"candidate_count": 459},
            evidence={"validation": {"nested": {"test_hash": "x"}}},
            mapping={"artifact_hash": "b" * 64},
            global_fixed_baseline={"decision": "cash"},
            profile={"profile_id": "three-day-daily-k4-v1"}, chronology={},
        )


def test_four_file_publication_is_atomic_and_rejects_aliases_before_mutation(tmp_path) -> None:
    from scripts.chart_regime_strategy_mapping import write_three_day_publication_atomic

    paths = tuple(tmp_path / name for name in ("report.json", "report.md", "model.json", "mapping.json"))
    write_three_day_publication_atomic(
        report_json=b"report\n", report_markdown=b"markdown\n",
        model_json=b"model\n", mapping_json=b"mapping\n",
        output_json=paths[0], output_markdown=paths[1],
        output_model=paths[2], output_mapping=paths[3],
    )
    assert tuple(path.read_bytes() for path in paths) == (
        b"report\n", b"markdown\n", b"model\n", b"mapping\n"
    )
    assert not tuple(tmp_path.glob(".*.tmp"))
    assert not tuple(tmp_path.glob(".*.bak"))

    original = paths[0].read_bytes()
    with pytest.raises(ValueError, match="distinct"):
        write_three_day_publication_atomic(
            report_json=b"changed", report_markdown=b"markdown",
            model_json=b"model", mapping_json=b"mapping",
            output_json=paths[0], output_markdown=paths[0],
            output_model=paths[2], output_mapping=paths[3],
        )
    assert paths[0].read_bytes() == original


def test_three_day_orchestrator_enforces_exact_pretest_order_and_strict_test_policy() -> None:
    from scripts.chart_regime_strategy_mapping import (
        ThreeDayExperimentDependencies,
        run_three_day_daily_k4_experiment,
    )
    from src.domain.regime import STRICT_RISK_POLICY

    calls = []
    model = {"artifact_hash": "a" * 64}
    manifest = {"candidate_count": 459, "manifest_hash": "b" * 64}

    def called(name, result):
        def invoke(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result
        return invoke

    deps = ThreeDayExperimentDependencies(
        verify_sources=called("verify_sources", {"source_hash": "c" * 64}),
        fit_and_freeze_model=called("fit_model", model),
        freeze_candidates=called("freeze_candidates", manifest),
        load_mapping_evidence=called("mapping_evidence", {"ledger_hash": "d" * 64}),
        build_strict_mapping=called("strict_mapping", {"artifact_hash": "e" * 64}),
        load_validation_evidence=called("validation_evidence", {"ledger_hash": "f" * 64}),
        report_validation_sensitivity=called("sensitivity", {"winner": "looser"}),
        rebuild_final_strict_mapping=called("final_mapping", {"artifact_hash": "1" * 64}),
        select_global_fixed_baseline=called("global_baseline", {"decision": "cash"}),
        load_test=lambda freeze: (
            calls.append(("load_test", (freeze,), {}))
            or {"provenance": _required_test_provenance(freeze)}
        ),
        run_test_comparisons=called("comparisons", {"cash": {"status": "ok"}}),
        publish=called("publish", None),
    )

    result = run_three_day_daily_k4_experiment(dependencies=deps)

    assert [name for name, _, _ in calls] == [
        "verify_sources", "fit_model", "freeze_candidates", "mapping_evidence",
        "strict_mapping", "validation_evidence", "sensitivity", "final_mapping",
        "global_baseline", "load_test", "comparisons", "publish",
    ]
    load_test_call = calls[9]
    assert load_test_call[1][0].pre_test_freeze_hash == result["pre_test_freeze_hash"]
    assert calls[10][2]["risk_policy"] == STRICT_RISK_POLICY
    assert result["validation_sensitivity"]["winner"] == "looser"
    assert result["strict_mapping"]["artifact_hash"] == "1" * 64
    assert calls[-1][2]["report"] == result


def _narrow_orchestration_dependencies(model, calls):
    from scripts.chart_regime_strategy_mapping import ThreeDayExperimentDependencies

    def called(name, result):
        def invoke(*args, **kwargs):
            calls.append(name)
            return result
        return invoke

    return ThreeDayExperimentDependencies(
        verify_sources=called("verify", {}),
        fit_and_freeze_model=called("model", model),
        freeze_candidates=called("manifest", {"manifest_hash": "b" * 64}),
        load_mapping_evidence=called("mapping-evidence", {}),
        build_strict_mapping=called("initial-mapping", {"artifact_hash": "c" * 64}),
        load_validation_evidence=called("validation-evidence", {}),
        report_validation_sensitivity=called("sensitivity", {}),
        rebuild_final_strict_mapping=called("final-mapping", {"artifact_hash": "d" * 64}),
        select_global_fixed_baseline=called("baseline", {"decision": "cash"}),
        load_test=lambda freeze: (
            calls.append("load-test")
            or {"provenance": _required_test_provenance(freeze)}
        ),
        run_test_comparisons=called("comparisons", {}),
        publish=called("publish", None),
    )


def test_orchestrator_rejects_model_test_results_before_test_read() -> None:
    from scripts.chart_regime_strategy_mapping import run_three_day_daily_k4_experiment

    calls = []
    dependencies = _narrow_orchestration_dependencies(
        {"artifact_hash": "a" * 64, "nested": {"test_results": {"return": "1"}}},
        calls,
    )

    with pytest.raises(ValueError, match="Test"):
        run_three_day_daily_k4_experiment(dependencies=dependencies)

    assert "load-test" not in calls


def test_orchestrator_allows_exact_canonical_model_profile_test_interval() -> None:
    from scripts.chart_regime_strategy_mapping import run_three_day_daily_k4_experiment
    from tests.infrastructure.regime.test_three_day_k4_model_artifact import _artifact

    calls = []
    model = _artifact()
    dependencies = _narrow_orchestration_dependencies(model, calls)

    report = run_three_day_daily_k4_experiment(dependencies=dependencies)

    assert "load-test" in calls
    assert report["model_artifact"] == model.canonical_payload()


def test_identical_orchestration_runs_have_identical_canonical_reports() -> None:
    from scripts.chart_regime_strategy_mapping import (
        ThreeDayExperimentDependencies, run_three_day_daily_k4_experiment,
    )

    def dependencies():
        return ThreeDayExperimentDependencies(
            verify_sources=lambda: {"source_hash": "a" * 64},
            fit_and_freeze_model=lambda sources: {"artifact_hash": "b" * 64},
            freeze_candidates=lambda: {"candidate_count": 459, "manifest_hash": "c" * 64},
            load_mapping_evidence=lambda **kwargs: {"ledger_hash": "d" * 64},
            build_strict_mapping=lambda **kwargs: {"artifact_hash": "e" * 64},
            load_validation_evidence=lambda **kwargs: {"ledger_hash": "f" * 64},
            report_validation_sensitivity=lambda **kwargs: {"strict": {}},
            rebuild_final_strict_mapping=lambda **kwargs: {"artifact_hash": "1" * 64},
            select_global_fixed_baseline=lambda **kwargs: {"decision": "cash"},
            load_test=lambda freeze: {
                "provenance": _required_test_provenance(freeze)
            },
            run_test_comparisons=lambda **kwargs: {"cash": {"status": "completed"}},
            publish=lambda **kwargs: None,
        )

    first = run_three_day_daily_k4_experiment(dependencies=dependencies())
    second = run_three_day_daily_k4_experiment(dependencies=dependencies())
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert {
        "source_verification", "intervals", "purges", "candidate_manifest",
        "model_artifact", "evidence", "validation_sensitivity", "strict_mapping",
        "strict_mapping_artifact_hash", "global_fixed_baseline", "test_provenance",
        "test_comparisons", "selection_and_exit_audits", "concentration_audit",
        "adoption_assessment", "safety", "leakage_audit", "limitations",
    } <= set(first)


def test_three_day_publication_render_is_byte_identical_and_noncyclic() -> None:
    from scripts.chart_regime_strategy_mapping import render_three_day_publication

    report = {
        "schema_version": "three-day-daily-k4-report-v1",
        "pre_test_freeze_hash": "a" * 64,
        "strict_mapping": {"entries": []},
        "validation_sensitivity": {}, "test_comparisons": {}, "limitations": [],
    }
    first = render_three_day_publication(
        report=report, model_json=b'{"artifact_hash":"' + b"b" * 64 + b'"}\n',
        mapping_json=b'{"artifact_hash":"' + b"c" * 64 + b'"}\n',
    )
    second = render_three_day_publication(
        report=report, model_json=b'{"artifact_hash":"' + b"b" * 64 + b'"}\n',
        mapping_json=b'{"artifact_hash":"' + b"c" * 64 + b'"}\n',
    )

    assert first == second
    payload = json.loads(first.report_json)
    assert payload["publication"]["report_payload_hash"] == _canonical_hash(report)
    assert payload["publication"]["model_byte_hash"] == hashlib.sha256(first.model_json).hexdigest()
    assert payload["publication"]["mapping_byte_hash"] == hashlib.sha256(first.mapping_json).hexdigest()
    assert payload["publication"]["markdown_byte_hash"] == hashlib.sha256(first.report_markdown).hexdigest()
    assert "json_byte_hash" not in payload["publication"]


def test_six_test_comparisons_use_shared_inputs_and_explicit_adopted_failure() -> None:
    from scripts.chart_regime_strategy_mapping import run_six_three_day_test_comparisons
    from scripts.scheduler_driven_scalping_backtest import PositionExitPolicy

    calls = []
    shared = object()
    def runner(kind):
        def invoke(**kwargs):
            calls.append((kind, kwargs))
            return {"status": "completed", "kind": kind}
        return invoke

    results = run_six_three_day_test_comparisons(
        test_inputs=shared, model=object(), mapping=object(), candidate_manifest=object(),
        global_fixed_candidate=None, candidates=(object(),),
        resolve_current_adopted=lambda: (_ for _ in ()).throw(ValueError("missing adopted")),
        cash_runner=runner("cash"), static_runner=runner("static"),
        dynamic_runner=runner("dynamic"), manual_router_runner=runner("manual"),
        cost_config={"fee": "same"}, initial_equity=Decimal("10000"),
    )

    assert tuple(results) == (
        "cash", "current_adopted_fixed", "pre_test_global_best_fixed",
        "k4_dynamic_entry_owner_exit", "k4_dynamic_active_strategy_opposite_exit",
        "existing_manual_regime_router",
    )
    assert results["current_adopted_fixed"]["status"] == "failed_baseline"
    assert results["pre_test_global_best_fixed"]["status"] == "completed"
    assert [item[1].get("position_exit_policy") for item in calls if item[0] == "dynamic"] == [
        PositionExitPolicy.ENTRY_OWNER_ONLY,
        PositionExitPolicy.ACTIVE_STRATEGY_OPPOSITE,
    ]
    assert all(item[1]["test_inputs"] is shared for item in calls)
    assert all(item[1]["cost_config"] == {"fee": "same"} for item in calls)


def test_main_routes_explicit_three_day_profile_before_weekly_loaders(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    args = SimpleNamespace(
        profile="three-day-daily-k4-v1",
        output_json=Path("a.json"), output_markdown=Path("b.md"),
        output_model=Path("c.json"), output_mapping=Path("d.json"),
    )
    calls = []
    monkeypatch.setattr(module, "parse_walk_forward_args", lambda argv=None: args)
    monkeypatch.setattr(
        module, "run_three_day_profile_main",
        lambda supplied: calls.append(("three-day", supplied)) or 0,
    )
    monkeypatch.setattr(
        module, "load_walk_forward_inputs",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("weekly loader reached")),
    )

    assert module.main([]) == 0
    assert calls == [("three-day", args)]


def test_concrete_dependency_factory_keeps_validation_and_test_lazy(monkeypatch, tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    calls = []
    args = SimpleNamespace(
        symbol="BTCUSDT", raw_kline_root=tmp_path, feature_cache_root=None,
        evidence_rows_path=tmp_path / "evidence.jsonl", resume=True,
        output_json=tmp_path / "r.json", output_markdown=tmp_path / "r.md",
        output_model=tmp_path / "model.json", output_mapping=tmp_path / "mapping.json",
        dry_run=False, manifest_only=False,
    )
    monkeypatch.setattr(
        module, "verify_three_day_experiment_sources",
        lambda a: calls.append("verify") or {},
    )
    monkeypatch.setattr(module, "load_three_day_validation_evidence", lambda *a, **k: calls.append("validation"))
    monkeypatch.setattr(module, "load_three_day_test_inputs", lambda *a, **k: calls.append("test"))

    dependencies = module.build_three_day_experiment_dependencies(args)

    assert calls == []
    dependencies.verify_sources()
    assert calls == ["verify"]


def test_three_day_main_rejects_output_alias_before_any_dependency(monkeypatch, tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    alias = tmp_path / "same.json"
    args = SimpleNamespace(
        profile="three-day-daily-k4-v1",
        output_json=alias, output_markdown=alias,
        output_model=tmp_path / "model.json", output_mapping=tmp_path / "mapping.json",
    )
    calls = []
    monkeypatch.setattr(module, "parse_walk_forward_args", lambda argv=None: args)
    monkeypatch.setattr(module, "run_three_day_profile_main", lambda args: calls.append("dependency"))

    assert module.main([]) == 1
    assert calls == []


def test_three_day_model_gate_failure_publishes_cash_without_test(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    calls = []
    outcome = module.ThreeDayK4FitOutcome("failed-model-cash", None, ("gate",))
    dependencies = module.ThreeDayExperimentDependencies(
        verify_sources=lambda: calls.append("verify") or {},
        fit_and_freeze_model=lambda sources: (_ for _ in ()).throw(module.ThreeDayModelGateFailure(outcome)),
        freeze_candidates=lambda: calls.append("manifest"),
        load_mapping_evidence=lambda **kwargs: calls.append("mapping"),
        build_strict_mapping=lambda **kwargs: calls.append("build"),
        load_validation_evidence=lambda **kwargs: calls.append("validation"),
        report_validation_sensitivity=lambda **kwargs: calls.append("sensitivity"),
        rebuild_final_strict_mapping=lambda **kwargs: calls.append("final"),
        select_global_fixed_baseline=lambda **kwargs: calls.append("baseline"),
        load_test=lambda freeze: calls.append("test"),
        run_test_comparisons=lambda **kwargs: calls.append("comparisons"),
        publish=lambda **kwargs: calls.append("publish"),
    )
    args = SimpleNamespace(dry_run=False, manifest_only=False)
    monkeypatch.setattr(module, "build_three_day_experiment_dependencies", lambda supplied: dependencies)
    monkeypatch.setattr(module, "_publish_model_failure", lambda supplied, failure: calls.append("cash-report"))

    assert module.run_three_day_profile_main(args) == 1
    assert calls == ["verify", "cash-report"]


def test_concrete_model_gate_failure_never_expands_candidate_factories(monkeypatch, tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    args = SimpleNamespace(
        symbol="BTCUSDT", raw_kline_root=tmp_path, feature_cache_root=None,
        evidence_rows_path=tmp_path / "evidence.jsonl", resume=False,
        output_json=tmp_path / "r.json", output_markdown=tmp_path / "r.md",
        output_model=tmp_path / "model.json", output_mapping=tmp_path / "mapping.json",
        dry_run=False, manifest_only=False,
    )
    monkeypatch.setattr(module, "verify_three_day_experiment_sources", lambda args: {})
    monkeypatch.setattr(
        module, "load_and_fit_fold_local_three_day_k4_model",
        lambda **kwargs: module.ThreeDayK4FitOutcome("failed-model-cash", None, ("gate",)),
    )
    monkeypatch.setattr(
        module, "build_three_day_daily_candidate_manifest",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("candidate factory reached")),
    )

    with pytest.raises(module.ThreeDayModelGateFailure):
        module.run_three_day_daily_k4_experiment(
            dependencies=module.build_three_day_experiment_dependencies(args)
        )


def test_three_day_main_composes_concrete_stages_and_publishes_last(monkeypatch, tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    calls = []
    manifest = SimpleNamespace(entries=(object(),) * 459)
    args = SimpleNamespace(
        profile="three-day-daily-k4-v1", symbol="BTCUSDT",
        raw_kline_root=tmp_path, feature_cache_root=None,
        evidence_rows_path=tmp_path / "evidence.jsonl", resume=True,
        output_json=tmp_path / "report.json", output_markdown=tmp_path / "report.md",
        output_model=tmp_path / "model.json", output_mapping=tmp_path / "mapping.json",
        dry_run=False, manifest_only=False,
    )
    monkeypatch.setattr(module, "parse_walk_forward_args", lambda argv=None: args)
    monkeypatch.setattr(
        module, "verify_three_day_experiment_sources",
        lambda supplied: calls.append("verify") or {},
    )
    monkeypatch.setattr(
        module, "build_three_day_daily_candidate_manifest",
        lambda **kwargs: calls.append("candidate-freeze") or manifest,
    )
    monkeypatch.setattr(
        module, "load_and_fit_fold_local_three_day_k4_model",
        lambda **kwargs: calls.append("cluster-fit") or module.ThreeDayK4FitOutcome(
            "model-fit", {"artifact_hash": "a" * 64}
        ),
    )
    monkeypatch.setattr(
        module, "load_three_day_mapping_evidence",
        lambda *args, **kwargs: calls.append("mapping-evidence") or {"ledger_hash": "b" * 64},
    )
    monkeypatch.setattr(
        module, "build_three_day_strict_mapping",
        lambda **kwargs: calls.append("initial-mapping") or {"artifact_hash": "c" * 64},
    )
    monkeypatch.setattr(
        module, "load_three_day_validation_evidence",
        lambda *args, **kwargs: calls.append("validation-evidence") or {"ledger_hash": "d" * 64},
    )
    monkeypatch.setattr(
        module, "report_three_day_validation_sensitivity",
        lambda **kwargs: calls.append("sensitivity") or {"strict": {}},
    )
    monkeypatch.setattr(
        module, "rebuild_three_day_final_mapping",
        lambda **kwargs: calls.append("final-mapping") or {"artifact_hash": "e" * 64},
    )
    monkeypatch.setattr(
        module, "select_three_day_global_baseline",
        lambda **kwargs: calls.append("global-baseline") or {"decision": "cash"},
    )
    def load_test(*args, **kwargs):
        assert "global-baseline" in calls
        calls.append("test-load")
        freeze = args[1]
        return SimpleNamespace(data_provenance=_required_test_provenance(freeze))
    monkeypatch.setattr(module, "load_three_day_test_inputs", load_test)
    monkeypatch.setattr(
        module, "run_concrete_three_day_test_comparisons",
        lambda **kwargs: calls.append("comparisons") or {"cash": {}},
    )
    def publish(supplied, **kwargs):
        assert calls[-1] == "comparisons"
        calls.append("publish")
        supplied.output_json.write_bytes(b"{}")
        return {}
    monkeypatch.setattr(module, "publish_three_day_outputs", publish)

    assert module.main([]) == 0
    assert calls == [
        "verify", "cluster-fit", "candidate-freeze", "mapping-evidence", "initial-mapping",
        "validation-evidence", "sensitivity", "final-mapping", "global-baseline",
        "test-load", "comparisons", "publish",
    ]


def test_adoption_assessment_is_inconclusive_when_required_baseline_failed() -> None:
    from scripts.chart_regime_strategy_mapping import assess_three_day_adoption

    result = assess_three_day_adoption({
        "cash": {"status": "completed", "return_ratio": "0"},
        "current_adopted_fixed": {"status": "failed_baseline"},
        "pre_test_global_best_fixed": {"status": "completed", "return_ratio": "0.01"},
        "k4_dynamic_active_strategy_opposite_exit": {
            "status": "completed", "return_ratio": "0.05", "max_drawdown_ratio": "0.02",
        },
    })

    assert result["status"] == "inconclusive"
    assert result["adopted"] is False
    assert "required_baseline_failed" in result["reasons"]


def test_comparison_audits_publish_independently_recomputable_concentration_and_deltas() -> None:
    from scripts.chart_regime_strategy_mapping import build_three_day_comparison_audits

    primary_trades = [
        {"exit_at": "2026-04-07T01:00:00Z", "net_pnl": "6", "exit_reason": "active_strategy_opposite_signal"},
        {"exit_at": "2026-04-07T02:00:00Z", "net_pnl": "4", "exit_reason": "target"},
        {"exit_at": "2026-04-08T01:00:00Z", "net_pnl": "2", "exit_reason": "active_strategy_opposite_signal"},
        {"exit_at": "2026-04-08T02:00:00Z", "net_pnl": "-1", "exit_reason": "stop"},
    ]
    owner_trades = [
        {"exit_at": "2026-04-07T01:00:00Z", "net_pnl": "3", "exit_reason": "target"},
        {"exit_at": "2026-04-08T01:00:00Z", "net_pnl": "1", "exit_reason": "stop"},
    ]
    comparisons = {
        "k4_dynamic_active_strategy_opposite_exit": {
            "continuous_metrics": {
                "return_ratio": "0.12",
                "portfolio_max_drawdown_ratio": "0.03",
            },
            "trades": primary_trades,
        },
        "k4_dynamic_entry_owner_exit": {
            "continuous_metrics": {
                "return_ratio": "0.08",
                "portfolio_max_drawdown_ratio": "0.02",
            },
            "trades": owner_trades,
        },
    }

    concentration, active_effect = build_three_day_comparison_audits(comparisons)

    from src.domain.regime import decimal_arithmetic_context
    with decimal_arithmetic_context():
        positive_daily_pnl = [Decimal("10"), Decimal("1")]
        expected_top_day_share = max(positive_daily_pnl) / sum(positive_daily_pnl)
        positive_trade_pnl = [Decimal("6"), Decimal("4"), Decimal("2")]
        expected_top_five_share = sum(sorted(positive_trade_pnl, reverse=True)[:5]) / sum(positive_trade_pnl)
    assert Decimal(concentration["top_episode_profit_share"]) == expected_top_day_share
    assert Decimal(concentration["top_day_profit_share"]) == expected_top_day_share
    assert Decimal(concentration["top_five_trade_profit_share"]) == expected_top_five_share
    assert concentration["positive_day_count"] == len(positive_daily_pnl)
    assert concentration["positive_trade_count"] == len(positive_trade_pnl)
    assert Decimal(active_effect["return_ratio_delta"]) == Decimal("0.12") - Decimal("0.08")
    assert Decimal(active_effect["maximum_drawdown_ratio_delta"]) == Decimal("0.03") - Decimal("0.02")
    assert active_effect["trade_count_delta"] == len(primary_trades) - len(owner_trades)
    assert active_effect["active_strategy_opposite_exit_count"] == 2
    assert active_effect["entry_owner_active_strategy_opposite_exit_count"] == 0
    assert active_effect["active_strategy_opposite_exit_count_delta"] == 2


def test_comparison_audit_bytes_ignore_ambient_decimal_precision() -> None:
    from scripts.chart_regime_strategy_mapping import build_three_day_comparison_audits

    comparisons = {
        "k4_dynamic_active_strategy_opposite_exit": {
            "return_ratio": "0.1234567890123456789",
            "max_drawdown_ratio": "0.01234567890123456789",
            "trades": [
                {"exit_at": "2026-04-07T01:00:00Z", "net_pnl": "1", "exit_reason": "target"},
                {"exit_at": "2026-04-08T01:00:00Z", "net_pnl": "2", "exit_reason": "target"},
            ],
        },
        "k4_dynamic_entry_owner_exit": {
            "return_ratio": "0.0234567890123456789",
            "max_drawdown_ratio": "0.00234567890123456789",
            "trades": [],
        },
    }
    serialized = []
    for precision in (6, 28, 50):
        with localcontext() as context:
            context.prec = precision
            serialized.append(json.dumps(
                build_three_day_comparison_audits(comparisons),
                sort_keys=True,
                separators=(",", ":"),
            ))

    assert serialized[0] == serialized[1] == serialized[2]


def test_markdown_binds_weights_by_numeric_index_and_selected_candidate_trade_count() -> None:
    from scripts.chart_regime_strategy_mapping import render_three_day_markdown

    report = {
        "model_artifact": {
            "component_fingerprints": ["a", "z"],
            "numeric_index_to_fingerprint": {"0": "z", "1": "a"},
            "weights": [0.9, 0.1],
            "model_gates": {"distance_threshold": 4.2},
        },
        "strict_mapping": {
            "entries": [
                {"component_fingerprint": "z", "strategy_candidate_id": "selected-z", "rejection_reasons": []},
                {"component_fingerprint": "a", "strategy_candidate_id": "selected-a", "rejection_reasons": []},
            ],
            "candidate_assessments": [
                {"component_fingerprint": "z", "candidate_id": "selected-z", "assigned_day_count": 8, "episode_count": 2, "closed_trade_count": 7, "eligible": True},
                {"component_fingerprint": "z", "candidate_id": "not-selected-z", "assigned_day_count": 8, "episode_count": 2, "closed_trade_count": 99, "eligible": False},
                {"component_fingerprint": "a", "candidate_id": "selected-a", "assigned_day_count": 5, "episode_count": 1, "closed_trade_count": 3, "eligible": True},
            ],
        },
        "validation_sensitivity": {},
        "test_comparisons": {},
    }

    markdown = render_three_day_markdown(report)

    z_line = next(line for line in markdown.splitlines() if line.startswith("- `z`:"))
    a_line = next(line for line in markdown.splitlines() if line.startswith("- `a`:"))
    assert "weight=0.9" in z_line
    assert "weight=0.1" in a_line
    assert "selected=selected-z" in z_line
    assert "closed_trades=7" in z_line
    assert "closed_trades=106" not in z_line


def test_phase_evidence_payload_embeds_rows_assignments_and_recomputable_hash() -> None:
    from scripts.chart_regime_strategy_mapping import ThreeDayPhaseEvidence

    day = datetime(2025, 7, 7, tzinfo=timezone.utc)
    row_payload = {
        "candidate_id": "candidate-a",
        "outcome_start_at": "2025-07-07T00:00:00Z",
        "daily_return_ratio": "0.01",
        "closed_trade_count": 3,
    }
    row = SimpleNamespace(
        outcome_start_at=day,
        candidate_id="candidate-a",
        availability_status="available",
        canonical_payload=lambda: row_payload,
    )
    identity = SimpleNamespace(
        canonical_payload=lambda: {"code_version": "test"}, digest="1" * 64,
        feature_provenance_hash=_canonical_hash({"provider": "cache-a"}),
        feature_source_coverage_hash=_canonical_hash({"coverage": 1}),
        feature_unavailable_counts_hash=_canonical_hash({"missing": 0}),
    )
    archives = ({
        "source_url": "https://example.invalid/archive.zip",
        "member_name": "BTCUSDT-1m.csv",
        "byte_count": 123,
        "sha256": "3" * 64,
    },)
    vector_provenance = ({
        "url": "https://example.invalid/vector.zip",
        "member_identity": "member-v1",
        "bytes": 456,
        "sha256": "4" * 64,
    },)
    evidence = ThreeDayPhaseEvidence(
        phase="mapping_fit",
        rows=(row,),
        calendar=(day,),
        assignments=("component-a",),
        run_identity=identity,
        ledger_path=Path("mapping.jsonl"),
        ledger_hash="2" * 64,
        archive_descriptors=archives,
        vector_provenance=vector_provenance,
        feature_provenance={"provider": "cache-a"},
        feature_source_coverage={"coverage": 1},
        feature_unavailable_counts={"missing": 0},
    )

    payload = evidence.canonical_payload()

    assert payload["daily_evidence_rows"] == [row_payload]
    assert payload["component_assignments"] == ["component-a"]
    assert payload["calendar_rows"] == [{
        "outcome_start_at": "2025-07-07T00:00:00Z",
        "component_fingerprint": "component-a",
        "role": "mapping_fit",
    }]
    assert payload["assignment_hash"] == _canonical_hash(payload["component_assignments"])
    assert payload["archive_descriptors"] == list(archives)
    assert payload["archive_descriptor_hash"] == _canonical_hash(list(archives))
    assert payload["vector_provenance"] == list(vector_provenance)
    assert payload["vector_provenance_hash"] == _canonical_hash(list(vector_provenance))
    assert payload["feature_provenance_hash"] == _canonical_hash(payload["feature_provenance"])
    independently_reconstructed = [
        row["component_fingerprint"] for row in payload["calendar_rows"]
    ]
    assert independently_reconstructed == payload["component_assignments"]


def _empty_phase_evidence(*, identity_hash: str, archive_descriptors=()):
    from scripts.chart_regime_strategy_mapping import ThreeDayPhaseEvidence

    identity = SimpleNamespace(
        canonical_payload=lambda: {}, digest="1" * 64,
        feature_provenance_hash=identity_hash,
        feature_source_coverage_hash=identity_hash,
        feature_unavailable_counts_hash=identity_hash,
    )
    return ThreeDayPhaseEvidence(
        phase="mapping_fit", rows=(), calendar=(), assignments=(),
        run_identity=identity, ledger_path=Path("mapping.jsonl"),
        ledger_hash="2" * 64, archive_descriptors=archive_descriptors,
        feature_provenance={}, feature_source_coverage={},
        feature_unavailable_counts={},
    )


def test_empty_phase_provenance_still_requires_exact_identity_hash() -> None:
    with pytest.raises(ValueError, match="feature_provenance_hash"):
        _empty_phase_evidence(identity_hash="f" * 64)


def test_empty_phase_provenance_accepts_canonical_empty_hash() -> None:
    evidence = _empty_phase_evidence(identity_hash=_canonical_hash({}))

    assert evidence.canonical_payload()["feature_provenance_hash"] == _canonical_hash({})


@pytest.mark.parametrize("descriptor", (
    {"source_url": "", "member_name": "data.csv", "byte_count": 1, "sha256": "a" * 64},
    {"source_url": "not-a-url", "member_name": "data.csv", "byte_count": 1, "sha256": "a" * 64},
    {"source_url": "https://example.com/a.zip", "member_name": "", "byte_count": 1, "sha256": "a" * 64},
    {"source_url": "https://example.com/a.zip", "member_name": "data.csv", "byte_count": -1, "sha256": "a" * 64},
    {"source_url": "https://example.com/a.zip", "member_name": "data.csv", "byte_count": "1", "sha256": "a" * 64},
    {"source_url": "https://example.com/a.zip", "member_name": "data.csv", "byte_count": True, "sha256": "a" * 64},
    {"source_url": "https://example.com/a.zip", "member_name": "data.csv", "byte_count": 1, "sha256": "A" * 64},
    {"source_url": "https://example.com/a.zip", "member_name": "data.csv", "byte_count": 1, "sha256": "short"},
))
def test_phase_archive_descriptor_rejects_unverifiable_fields(descriptor) -> None:
    with pytest.raises(ValueError, match="archive descriptor"):
        _empty_phase_evidence(
            identity_hash=_canonical_hash({}), archive_descriptors=(descriptor,)
        )


def test_canonical_report_reuses_large_already_canonical_daily_grid() -> None:
    from scripts.chart_regime_strategy_mapping import _canonicalize_report

    rows = [
        {
            "candidate_id": f"candidate-{candidate:03d}",
            "day_index": day,
            "net_return_ratio": "0.001",
        }
        for day in range(265)
        for candidate in range(459)
    ]
    report = {"daily_evidence_rows": rows, "schema_version": "memory-regression-v1"}

    normalized = _canonicalize_report(report)

    assert normalized is report
    assert normalized["daily_evidence_rows"] is rows
    assert len(json.dumps(normalized, separators=(",", ":"))) < 12_000_000


def test_all_eight_walk_forward_fold_dates_are_accepted() -> None:
    args = parse_walk_forward_args([
        "--symbol", "BTCUSDT",
        "--cluster-fit-start", "2021-01-01", "--cluster-fit-end", "2025-06-30",
        "--mapping-fit-start", "2025-07-07", "--mapping-fit-end", "2026-01-05",
        "--validation-start", "2026-01-12", "--validation-end", "2026-03-30",
        "--test-start", "2026-04-06", "--test-end", "2026-07-01",
        "--output-json", "report.json", "--output-markdown", "report.md",
    ])
    assert args.test_end == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_diagnostic_test_claim_requires_complete_prior_exposure_audit() -> None:
    common = [
        "--symbol", "BTCUSDT", "--output-json", "report.json",
        "--output-markdown", "report.md",
        "--test-claim-status", "diagnostic_after_pipeline_defect",
    ]
    with pytest.raises(SystemExit):
        parse_walk_forward_args(common)
    args = parse_walk_forward_args(common + [
        "--test-claim-reason", "pre-Test extractor denominator defect",
        "--prior-run-timestamp", "2026-07-15T12:34:56+00:00",
        "--prior-run-hash", "a" * 64,
    ])
    assert args.test_claim_status == "diagnostic_after_pipeline_defect"
    assert args.prior_run_hash == "a" * 64


def test_diagnostic_test_claim_is_surfaced_separately_from_structural_freeze() -> None:
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"),),
        dependencies=_fixture_walk_forward_dependencies(),
        test_claim_status="diagnostic_after_pipeline_defect",
        test_claim_reason="pre-Test extractor denominator defect",
        prior_run_timestamp="2026-07-15T12:34:56+00:00",
        prior_run_hash="b" * 64,
    )
    audit = payload["leakage_audit"]
    assert audit["frozen_before_test"] is True
    assert audit["confirmatory_status"] == "diagnostic_after_pipeline_defect"
    assert audit["thresholds_changed_after_prior_exposure"] is False
    assert audit["configuration_grid_changed_after_prior_exposure"] is False


def test_real_feature_cache_selection_reads_manifests_only() -> None:
    import scripts.chart_regime_strategy_mapping as module

    root = Path(__file__).resolve().parents[1] / ".research-data/binance-usdm/features/BTCUSDT/1m"
    if not root.exists():
        pytest.skip("workspace feature cache is not present")
    plan = module.plan_feature_caches(
        root,
        required_start=datetime(2025, 7, 7, tzinfo=timezone.utc),
        required_end=datetime(2026, 3, 30, tzinfo=timezone.utc),
    )
    assert plan is not None
    assert {source for shard in plan.shards for source in shard.sources} >= {
        "fundingRate", "metrics",
    }
    assert len(plan.shards) == 2


def test_archive_parser_stops_before_parsing_rows_at_access_boundary(tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    boundary = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
    archive = tmp_path / "BTCUSDT-1m.zip"
    first_ms = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    boundary_ms = int(boundary.timestamp() * 1000)
    with zipfile.ZipFile(archive, "w") as stream:
        stream.writestr(
            "rows.csv",
            f"{first_ms},1,1,1,1,1\n{boundary_ms},not-a-price,2,0,1,1\n",
        )
    rows = tuple(module._archive_candles(archive, "BTCUSDT", end_at=boundary))
    assert len(rows) == 1


def _write_feature_shard(root: Path, suffix: str, feature_value: str, extra_name: str) -> Path:
    start = "2026-01-01T00:00:00+00:00"
    end = "2026-01-01T00:01:00+00:00"
    stem = f"tiny-{suffix}"
    row = {
        "symbol": "BTCUSDT", "timeframe": "1m", "measured_at": end,
        "unavailable_sources": [],
        "features": {
            "close": {"value": feature_value, "source": "klines", "observed_at": end, "available_at": end},
            extra_name: {"value": "2", "source": suffix, "observed_at": end, "available_at": end},
        },
    }
    cache = root / f"{stem}.jsonl"
    cache.write_text(json.dumps(row) + "\n", encoding="utf-8")
    manifest = {
        "symbol": "BTCUSDT", "timeframe": "1m", "row_count": 1,
        "output_hash": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "cache_identity_hash": hashlib.sha256(stem.encode()).hexdigest(),
        "input_hashes": {}, "raw_hashes": {},
        "cache_identity": {
            "schema_version": "binance-usdm-market-features-v1",
            "start": start, "end": end, "sources": ["klines", suffix],
        },
        "source_coverage": {"klines": {"available_rows": 1}, suffix: {"available_rows": 1}},
        "provenance": {"fixture": suffix},
    }
    (root / f"{stem}.manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return cache


def _write_multi_feature_shard(root: Path, values: list[str], suffix: str = "metrics") -> tuple[Path, Path]:
    start_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index, value in enumerate(values, start=1):
        measured_at = (start_at + timedelta(minutes=index)).isoformat()
        rows.append({
            "symbol": "BTCUSDT", "timeframe": "1m", "measured_at": measured_at,
            "unavailable_sources": [],
            "features": {
                "open_interest": {
                    "value": value, "source": suffix,
                    "observed_at": measured_at, "available_at": measured_at,
                },
            },
        })
    cache = root / f"multi-{suffix}.jsonl"
    cache.write_bytes(b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows))
    manifest_path = root / f"multi-{suffix}.manifest.json"
    manifest = {
        "symbol": "BTCUSDT", "timeframe": "1m", "row_count": len(rows),
        "output_hash": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "cache_identity_hash": "a" * 64, "input_hashes": {}, "raw_hashes": {},
        "cache_identity": {
            "schema_version": "binance-usdm-market-features-v1",
            "start": start_at.isoformat(),
            "end": (start_at + timedelta(minutes=len(rows))).isoformat(),
            "sources": [suffix],
        },
        "source_coverage": {suffix: {"available_rows": len(rows)}},
        "provenance": {"fixture": suffix},
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return cache, manifest_path


def test_pretest_feature_identity_excludes_test_only_rows(tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    cache, manifest_path = _write_multi_feature_shard(tmp_path, ["1", "2", "3"])
    bounds = {
        "required_start": datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        "required_end": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
    }
    first = module.IndexedCompositeFeatureProvider(module.plan_feature_caches(tmp_path, **bounds))
    first_identity = (first.feature_cache_hash, first.feature_config_hash, first.feature_provenance)
    assert next(iter(first.feature_read_audit.values()))["indexed_row_count"] == 2
    assert "output_hash" not in next(iter(first.feature_provenance.values()))
    first.close()

    lines = cache.read_text(encoding="utf-8").splitlines()
    changed = json.loads(lines[2])
    changed["features"]["open_interest"]["value"] = "999"
    lines[2] = json.dumps(changed, sort_keys=True)
    cache.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_hash"] = hashlib.sha256(cache.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    second = module.IndexedCompositeFeatureProvider(module.plan_feature_caches(tmp_path, **bounds))
    assert (second.feature_cache_hash, second.feature_config_hash, second.feature_provenance) == first_identity
    second.close()


def test_feature_index_rejects_tamper_with_unchanged_line_count(tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    cache, _ = _write_multi_feature_shard(tmp_path, ["1", "2", "3"])
    plan = module.plan_feature_caches(
        tmp_path,
        required_start=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        required_end=datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
    )
    data = cache.read_bytes().replace(b'"value": "2"', b'"value": "9"')
    cache.write_bytes(data)
    with pytest.raises(ValueError, match="output hash"):
        module.IndexedCompositeFeatureProvider(plan)


def test_post_freeze_provider_full_verifies_beyond_test_slice(tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    cache, _ = _write_multi_feature_shard(tmp_path, ["1", "2", "3"])
    bounds = {
        "required_start": datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        "required_end": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
    }
    pretest = module.IndexedCompositeFeatureProvider(module.plan_feature_caches(tmp_path, **bounds))
    pretest.close()
    cache.write_bytes(cache.read_bytes().replace(b'"value": "3"', b'"value": "8"'))

    # Access-bounded pre-Test construction never reads the changed third row.
    bounded = module.IndexedCompositeFeatureProvider(module.plan_feature_caches(tmp_path, **bounds))
    assert next(iter(bounded.feature_read_audit.values()))["indexed_row_count"] == 2
    bounded.close()
    # Post-freeze Test construction authenticates the complete selected shard.
    verified_plan = module.plan_feature_caches(tmp_path, **bounds, verify_full_file=True)
    with pytest.raises(ValueError, match="output hash"):
        module.IndexedCompositeFeatureProvider(verified_plan)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        ("measured_at", "2026-01-01T00:01:00+00:00", "strict increasing"),
        ("symbol", "ETHUSDT", "row identity"),
    ),
)
def test_full_feature_index_validates_row_timeline_and_identity(
    tmp_path, field, replacement, message
) -> None:
    import scripts.chart_regime_strategy_mapping as module

    cache, manifest_path = _write_multi_feature_shard(tmp_path, ["1", "2", "3"])
    lines = cache.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[1])
    row[field] = replacement
    lines[1] = json.dumps(row, sort_keys=True)
    cache.write_bytes(("\n".join(lines) + "\n").encode())
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_hash"] = hashlib.sha256(cache.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    plan = module.plan_feature_caches(
        tmp_path,
        required_start=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        required_end=datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
        verify_full_file=True,
    )
    with pytest.raises(ValueError, match=message):
        module.IndexedCompositeFeatureProvider(plan)


def test_full_feature_index_rejects_extra_row_even_with_matching_raw_hash(tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    cache, manifest_path = _write_multi_feature_shard(tmp_path, ["1", "2", "3"])
    cache.write_bytes(cache.read_bytes() + cache.read_bytes().splitlines(keepends=True)[-1])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_hash"] = hashlib.sha256(cache.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    plan = module.plan_feature_caches(
        tmp_path,
        required_start=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        required_end=datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
        verify_full_file=True,
    )
    with pytest.raises(ValueError, match="row count"):
        module.IndexedCompositeFeatureProvider(plan)


def test_feature_provider_opens_each_shard_once_and_reuses_parsed_rows(monkeypatch, tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    _write_multi_feature_shard(tmp_path, ["1", "2", "3"])
    plan = module.plan_feature_caches(
        tmp_path,
        required_start=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        required_end=datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
    )
    real_open = Path.open
    opened = []

    def tracked_open(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            opened.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked_open)
    provider = module.IndexedCompositeFeatureProvider(plan)
    when = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    first = provider.load_features(Symbol("BTC", "USDT"), Timeframe(1, "m"), when)
    for _ in range(1_000):
        assert provider.load_features(Symbol("BTC", "USDT"), Timeframe(1, "m"), when) is first
    assert len(opened) == len(plan.shards)
    provider.close()


def test_feature_provider_keeps_complete_weekly_episode_hot(tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    episode_rows = 7 * 24 * 60
    _write_multi_feature_shard(tmp_path, ["1"] * episode_rows)
    plan = module.plan_feature_caches(
        tmp_path,
        required_start=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        required_end=datetime(2026, 1, 8, tzinfo=timezone.utc),
    )
    provider = module.IndexedCompositeFeatureProvider(plan)
    symbol, timeframe = Symbol("BTC", "USDT"), Timeframe(1, "m")
    first_pass = [
        provider.load_features(
            symbol, timeframe, datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
        )
        for index in range(1, episode_rows + 1)
    ]
    second_pass = [
        provider.load_features(
            symbol, timeframe, datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
        )
        for index in range(1, episode_rows + 1)
    ]
    assert all(first is second for first, second in zip(first_pass, second_pass, strict=True))
    provider.close()


def test_feature_index_reports_bounded_progress(tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    _write_multi_feature_shard(tmp_path, ["1", "2", "3"])
    plan = module.plan_feature_caches(
        tmp_path,
        required_start=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        required_end=datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
    )
    events = []
    provider = module.IndexedCompositeFeatureProvider(plan, progress=events.append)
    assert events[0].startswith("feature_cache_index_started:shard_00:")
    assert events[-1].startswith("feature_cache_index_completed:shard_00:")
    provider.close()


def test_complementary_feature_caches_merge_identical_overlap(tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    _write_feature_shard(tmp_path, "metrics", "1", "open_interest")
    _write_feature_shard(tmp_path, "fundingRate", "1", "funding_rate")
    plan = module.plan_feature_caches(
        tmp_path,
        required_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        required_end=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    result = module.IndexedCompositeFeatureProvider(plan).load_features(
        Symbol("BTC", "USDT"), Timeframe(1, "m"),
        datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert {value.name for value in result.values} == {"close", "funding_rate", "open_interest"}


def test_complementary_feature_caches_fail_closed_on_conflict(tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    _write_feature_shard(tmp_path, "metrics", "1", "open_interest")
    _write_feature_shard(tmp_path, "fundingRate", "9", "funding_rate")
    plan = module.plan_feature_caches(
        tmp_path,
        required_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        required_end=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="conflicting feature cache value"):
        module.IndexedCompositeFeatureProvider(plan).load_features(
            Symbol("BTC", "USDT"), Timeframe(1, "m"),
            datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        )


def test_gmm_bic_counts_diag_and_tied_parameters_exactly() -> None:
    # weights + means + covariance parameters
    assert _gmm_parameter_count(3, 4, "diag") == 2 + 12 + 12
    assert _gmm_parameter_count(3, 4, "tied") == 2 + 12 + 10
    assert _gmm_bic(-100.0, 50, 24) == pytest.approx(200 + 24 * __import__("math").log(50))


def test_numeric_metric_bound_normalizes_only_machine_scale_roundoff() -> None:
    normalized, audit = _normalize_bounded_metric(1.0 + 5e-16, "seed_nmi", 0.0, 1.0)
    assert normalized == 1.0
    assert audit == {"raw": 1.0 + 5e-16, "normalized": 1.0, "clamped": True}
    with pytest.raises(ValueError, match="seed_nmi.*outside"):
        _normalize_bounded_metric(1.0 + 1e-8, "seed_nmi", 0.0, 1.0)


def test_fixed_diagnostics_reconstruct_and_verify_round_trip_turnover() -> None:
    turnover = Decimal("2") * (Decimal("100") + Decimal("110"))
    comparisons = {
        "adopted_fixed": {
            "status": "ok",
            "continuous_metrics": {
                "trade_count": 1,
                "trades": [{
                    "quantity": "2", "entry_price": "100", "exit_price": "110",
                    "fee_paid": str(turnover * FEE_RATE), "net_pnl": "1",
                }],
            },
        },
        "manual_regime_router": {
            "status": "ok",
            "continuous_metrics": {"trade_count": 0, "trades": []},
        },
    }
    diagnostics = _continuous_diagnostics(comparisons, test_minutes=100)
    fixed = diagnostics["adopted_fixed"]
    assert fixed["actual_turnover_notional"] == {
        "availability": "measured",
        "value": "420",
        "source": "reconstructed_trade_legs",
        "convention": "sum(quantity * (entry_price + exit_price))",
    }
    assert fixed["confidence"]["availability"] == "not_applicable"
    assert fixed["transitions"]["counts"] is None
    manual = diagnostics["manual_regime_router"]
    assert manual["actual_turnover_notional"]["availability"] == "measured"
    assert manual["actual_turnover_notional"]["value"] == "0"
    assert manual["confidence"]["availability"] == "not_applicable"

    comparisons["adopted_fixed"]["continuous_metrics"]["trades"][0]["fee_paid"] = "0"
    with pytest.raises(ValueError, match="fee_paid.*turnover"):
        _continuous_diagnostics(comparisons, test_minutes=100)


def test_fixed_diagnostics_reject_trade_count_without_trade_ledger() -> None:
    with pytest.raises(ValueError, match="trade_count.*trade ledger"):
        _continuous_diagnostics(
            {
                "adopted_fixed": {
                    "status": "ok",
                    "continuous_metrics": {"trade_count": 1, "trades": []},
                },
            },
            test_minutes=100,
        )


def test_cash_and_unavailable_diagnostic_availability_is_explicit() -> None:
    diagnostics = _continuous_diagnostics(
        {
            "cash": {"status": "cash", "continuous_metrics": {}},
            "train_selected_fixed": {
                "status": "cash",
                "rejection_reasons": ["not evaluated: no eligible model"],
                "continuous_metrics": {},
            },
            "kmeans_dynamic": {
                "status": "cash",
                "rejection_reasons": ["no frozen eligible artifact"],
                "continuous_metrics": {},
            },
        },
        test_minutes=123,
    )
    cash = diagnostics["cash"]
    assert cash["availability"] == "measured"
    assert cash["cash_contribution"] == {
        "availability": "measured", "cash_bars": 123,
        "cash_bar_share": "1", "entries_while_cash": 0,
    }
    assert cash["actual_turnover_notional"]["value"] == "0"
    for name in ("train_selected_fixed", "kmeans_dynamic"):
        item = diagnostics[name]
        assert item["availability"] == "not_evaluated"
        assert item["actual_turnover_notional"]["value"] is None
        assert item["confidence"]["diagnostics"] is None
        assert item["transitions"]["counts"] is None
        assert item["reason"]


def test_validation_replay_metrics_require_canonical_finite_schema() -> None:
    import scripts.chart_regime_strategy_mapping as module

    assert module._validation_replay_metrics({
        "return_ratio": "-0.1",
        "portfolio_max_drawdown_ratio": "0.2",
        "actual_turnover_notional": "300",
    }) == (Decimal("-0.1"), Decimal("0.2"), Decimal("300"))

    invalid = (
        ({"return_ratio": "0", "portfolio_max_drawdown_ratio": "0"}, "actual_turnover_notional"),
        ({"return_ratio": "0", "max_drawdown_ratio": "0", "turnover": "0"}, "portfolio_max_drawdown_ratio"),
        ({"return_ratio": "NaN", "portfolio_max_drawdown_ratio": "0", "actual_turnover_notional": "0"}, "return_ratio"),
        ({"return_ratio": "0", "portfolio_max_drawdown_ratio": "-0.1", "actual_turnover_notional": "0"}, "portfolio_max_drawdown_ratio"),
        ({"return_ratio": "0", "portfolio_max_drawdown_ratio": "0", "actual_turnover_notional": "-1"}, "actual_turnover_notional"),
    )
    for replay, field in invalid:
        with pytest.raises(ValueError, match=field):
            module._validation_replay_metrics(replay)


def test_manual_router_is_a_distinct_public_factory_candidate() -> None:
    from scripts.scheduler_driven_scalping_backtest import default_candidate

    manual = _manual_router_candidate()
    assert manual.candidate_id == "range-first-p2-tp0060-sl0045-e0035-l3-guard-a"
    assert [spec.kind for spec in manual.strategies] == ["regime_router"]
    assert manual != default_candidate()
    unavailable, reason = _manual_router_for_replay(include_deferred=False)
    opted_in, opted_in_reason = _manual_router_for_replay(include_deferred=True)
    assert unavailable is None and "deferred" in reason
    assert opted_in == manual and opted_in_reason is None


def test_manual_router_without_deferred_opt_in_is_reported_unavailable(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    calls = []
    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda *args, **kwargs: calls.append(kwargs) or {
            "return_ratio": "0", "max_drawdown_ratio": "0", "trade_count": 0
        },
    )
    result = _default_replay_test(
        {
            "test": BTCUSDT_FIRST_FOLD.test,
            "candidates": (_candidate("candidate-a"),),
            "include_deferred": False,
        },
        {"market": _minute_market(BTCUSDT_FIRST_FOLD.mapping_fit.start_at, 1), "provider": None},
        {}, {"_artifacts": {}}, {"_artifacts": {}}, {},
    )
    assert result["manual_regime_router"]["status"] == "unavailable"
    assert "deferred" in result["manual_regime_router"]["rejection_reasons"][0]
    assert all(
        call["candidate"].candidate_id != "range-first-p2-tp0060-sl0045-e0035-l3-guard-a"
        for call in calls
    )


def test_mapping_feature_coverage_rejects_partial_point_in_time_episode() -> None:
    from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episode = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    candidate = SchedulerBacktestCandidate(
        candidate_id="flow",
        strategies=(StrategyCandidateSpec("flow_breakout", {}),),
        take_profit_ratio=Decimal("0.01"), stop_loss_ratio=Decimal("0.01"),
        equity_ratio=Decimal("0.1"), leverage=Decimal("2"), candle_limit=1,
    )

    class PartialProvider:
        def load_features(self, symbol, timeframe, as_of):
            values = () if as_of >= start + timedelta(days=3) else tuple(
                MarketFeatureValue(name, Decimal("1"), source, as_of, as_of)
                for name, source in (
                    ("taker_imbalance", "aggTrades"),
                    ("cvd_delta", "aggTrades"),
                    ("trade_intensity", "aggTrades"),
                )
            )
            return MarketFeatureSet(symbol, timeframe, as_of, values)

    valid, report = _mapping_feature_coverage(
        _minute_market(start, 1, warmup_minutes=0), episode, (candidate,), PartialProvider()
    )
    assert valid["flow"] == set()
    assert report["flow"]["eligible_episode_count"] == 0
    assert report["flow"]["episodes"][0]["available_minutes"] < 10080
    assert "missing point-in-time alternatives" in report["flow"]["episodes"][0]["rejection_reason"]


def test_premium_strategy_accepts_either_premium_or_complete_basis_alternative() -> None:
    from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    market = _minute_market(start, 1, warmup_minutes=0)
    candidate = SchedulerBacktestCandidate(
        candidate_id="premium",
        strategies=(StrategyCandidateSpec("premium_funding", {}),),
        take_profit_ratio=Decimal("0.01"), stop_loss_ratio=Decimal("0.01"),
        equity_ratio=Decimal("0.1"), leverage=Decimal("2"), candle_limit=1,
    )

    class Provider:
        def __init__(self, extra):
            self.extra = extra

        def load_features(self, symbol, timeframe, as_of):
            fields = {
                "taker_imbalance": "aggTrades",
                "cvd_delta": "aggTrades",
                **self.extra,
            }
            return MarketFeatureSet(
                symbol, timeframe, as_of,
                tuple(MarketFeatureValue(name, Decimal("1"), source, as_of, as_of) for name, source in fields.items()),
            )

    premium_valid, _ = _mapping_feature_coverage(
        market, episodes, (candidate,), Provider({"premium_index": "premiumIndexKlines"})
    )
    basis_valid, _ = _mapping_feature_coverage(
        market, episodes, (candidate,), Provider({"mark_price": "markPriceKlines", "index_price": "indexPriceKlines"})
    )
    incomplete, report = _mapping_feature_coverage(
        market, episodes, (candidate,), Provider({"mark_price": "markPriceKlines"})
    )
    assert premium_valid["premium"] == {start}
    assert basis_valid["premium"] == {start}
    assert incomplete["premium"] == set()
    assert "premium_index" in report["premium"]["episodes"][0]["rejection_reason"]
    assert "index_price" in report["premium"]["episodes"][0]["rejection_reason"]


def test_coverage_invalid_candidates_are_never_backtested(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=14)))
    valid_candidate, invalid_candidate = _candidate("valid"), _candidate("invalid")
    calls = []

    def capture(_market, *, candidates, episodes, **_kwargs):
        calls.append(([item.candidate_id for item in candidates], episodes[0].start_at))
        return []

    monkeypatch.setattr(module, "run_mapping_episodes", capture)
    rows = _run_mapping_coverage_filtered_evidence(
        _minute_market(start, 2, warmup_minutes=0),
        episodes=episodes,
        assignments={episode.anchor_at: "cluster" for episode in episodes},
        candidates=(valid_candidate, invalid_candidate),
        valid_episodes={"valid": {episodes[0].start_at}, "invalid": set()},
        market_feature_provider=None,
    )
    assert rows == []
    assert calls == [(["valid"], episodes[0].start_at)]


def _fixture_walk_forward_dependencies(test_return: str = "0.01"):
    def prepare(context):
        return {"provenance": {"archives": [{"sha256": "a" * 64}]}}

    def features(context, prepared):
        return {"schema": "btc-chart-regime-ohclv-v1", "vectors": [1, 2, 3]}

    def models(context, features):
        return {
            "selected": {"kmeans": {"artifact_hash": "b" * 64}, "gmm": {"artifact_hash": "c" * 64}},
            "candidates": [{"config_id": "bad", "eligible": False, "rejection_reasons": ["unstable"]}],
        }

    def mappings(context, prepared, features, models):
        return {
            "selected": {"kmeans": {"artifact_hash": "d" * 64}, "gmm": {"artifact_hash": "e" * 64}},
            "mapping_metrics": {"weekly_episode_count": 8},
        }

    def validation(context, prepared, features, models, mappings):
        return {"score": "0.02", "selected_family": "kmeans"}

    def test(context, prepared, features, models, mappings, validation):
        callback = context.get("on_test_selector_invoked")
        if callable(callback):
            callback("fixture")
        return {
            name: {"status": "cash" if name == "cash" else "ok", "continuous_metrics": {"return_ratio": test_return}}
            for name in ("cash", "adopted_fixed", "train_selected_fixed", "manual_regime_router", "kmeans_dynamic", "gmm_dynamic")
        }

    return WalkForwardDependencies(prepare, features, models, mappings, validation, test)


def test_walk_forward_freezes_artifacts_before_test_and_has_required_baselines() -> None:
    events = []
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"),),
        dependencies=_fixture_walk_forward_dependencies(),
        progress=events.append,
    )
    assert events.index("mapping_frozen") < events.index("first_test_classification")
    assert "test_result" not in events[:events.index("mapping_frozen")]
    assert set(payload["comparisons"]) == {
        "cash", "adopted_fixed", "train_selected_fixed", "manual_regime_router",
        "kmeans_dynamic", "gmm_dynamic",
    }
    assert payload["leakage_audit"]["frozen_before_test"] is True
    assert {access["stage"] for access in payload["data_access_audit"] if access["interval"] == "test"} == {
        "test_result", "test_selector_invoked",
    }


def test_test_inputs_are_loaded_once_and_only_after_mapping_freeze() -> None:
    import scripts.chart_regime_strategy_mapping as module

    events = []
    calls = []

    class Provider:
        closed = False

        def close(self):
            self.closed = True

    provider = Provider()

    def load_test():
        calls.append(tuple(events))
        return module.TestReplayInputs(
            market=_minute_market(BTCUSDT_FIRST_FOLD.test.start_at - timedelta(days=7), 8),
            data_provenance={"fixture": "test-only"},
            market_feature_provider=provider,
        )

    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"),),
        dependencies=_fixture_walk_forward_dependencies(),
        progress=events.append,
        test_input_loader=load_test,
    )
    assert len(calls) == 1
    assert provider.closed is True
    assert "mapping_frozen" in calls[0]
    assert "first_test_classification" not in calls[0]
    assert events.index("test_data_prepared") < events.index("first_test_classification")
    assert {item["stage"] for item in payload["data_access_audit"] if item["interval"] == "test"} == {
        "test_data_loaded", "test_result", "test_selector_invoked",
    }


def test_cash_only_run_writes_reports_and_explicit_artifact_envelopes(tmp_path) -> None:
    paths = {
        "output_json": tmp_path / "result.json",
        "output_markdown": tmp_path / "result.md",
        "output_model": tmp_path / "result-model.json",
        "output_mapping": tmp_path / "result-mapping.json",
    }
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"),),
        dependencies=_fixture_walk_forward_dependencies(),
        **paths,
    )
    assert payload["artifact_outputs"]["status"] == "cash_only"
    assert all(path.is_file() for path in paths.values())
    for key in ("output_model", "output_mapping"):
        envelope = json.loads(paths[key].read_text(encoding="utf-8"))
        assert envelope["kind"] == "cash_only"
        assert envelope["artifact_hash"]


def test_main_closes_pretest_feature_provider(monkeypatch, tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    class Provider:
        closed = False

        def close(self):
            self.closed = True

    provider = Provider()
    args = SimpleNamespace(
        symbol="BTCUSDT", candidate_group=["all"], include_deferred=False,
        raw_kline_root=tmp_path, feature_cache_root=tmp_path,
        output_json=tmp_path / "result.json", output_markdown=tmp_path / "result.md",
        output_model=tmp_path / "model.json", output_mapping=tmp_path / "mapping.json",
        test_claim_status="untouched", test_claim_reason=None,
        prior_run_timestamp=None, prior_run_hash=None,
        **{name: None for name in (
            "cluster_fit_start", "cluster_fit_end", "mapping_fit_start", "mapping_fit_end",
            "validation_start", "validation_end", "test_start", "test_end",
        )},
    )
    inputs = WalkForwardInputs(
        market=_minute_market(BTCUSDT_FIRST_FOLD.mapping_fit.start_at, 1),
        cluster_fit_vectors=(), mapping_vectors=(), validation_vectors=(),
        data_provenance={}, market_feature_provider=provider,
    )
    monkeypatch.setattr(module, "parse_walk_forward_args", lambda _argv: args)
    monkeypatch.setattr(module, "_resolve_walk_forward_candidates", lambda **_kwargs: ((_candidate("a"),), {}))
    monkeypatch.setattr(module, "load_walk_forward_inputs", lambda *_args, **_kwargs: inputs)
    monkeypatch.setattr(module, "run_chart_regime_walk_forward", lambda *_args, **_kwargs: {})
    assert module.main([]) == 0
    assert provider.closed is True


def test_walk_forward_report_records_grid_provenance_and_rejections() -> None:
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"),),
        dependencies=_fixture_walk_forward_dependencies(),
    )
    assert payload["feature_schema_version"] == "btc-chart-regime-ohclv-v1"
    assert payload["candidate_universe_hash"]
    assert payload["candidate_definition_hash"]
    assert payload["data_provenance"]
    assert payload["rejected_model_configurations"][0]["config_id"] == "bad"
    assert payload["configuration_grid"]["cluster_counts"] == [3, 4, 5, 6, 7, 8]


def test_serialized_candidate_behavior_payloads_self_verify_hashes() -> None:
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"), _candidate("candidate-b", equity_ratio="0.2")),
        dependencies=_fixture_walk_forward_dependencies(),
    )
    for candidate_id, behavior in payload["candidate_behaviors"].items():
        assert _canonical_hash(behavior) == payload["candidate_behavior_hashes"][candidate_id]


def test_cash_only_replay_does_not_claim_first_dynamic_selector() -> None:
    dependencies = replace(
        _fixture_walk_forward_dependencies(),
        replay_test=lambda *_args: {},
    )
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"),),
        dependencies=dependencies,
    )
    assert "first_test_classification" not in payload["pipeline_events"]
    assert "test_selector_not_reached" in payload["pipeline_events"]
    assert payload["leakage_audit"]["test_selector_reached"] is False
    assert payload["leakage_audit"]["test_selector_not_reached_reason"]


def test_no_eligible_model_skips_mapping_and_reports_actual_fixed_baseline_reason(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", lambda *_args, **_kwargs: {})
    base = _fixture_walk_forward_dependencies()
    dependencies = replace(
        base,
        evaluate_models=lambda *_args: {
            "selected": {},
            "candidates": [{"config_id": "failed", "eligible": False, "rejection_reasons": ["distance gate"]}],
        },
        build_mappings=lambda *_args: pytest.fail("mapping must not run without an eligible model"),
        replay_test=_default_replay_test,
    )
    inputs = WalkForwardInputs(
        market=_minute_market(BTCUSDT_FIRST_FOLD.test.start_at - timedelta(days=7), 1),
        cluster_fit_vectors=(), mapping_vectors=(), validation_vectors=(), data_provenance={},
    )
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(_candidate("candidate-a"),), dependencies=dependencies, inputs=inputs,
    )
    assert "mapping_evidence_ready" not in payload["pipeline_events"]
    assert "mapping_skipped_no_eligible_model" in payload["pipeline_events"]
    assert payload["comparisons"]["train_selected_fixed"]["rejection_reasons"] == [
        "not evaluated: no eligible model"
    ]
    markdown = __import__("scripts.chart_regime_strategy_mapping", fromlist=["render_walk_forward_markdown"]).render_walk_forward_markdown(payload)
    assert "distance gate" in markdown


def test_frozen_selection_hashes_do_not_depend_on_test_outcome() -> None:
    first = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD, candidates=(_candidate("a"),),
        dependencies=_fixture_walk_forward_dependencies("0.1"),
    )
    changed = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD, candidates=(_candidate("a"),),
        dependencies=_fixture_walk_forward_dependencies("-0.9"),
    )
    assert first["frozen_artifact_hashes"] == changed["frozen_artifact_hashes"]
    assert first["comparisons"] != changed["comparisons"]


def test_test_interval_is_not_passed_to_any_scoring_stage() -> None:
    dependencies = _fixture_walk_forward_dependencies()
    seen = []

    def wrap(function, *, test_stage=False):
        def call(context, *args):
            seen.append((test_stage, set(context)))
            return function(context, *args)
        return call

    guarded = WalkForwardDependencies(
        wrap(dependencies.prepare_data),
        wrap(dependencies.build_cluster_features),
        wrap(dependencies.evaluate_models),
        wrap(dependencies.build_mappings),
        wrap(dependencies.validate),
        wrap(dependencies.replay_test, test_stage=True),
    )
    run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD, candidates=(_candidate("a"),), dependencies=guarded
    )
    assert all("test" not in keys for is_test, keys in seen if not is_test)
    assert "test" in seen[-1][1]


def test_walk_forward_candidate_duplicates_dedupe_but_conflicts_fail_before_data() -> None:
    calls = []
    dependencies = _fixture_walk_forward_dependencies()

    def prepare(context):
        calls.append("data")
        return dependencies.prepare_data(context)

    guarded = replace(dependencies, prepare_data=prepare)
    candidate = _candidate("same")
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(candidate, candidate),
        dependencies=guarded,
    )
    assert payload["candidate_ids"] == ["same"]
    assert calls == ["data"]

    calls.clear()
    with pytest.raises(ValueError, match="conflicting candidate definition"):
        run_chart_regime_walk_forward(
            BTCUSDT_FIRST_FOLD,
            candidates=(candidate, _candidate("same", equity_ratio="0.2")),
            dependencies=guarded,
        )
    assert calls == []


def test_walk_forward_fold_grid_and_cli_contract(tmp_path: Path) -> None:
    assert BTCUSDT_FIRST_FOLD.mapping_fit.start_at - BTCUSDT_FIRST_FOLD.cluster_fit.end_at == timedelta(days=7)
    assert BTCUSDT_FIRST_FOLD.validation.start_at - BTCUSDT_FIRST_FOLD.mapping_fit.end_at == timedelta(days=7)
    assert BTCUSDT_FIRST_FOLD.test.start_at - BTCUSDT_FIRST_FOLD.validation.end_at == timedelta(days=7)
    assert PRODUCTION_WALK_FORWARD_GRID.gmm_covariance_types == ("diag", "tied")
    assert PRODUCTION_WALK_FORWARD_GRID.gmm_probability_mins
    args = parse_walk_forward_args(["--symbol", "BTCUSDT", "--candidate-group", "all", "--output-json", str(tmp_path / "x.json"), "--output-markdown", str(tmp_path / "x.md")])
    assert args.output_model.name == "x-model.json"
    assert args.output_mapping.name == "x-mapping.json"


def test_atomic_walk_forward_reports_preserve_previous_files_on_render_failure(tmp_path: Path) -> None:
    json_path, md_path = tmp_path / "report.json", tmp_path / "report.md"
    write_walk_forward_reports({"comparisons": {}, "symbol": "BTCUSDT"}, json_path, md_path)
    before = (json_path.read_bytes(), md_path.read_bytes())
    with pytest.raises(ValueError):
        write_walk_forward_reports({"bad": float("nan")}, json_path, md_path)
    assert (json_path.read_bytes(), md_path.read_bytes()) == before


def test_cached_archive_is_verified_against_remote_checksum(monkeypatch, tmp_path: Path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    archive = tmp_path / "BTCUSDT-1m-2026-01.zip"
    archive.write_bytes(b"verified archive")
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: BytesIO(f"{expected}  {archive.name}\n".encode("ascii")))
    actual, remote, source = module._ensure_archive(archive, "https://example.test/archive.zip")
    assert (actual, remote) == (expected, expected)
    assert source.endswith(".CHECKSUM")

    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: BytesIO(("0" * 64 + "  bad.zip\n").encode("ascii")))
    with pytest.raises(ValueError, match="checksum mismatch"):
        module._ensure_archive(archive, "https://example.test/archive.zip")


def _regime_vectors(anchors):
    names = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)
    vectors = []
    for index, anchor in enumerate(anchors):
        cluster = index % 3
        values = {
            name: float(cluster * 25 + __import__("math").sin((index + 1) * (column + 1) * 0.37) + column * 0.071)
            for column, name in enumerate(names)
        }
        vectors.append(ChartFeatureVector("BTCUSDT", anchor, anchor - timedelta(days=7), CHART_FEATURE_SCHEMA_VERSION, values))
    return tuple(vectors)


def test_chronological_stability_refits_disjoint_time_blocks() -> None:
    from src.domain.regime.model import RegimeModelConfig
    from src.infrastructure.regime.sklearn_regime_model import SklearnRegimeModel

    anchors = [datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(hours=4 * index) for index in range(90)]
    vectors = _regime_vectors(anchors)
    mapping = _regime_vectors([
        datetime(2025, 7, 7, tzinfo=timezone.utc) + timedelta(days=7 * index)
        for index in range(26)
    ])
    real = SklearnRegimeModel()
    primary = real.fit(RegimeModelConfig("kmeans", 3, 20260714), vectors)

    class RecordingEngine:
        def __init__(self):
            self.blocks = []

        def fit(self, config, block, *, retained_feature_names=None):
            self.blocks.append((block[0].anchor_at, block[-1].anchor_at, len(block)))
            return real.fit(config, block, retained_feature_names=retained_feature_names)

        def assign(self, artifact, values):
            return real.assign(artifact, values)

    engine = RecordingEngine()
    distance, drift, profiles = _chronological_block_stability(engine, primary, vectors, mapping)
    assert engine.blocks[0][1] < engine.blocks[1][0]
    assert [item[2] for item in engine.blocks] == [45, 45]
    assert distance >= 0 and 0 <= drift <= 1
    assert len(profiles) == 2


def test_chronological_refits_freeze_primary_features_when_block_correlations_differ() -> None:
    from src.domain.regime.model import RegimeModelConfig
    from src.infrastructure.regime.sklearn_regime_model import SklearnRegimeModel

    anchors = [datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(hours=4 * index) for index in range(90)]
    varied = []
    for index, vector in enumerate(_regime_vectors(anchors)):
        values = dict(vector.values)
        values["return_12h"] = (
            values["return_4h"]
            if index < 45
            else float((index % 11) ** 2 + (index % 3) * 0.17)
        )
        varied.append(replace(vector, values=values))
    vectors = tuple(varied)
    engine = SklearnRegimeModel()
    config = RegimeModelConfig("kmeans", 3, 20260714)
    independently_selected = (
        engine.fit(config, vectors[:45]).feature_names,
        engine.fit(config, vectors[45:]).feature_names,
    )
    assert independently_selected[0] != independently_selected[1]
    primary = engine.fit(config, vectors)
    mapping = _regime_vectors([
        datetime(2025, 7, 7, tzinfo=timezone.utc) + timedelta(days=7 * index)
        for index in range(26)
    ])

    distance, drift, profiles = _chronological_block_stability(
        engine, primary, vectors, mapping
    )
    assert distance >= 0 and 0 <= drift <= 1
    assert len(profiles) == 2


def test_block_centroids_are_projected_into_primary_standardized_coordinates() -> None:
    import numpy as np
    from dataclasses import replace
    from src.domain.regime.model import RegimeModelConfig
    from src.infrastructure.regime.sklearn_regime_model import SklearnRegimeModel

    anchors = [datetime(2021, 1, 1, tzinfo=timezone.utc) + timedelta(hours=4 * index) for index in range(90)]
    artifact = SklearnRegimeModel().fit(RegimeModelConfig("kmeans", 3), _regime_vectors(anchors))
    assert np.allclose(_project_centroids_to_primary_coordinates(artifact, artifact), artifact.means)

    shifted = replace(
        artifact,
        medians=tuple(value + 5 for value in artifact.medians),
        scales=tuple(value * 2 for value in artifact.scales),
    )
    raw = np.asarray(shifted.means) * np.asarray(shifted.scales) + np.asarray(shifted.medians)
    expected = (
        np.clip(raw, artifact.lower_bounds, artifact.upper_bounds) - np.asarray(artifact.medians)
    ) / np.asarray(artifact.scales)
    actual = _project_centroids_to_primary_coordinates(shifted, artifact)
    assert np.allclose(actual, expected)
    assert not np.allclose(actual, shifted.means)


def test_default_model_mapping_and_replay_stages_execute_end_to_end(monkeypatch, tmp_path: Path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "normalized_mutual_info_score",
        lambda *_args, **_kwargs: 1.0 + 5e-16,
    )

    cluster_anchors = [BTCUSDT_FIRST_FOLD.cluster_fit.start_at + timedelta(hours=4 * index) for index in range(90)]
    mapping_anchors = [episode.anchor_at for episode in build_weekly_episodes(BTCUSDT_FIRST_FOLD.mapping_fit.start_at, BTCUSDT_FIRST_FOLD.mapping_fit.end_at)]
    validation_anchors = [BTCUSDT_FIRST_FOLD.validation.start_at + timedelta(hours=4 * index) for index in range(12)]
    candidate = _candidate("candidate-a")

    def evidence(_market, *, episodes, assignments, candidates, **_kwargs):
        rows = []
        for episode in episodes:
            for item in candidates:
                rows.append({
                    "cluster_fingerprint": assignments[episode.anchor_at],
                    "candidate_id": item.candidate_id,
                    "episode_start_at": episode.start_at.isoformat(),
                    "episode_end_at": episode.end_at.isoformat(),
                    "initial_equity": "10000", "final_equity": "10000", "net_pnl": "0", "return_ratio": "0",
                    "trade_count": 0, "trades": [], "candidate_hash": "a" * 64,
                    "market_context_hash": "b" * 64, "data_hash": _canonical_hash({"episode": episode.start_at.isoformat()}),
                    "feature_cache_hash": None, "feature_provenance": {}, "feature_config_hash": None,
                })
        return rows

    monkeypatch.setattr(module, "run_mapping_episodes", evidence)
    fixed_calls = []

    def fixed_replay(*args, **kwargs):
        fixed_calls.append(kwargs)
        return {
            "return_ratio": "0", "max_drawdown_ratio": "0", "trade_count": 1,
            "trades": [{
                "quantity": "1", "entry_price": "100", "exit_price": "100",
                "fee_paid": str(Decimal("200") * FEE_RATE), "net_pnl": "1",
                "owner_strategy_profile_id": kwargs["candidate"].candidate_id,
            }],
        }

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fixed_replay)
    replay_calls = []

    def replay(*args, **kwargs):
        mapping = kwargs["mapping_artifact"]
        policy = mapping.selection_confidence_thresholds
        replay_calls.append((kwargs["start_at"], mapping_artifact_hash(mapping)))
        score = (
            Decimal(str(policy.gmm_probability_min + policy.gmm_margin_min))
            if policy.model_type == "gmm" else Decimal("0")
        )
        return {
            "return_ratio": str(score),
            "portfolio_max_drawdown_ratio": "0",
            "actual_turnover_notional": "0",
            "trade_count": 0,
        }

    from src.infrastructure.regime.json_regime_artifact_repository import mapping_artifact_hash
    monkeypatch.setattr(module, "run_scheduler_driven_regime_backtest", replay)
    market = _minute_market(BTCUSDT_FIRST_FOLD.mapping_fit.start_at, 1)
    inputs = WalkForwardInputs(
        market=market,
        cluster_fit_vectors=_regime_vectors(cluster_anchors),
        mapping_vectors=_regime_vectors(mapping_anchors),
        validation_vectors=_regime_vectors(validation_anchors),
        data_provenance={"fixture": "default-stage-e2e"},
    )
    grid = WalkForwardGrid(
        cluster_counts=(3,), model_types=("kmeans", "gmm"),
        gmm_covariance_types=("diag",), seeds=(20260714, 20260715, 20260716),
        bootstrap_resamples=(10, 11), confidence_levels=(0.90, 0.95),
    )
    payload = run_chart_regime_walk_forward(
        BTCUSDT_FIRST_FOLD,
        candidates=(candidate,),
        include_deferred=True,
        inputs=inputs,
        fixture_grid=grid,
        output_json=tmp_path / "result.json",
        output_markdown=tmp_path / "result.md",
        output_model=tmp_path / "result-model.json",
        output_mapping=tmp_path / "result-mapping.json",
    )
    assert set(payload["selected_models"]) == {"kmeans", "gmm"}
    assert any(
        len(item.get("evidence", {}).get("chronological_block_refits", ())) == 2
        for item in payload["model_candidates"] if item.get("eligible")
    )
    assert all(
        audit["nmi"] == {"raw": 1.0 + 5e-16, "normalized": 1.0, "clamped": True}
        for item in payload["model_candidates"] if item.get("eligible")
        for audit in item["evidence"]["seed_metric_normalization"]
    )
    assert all(
        "incompatible feature profiles" not in " ".join(item.get("rejection_reasons", ()))
        for item in payload["model_candidates"]
    )
    assert set(payload["mapping_artifacts"]) == {"kmeans", "gmm"}
    assert payload["mapping_metrics"]["evidence_rows"] == 26
    assert len(payload["validation"]["candidates"]) == 48
    assert payload["selection_score"] == payload["validation"]["score_order"]
    assert all(
        "portfolio_max_drawdown_ratio" in row and "actual_turnover_notional" in row
        for row in payload["validation"]["candidates"]
    )
    assert payload["comparisons"]["kmeans_dynamic"]["status"] == "ok"
    assert payload["validation"]["selected_config_id"].endswith("gmm:p0.75:m0.2")
    selected_hash = next(
        row["mapping_artifact_hash"] for row in payload["validation"]["candidates"]
        if row["config_id"] == payload["validation"]["selected_config_id"]
    )
    assert (BTCUSDT_FIRST_FOLD.test.start_at, selected_hash) in replay_calls
    assert payload["pipeline_events"][-1] == "reports_written"
    assert payload["mapping_artifacts"]["gmm"]["candidate_assessments"]
    assert "cash_contribution" in payload["continuous_diagnostics"]["gmm_dynamic"]
    assert all(call["include_trade_details"] is True for call in fixed_calls)
    manual_calls = [
        call for call in fixed_calls
        if call["candidate"].candidate_id == "range-first-p2-tp0060-sl0045-e0035-l3-guard-a"
    ]
    assert len(manual_calls) == 1 and manual_calls[0]["include_deferred"] is True
    assert payload["continuous_diagnostics"]["adopted_fixed"]["concentration"]["top_5_positive_trade_pnl_share"] == "1"
    assert all((tmp_path / name).is_file() for name in (
        "result.json", "result.md", "result-model.json", "result-mapping.json"
    ))
from src.domain.regime import build_weekly_episodes
from src.domain.regime import CHART_FEATURE_REGISTRY_V1, CHART_FEATURE_SCHEMA_VERSION, ChartFeatureVector


def _minute_market(
    start: datetime,
    weeks: int = 2,
    price: Decimal = Decimal("100"),
    symbol: Symbol | None = None,
    warmup_minutes: int = 300,
) -> MarketSnapshot:
    symbol = symbol or Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    return MarketSnapshot(tuple(
        Candle(
            symbol=symbol,
            timeframe=timeframe,
            opened_at=start + timedelta(minutes=index),
            closed_at=start + timedelta(minutes=index + 1),
            open_price=price,
            high_price=price,
            low_price=price,
            close_price=price,
            volume=Decimal("10"),
        )
        for index in range(-warmup_minutes, weeks * 7 * 24 * 60)
    ))


def _evidence_result(kwargs, **overrides):
    initial = kwargs["initial_equity"]
    result = {
        "candidate_id": kwargs["candidate"].candidate_id,
        "initial_equity": str(initial),
        "final_equity": str(initial),
        "trade_count": 0,
        "trades_per_day": "0",
        "gross_pnl": "0",
        "net_pnl": "0",
        "fee_paid": "0",
        "return_ratio": "0",
        "daily_return_ratio": "0",
        "max_drawdown_ratio": "0",
        "net_win_rate": "0",
        "average_net_trade_roe": "0",
        "average_net_trade_expectancy_ratio": "0",
        "trades": [],
        "feature_cache_hash": None,
        "feature_provenance": {},
        "feature_config_hash": None,
    }
    result.update(overrides)
    return result


def _accounted_trade(
    kwargs,
    *,
    entry_at: datetime,
    exit_at: datetime,
    entry_price: Decimal = Decimal("100"),
    exit_price: Decimal = Decimal("101"),
    quantity: Decimal = Decimal("1"),
    direction: str = "long",
):
    gross = (
        (exit_price - entry_price) * quantity
        if direction == "long"
        else (entry_price - exit_price) * quantity
    )
    fee = (entry_price * quantity + exit_price * quantity) * FEE_RATE
    margin = entry_price * quantity / kwargs["candidate"].leverage
    return {
        "entry_at": entry_at.isoformat(),
        "exit_at": exit_at.isoformat(),
        "entry_price": str(entry_price),
        "exit_price": str(exit_price),
        "direction": direction,
        "quantity": str(quantity),
        "margin": str(margin),
        "gross_pnl": str(gross),
        "net_pnl": str(gross - fee),
        "fee_paid": str(fee),
        "exit_reason": "take_profit",
        "holding_bars": int((exit_at - entry_at).total_seconds() // 60),
    }


def _result_for_trades(kwargs, trades, **overrides):
    initial = kwargs["initial_equity"]
    gross = sum((Decimal(item["gross_pnl"]) for item in trades), Decimal("0"))
    net = sum((Decimal(item["net_pnl"]) for item in trades), Decimal("0"))
    fees = sum((Decimal(item["fee_paid"]) for item in trades), Decimal("0"))
    equity = initial
    peak = initial
    max_drawdown = Decimal("0")
    for trade in trades:
        equity += Decimal(trade["net_pnl"])
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
    count = len(trades)
    wins = sum(Decimal(item["net_pnl"]) > 0 for item in trades)
    result = _evidence_result(
        kwargs,
        trade_count=count,
        trades=trades,
        trades_per_day=str(Decimal(count) / Decimal(7)),
        gross_pnl=str(gross),
        net_pnl=str(net),
        fee_paid=str(fees),
        final_equity=str(initial + net),
        return_ratio=str(net / initial),
        daily_return_ratio=str((net / initial) / Decimal(7)),
        net_win_rate=str(Decimal(wins) / Decimal(count) if count else Decimal("0")),
        average_net_trade_roe=str(
            sum(
                (Decimal(item["net_pnl"]) / Decimal(item["margin"]) for item in trades),
                Decimal("0"),
            ) / Decimal(count)
            if count else Decimal("0")
        ),
        average_net_trade_expectancy_ratio=str(
            (net / Decimal(count)) / initial if count else Decimal("0")
        ),
        max_drawdown_ratio=str(max_drawdown),
    )
    result.update(overrides)
    return result


def _candidate(candidate_id: str, *, equity_ratio: str = "0.1") -> SchedulerBacktestCandidate:
    return SchedulerBacktestCandidate(
        candidate_id=candidate_id,
        strategies=(StrategyCandidateSpec("mtf", {}),),
        take_profit_ratio=Decimal("0.01"),
        stop_loss_ratio=Decimal("0.02"),
        equity_ratio=Decimal(equity_ratio),
        leverage=Decimal("3"),
        candle_limit=1,
    )


def test_mapping_runs_flat_nonoverlapping_weekly_evidence(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    market = _minute_market(start)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=14)))
    assignments = {episodes[0].anchor_at: "cluster-b", episodes[1].anchor_at: "cluster-a"}
    candidates = (_candidate("candidate-b"), _candidate("candidate-a"))
    calls = []

    def fake_backtest(snapshot, **kwargs):
        calls.append((snapshot, kwargs))
        return _evidence_result(kwargs)

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    rows = run_mapping_episodes(
        market,
        episodes=episodes,
        assignments=assignments,
        candidates=candidates,
        initial_equity=Decimal("4321"),
    )

    assert [(row["episode_start_at"], row["candidate_id"]) for row in rows] == [
        ("2026-01-05T00:00:00+00:00", "candidate-a"),
        ("2026-01-05T00:00:00+00:00", "candidate-b"),
        ("2026-01-12T00:00:00+00:00", "candidate-a"),
        ("2026-01-12T00:00:00+00:00", "candidate-b"),
    ]
    assert all(kwargs["initial_equity"] == Decimal("4321") for _, kwargs in calls)
    assert all(kwargs["force_close_at_end"] is True for _, kwargs in calls)
    assert all(kwargs["include_trade_details"] is True for _, kwargs in calls)
    assert [(snapshot.opened_at, snapshot.closed_at) for snapshot, _ in calls] == [
        (episodes[0].start_at - timedelta(minutes=1), episodes[0].end_at),
        (episodes[0].start_at - timedelta(minutes=1), episodes[0].end_at),
        (episodes[1].start_at - timedelta(minutes=1), episodes[1].end_at),
        (episodes[1].start_at - timedelta(minutes=1), episodes[1].end_at),
    ]
    assert all(row["initial_equity"] == "4321" and row["final_equity"] == "4321" for row in rows)


def test_mapping_hashes_are_canonical_and_bind_data_and_candidate(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episode = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    assignments = {start: "cluster-a"}

    first = run_mapping_episodes(_minute_market(start, 1), episodes=episode, assignments=assignments, candidates=(_candidate("a"),))
    same = run_mapping_episodes(_minute_market(start, 1, Decimal("100.0")), episodes=episode, assignments=assignments, candidates=(_candidate("a", equity_ratio="0.10"),), initial_equity=Decimal("1E4"))
    repriced = run_mapping_episodes(_minute_market(start, 1, Decimal("101")), episodes=episode, assignments=assignments, candidates=(_candidate("a"),))
    reconfigured = run_mapping_episodes(_minute_market(start, 1), episodes=episode, assignments=assignments, candidates=(_candidate("a", equity_ratio="0.2"),))

    assert first[0]["data_hash"] == same[0]["data_hash"]
    assert first[0]["candidate_hash"] == same[0]["candidate_hash"]
    assert first[0]["data_hash"] != repriced[0]["data_hash"]
    assert first[0]["candidate_hash"] != reconfigured[0]["candidate_hash"]


@pytest.mark.parametrize("case", ("gap", "assignment", "duplicate_candidate", "non_utc", "missing_data"))
def test_mapping_fails_closed_on_invalid_evidence_inputs(case) -> None:
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=14)))
    assignments = {episode.anchor_at: "cluster" for episode in episodes}
    candidates = (_candidate("a"),)
    market = _minute_market(start)

    if case == "gap":
        broken = list(episodes)
        broken[1] = type(broken[1])(
            anchor_at=broken[1].anchor_at + timedelta(days=7),
            feature_start_at=broken[1].feature_start_at + timedelta(days=7),
            start_at=broken[1].start_at + timedelta(days=7),
            end_at=broken[1].end_at + timedelta(days=7),
        )
        episodes = tuple(broken)
    elif case == "assignment":
        assignments = {episodes[0].anchor_at: "cluster"}
    elif case == "duplicate_candidate":
        candidates = (_candidate("a"), _candidate("a"))
    elif case == "non_utc":
        bad = episodes[0]
        naive = bad.start_at.replace(tzinfo=None)
        episodes = (type(bad)(naive, naive - timedelta(days=7), naive, naive + timedelta(days=7)),)
        assignments = {naive: "cluster"}
    elif case == "missing_data":
        market = _minute_market(start, 1)

    with pytest.raises(ValueError):
        run_mapping_episodes(market, episodes=episodes, assignments=assignments, candidates=candidates)


def test_mapping_requires_explicit_deferred_group_opt_in() -> None:
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    with pytest.raises(ValueError, match="deferred"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidate_groups=("microstructure",),
        )


def test_mapping_resolves_explicit_candidate_from_opted_in_factory(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    rows = run_mapping_episodes(
        _minute_market(start, 1),
        episodes=episodes,
        assignments={start: "cluster"},
        candidate_groups=("microstructure",),
        candidate_ids=("micro-mtf-balanced-tight",),
        include_deferred_groups=("microstructure",),
    )

    assert [row["candidate_id"] for row in rows] == ["micro-mtf-balanced-tight"]

    with pytest.raises(ValueError, match="unknown candidate_id"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidate_groups=("microstructure",),
            candidate_ids=("does-not-exist",),
            include_deferred_groups=("microstructure",),
        )


@pytest.mark.parametrize(
    ("override", "message"),
    (
        ({"net_pnl": None}, "net_pnl"),
        ({"candidate_id": "wrong"}, "candidate_id"),
        ({"trade_count": True}, "trade_count"),
        ({"fee_paid": "NaN"}, "fee_paid"),
        ({"trades": [{}]}, "trade"),
    ),
)
def test_mapping_rejects_partial_or_malformed_backtest_evidence(
    monkeypatch, override, message
) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs, **override),
    )

    with pytest.raises(ValueError, match=message):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


def test_mapping_rejects_missing_backtest_evidence_field(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    def missing_field(snapshot, **kwargs):
        result = _evidence_result(kwargs)
        del result["net_pnl"]
        return result

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", missing_field)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    with pytest.raises(ValueError, match="missing required fields: net_pnl"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


def test_mapping_data_hash_binds_feature_cache_identity(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    class Provider:
        def __init__(self, cache_hash, config_hash):
            self.feature_cache_hash = cache_hash
            self.feature_provenance = {"provider": "fixture", "config": config_hash}
            self.feature_config_hash = config_hash

    def fake_backtest(snapshot, **kwargs):
        provider = kwargs["market_feature_provider"]
        return _evidence_result(
            kwargs,
            feature_cache_hash=provider.feature_cache_hash,
            feature_provenance=provider.feature_provenance,
            feature_config_hash=feature_provider_config_hash(provider),
        )

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    kwargs = {
        "episodes": episodes,
        "assignments": {start: "cluster"},
        "candidates": (_candidate("a"),),
    }
    first = run_mapping_episodes(
        _minute_market(start, 1),
        **kwargs,
        market_feature_provider=Provider("cache-a", "config-a"),
    )
    changed = run_mapping_episodes(
        _minute_market(start, 1),
        **kwargs,
        market_feature_provider=Provider("cache-b", "config-b"),
    )

    assert first[0]["feature_cache_hash"] == "cache-a"
    assert len(first[0]["feature_config_hash"]) == 64
    assert first[0]["data_hash"] != changed[0]["data_hash"]


def test_mapping_rejects_symbol_mismatch_and_non_minute_market(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    kwargs = {
        "episodes": episodes,
        "assignments": {start: "cluster"},
        "candidates": (_candidate("a"),),
    }

    with pytest.raises(ValueError, match="symbol"):
        run_mapping_episodes(
            _minute_market(start, 1),
            **kwargs,
            symbol=Symbol("ETH", "USDT"),
        )

    daily = MarketSnapshot(tuple(
        Candle(
            symbol=Symbol("BTC", "USDT"),
            timeframe=Timeframe(1, "d"),
            opened_at=start + timedelta(days=index),
            closed_at=start + timedelta(days=index + 1),
            open_price=Decimal("100"),
            high_price=Decimal("100"),
            low_price=Decimal("100"),
            close_price=Decimal("100"),
            volume=Decimal("1"),
        )
        for index in range(7)
    ))
    with pytest.raises(ValueError, match="1m"):
        run_mapping_episodes(daily, **kwargs)


def test_mapping_supplies_identical_max_candidate_warmup_to_every_candidate(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    calls = []

    def fake_backtest(snapshot, **kwargs):
        calls.append((snapshot, kwargs))
        return _evidence_result(kwargs)

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    short = _candidate("short")
    long = SchedulerBacktestCandidate(
        candidate_id="long",
        strategies=short.strategies,
        take_profit_ratio=short.take_profit_ratio,
        stop_loss_ratio=short.stop_loss_ratio,
        equity_ratio=short.equity_ratio,
        leverage=short.leverage,
        candle_limit=5,
    )

    run_mapping_episodes(
        _minute_market(start, 1),
        episodes=episodes,
        assignments={start: "cluster"},
        candidates=(short, long),
    )

    expected_context_start = start - timedelta(minutes=5)
    assert len(calls) == 2
    assert all(snapshot.opened_at == expected_context_start for snapshot, _ in calls)
    assert calls[0][0].candles == calls[1][0].candles
    assert all(kwargs["context_start_at"] == expected_context_start for _, kwargs in calls)


def test_canonical_hash_type_tags_decimals_without_spelling_differences() -> None:
    assert _canonical_hash({"value": Decimal("100")}) == _canonical_hash(
        {"value": Decimal("1E2")}
    )
    assert _canonical_hash({"value": Decimal("1")}) != _canonical_hash({"value": "1"})


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("return_ratio", "0.1"),
        ("daily_return_ratio", "0.1"),
        ("trades_per_day", "1"),
        ("net_win_rate", "2"),
        ("max_drawdown_ratio", "2"),
        ("average_net_trade_expectancy_ratio", "0.1"),
        ("profit_factor", "1"),
    ),
)
def test_mapping_rejects_tampered_derived_summary(monkeypatch, field, value) -> None:
    import scripts.chart_regime_strategy_mapping as module

    monkeypatch.setattr(
        module,
        "run_scheduler_driven_backtest",
        lambda snapshot, **kwargs: _evidence_result(kwargs, **{field: value}),
    )
    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))

    with pytest.raises(ValueError, match=field):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("entry_price", "0", "entry_price"),
        ("quantity", "0", "quantity"),
        ("margin", "0", "margin"),
        ("fee_paid", "-0.1", "fee_paid"),
        ("net_pnl", "2", "net_pnl"),
        ("entry_at", "2026-01-04T23:59:00+00:00", "entry_at"),
        ("exit_at", "2026-01-05T00:00:00+00:00", "exit_at"),
        ("holding_bars", 2, "holding_bars"),
    ),
)
def test_mapping_rejects_invalid_trade_accounting_or_bounds(
    monkeypatch, field, value, message
) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def fake_backtest(snapshot, **kwargs):
        trade = _accounted_trade(
            kwargs,
            entry_at=start,
            exit_at=start + timedelta(minutes=1),
        )
        result = _result_for_trades(kwargs, [trade])
        result["trades"][0][field] = value
        return result

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    with pytest.raises(ValueError, match=message):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


@pytest.mark.parametrize(
    ("forgery", "message"),
    (("gross", "gross_pnl"), ("fee", "fee_paid"), ("margin", "margin")),
)
def test_mapping_rejects_coherent_reported_trade_forgery(monkeypatch, forgery, message) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def fake_backtest(snapshot, **kwargs):
        trade = _accounted_trade(kwargs, entry_at=start, exit_at=start + timedelta(minutes=1))
        if forgery == "gross":
            trade["gross_pnl"] = "2"
            trade["fee_paid"] = "0.2"
            trade["net_pnl"] = "1.8"
        elif forgery == "fee":
            trade["fee_paid"] = "0.2"
            trade["net_pnl"] = "0.8"
        else:
            trade["margin"] = "34"
        return _result_for_trades(kwargs, [trade])

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    with pytest.raises(ValueError, match=message):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


@pytest.mark.parametrize("mode", ("overlap", "reordered"))
def test_mapping_rejects_non_chronological_single_position_trades(monkeypatch, mode) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)

    def fake_backtest(snapshot, **kwargs):
        first = _accounted_trade(
            kwargs, entry_at=start, exit_at=start + timedelta(minutes=2)
        )
        second = _accounted_trade(
            kwargs,
            entry_at=start + timedelta(minutes=1 if mode == "overlap" else 2),
            exit_at=start + timedelta(minutes=3),
        )
        trades = [first, second] if mode == "overlap" else [second, first]
        return _result_for_trades(kwargs, trades)

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    with pytest.raises(ValueError, match="chronological|overlap"):
        run_mapping_episodes(
            _minute_market(start, 1),
            episodes=episodes,
            assignments={start: "cluster"},
            candidates=(_candidate("a"),),
        )


def test_mapping_reconstructs_drawdown_and_allows_equity_below_zero(monkeypatch) -> None:
    import scripts.chart_regime_strategy_mapping as module

    start = datetime(2026, 1, 5, tzinfo=timezone.utc)
    forged = {"enabled": True}

    def fake_backtest(snapshot, **kwargs):
        trade = _accounted_trade(
            kwargs,
            entry_at=start,
            exit_at=start + timedelta(minutes=1),
            entry_price=Decimal("100"),
            exit_price=Decimal("1"),
            quantity=Decimal("200"),
        )
        result = _result_for_trades(kwargs, [trade])
        if forged["enabled"]:
            result["max_drawdown_ratio"] = "0"
        return result

    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    episodes = tuple(build_weekly_episodes(start, start + timedelta(days=7)))
    kwargs = {
        "episodes": episodes,
        "assignments": {start: "cluster"},
        "candidates": (_candidate("a"),),
    }
    with pytest.raises(ValueError, match="max_drawdown_ratio"):
        run_mapping_episodes(_minute_market(start, 1), **kwargs)

    forged["enabled"] = False
    rows = run_mapping_episodes(_minute_market(start, 1), **kwargs)
    assert Decimal(rows[0]["max_drawdown_ratio"]) > Decimal("1")


def test_three_day_k4_loader_uses_context_only_before_first_fit_anchor(monkeypatch, tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    captured = {}
    sentinel_vectors = (object(),)
    sentinel_provenance = ({"archive": "sentinel"},)

    def fake_loader(**kwargs):
        captured.update(kwargs)
        return sentinel_vectors, sentinel_provenance

    def fake_fit(vectors, **kwargs):
        captured["fit_vectors"] = vectors
        captured["fit_provenance"] = kwargs["source_provenance"]
        return "sentinel-outcome"

    monkeypatch.setattr(module, "load_three_day_feature_history", fake_loader)
    monkeypatch.setattr(module, "fit_fold_local_three_day_k4_model", fake_fit)
    outcome = module.load_and_fit_fold_local_three_day_k4_model(
        raw_root=tmp_path,
        code_provenance_hash="a" * 64,
    )

    assert outcome == "sentinel-outcome"
    assert captured["start"] == datetime(2020, 12, 29, tzinfo=timezone.utc)
    assert captured["end"] == datetime(2025, 6, 30, tzinfo=timezone.utc)
    assert captured["expected_anchor_count"] == 1641
    assert captured["fit_vectors"] is sentinel_vectors
    assert captured["fit_provenance"] is sentinel_provenance


def test_three_day_k4_loader_corruption_fails_before_fit(monkeypatch, tmp_path) -> None:
    import scripts.chart_regime_strategy_mapping as module

    called = []

    def corrupt_loader(**kwargs):
        raise ValueError("archive checksum mismatch")

    monkeypatch.setattr(module, "load_three_day_feature_history", corrupt_loader)
    monkeypatch.setattr(module, "fit_fold_local_three_day_k4_model", lambda *args, **kwargs: called.append(True))
    with pytest.raises(ValueError, match="checksum"):
        module.load_and_fit_fold_local_three_day_k4_model(
            raw_root=tmp_path,
            code_provenance_hash="a" * 64,
        )
    assert called == []


def test_three_day_k4_rejects_provenance_before_diagnostic_fit() -> None:
    from src.domain.regime import THREE_DAY_CHART_FEATURE_REGISTRY_V1, ThreeDayChartFeatureVector
    from scripts.chart_regime_strategy_mapping import fit_fold_local_three_day_k4_model

    class SpyDiagnostic:
        def fit(self, *args, **kwargs):
            raise AssertionError("fit must not run")

    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    values = {spec.name: 0.0 for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
    vectors = tuple(
        ThreeDayChartFeatureVector(
            "BTCUSDT", start + timedelta(days=index), start + timedelta(days=index - 3), values
        )
        for index in range(1641)
    )
    with pytest.raises(ValueError, match="provenance"):
        fit_fold_local_three_day_k4_model(
            vectors,
            source_provenance=({"forged": True},),
            code_provenance_hash="a" * 64,
            diagnostic=SpyDiagnostic(),
        )
