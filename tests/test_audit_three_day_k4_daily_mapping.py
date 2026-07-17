from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.audit_three_day_k4_daily_mapping import (
    AuditInputs,
    _audit_mapping,
    _audit_model,
    _audit_freeze,
    _reconstruct_cluster_fit,
    _compare_phase_reconstruction,
    audit_three_day_k4_daily_mapping,
    canonical_json_bytes,
)
from tests.infrastructure.regime.test_three_day_k4_model_artifact import _artifact


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value, newline=False)).hexdigest()


def _write_bundle(tmp_path: Path) -> tuple[AuditInputs, dict[str, object]]:
    raw = tmp_path / "raw.bin"
    raw.write_bytes(b"verified raw BTCUSDT archive")
    candidate_payload = {
        "candidate_count": 1,
        "candidate_ids": ["candidate-a"],
        "ordered_definition_hashes": [["candidate-a", "1" * 64]],
        "candidate_universe_hash": _hash(["candidate-a"]),
        "entries": [{"candidate_id": "candidate-a", "definition_hash": "1" * 64}],
    }
    candidate_payload["manifest_hash"] = _hash(candidate_payload)
    components = ["a" * 24, "b" * 24, "c" * 24, "d" * 24]
    model = {
        "artifact_version": "fixture-model-v1",
        "component_fingerprints": components,
        "numeric_index_to_fingerprint": {str(index): value for index, value in enumerate(components)},
        "weights": [0.25] * 4,
        "means": [[float(index)] for index in range(4)],
        "covariances": [[1.0] for _ in range(4)],
        "retained_feature_names": ["return_3d"],
        "source_provenance": [{
            "local_path": str(raw), "bytes": raw.stat().st_size,
            "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
        }],
        "fit_input_vectors": [{"anchor_at": "2025-07-07T00:00:00Z", "values": [0.1]}],
    }
    model["fit_input_vector_hash"] = _hash(model["fit_input_vectors"])
    model["source_combined_hash"] = _hash({"archives": model["source_provenance"]})
    model["component_fingerprint_hash"] = _hash(components)
    model["artifact_hash"] = _hash(model)

    trade = {
        "entry_at": "2025-07-07T01:00:00Z", "exit_at": "2025-07-07T02:00:00Z",
        "direction": "long", "entry_price": "100", "exit_price": "101",
        "quantity": "1", "gross_pnl": "1", "fee_paid": "0.1", "net_pnl": "0.9",
        "exit_reason": "target",
    }
    evidence_row = {
        "candidate_id": "candidate-a", "candidate_hash": "1" * 64,
        "component_fingerprint": components[0],
        "outcome_start_at": "2025-07-07T00:00:00Z",
        "initial_equity": "100", "final_equity": "100.9", "net_pnl": "0.9",
        "net_return_ratio": "0.009", "closed_trade_count": 1, "trades": [trade],
    }
    evidence = {
        "phase": "mapping_fit", "component_assignments": [components[0]],
        "assignment_features": [[0.1]],
        "calendar_rows": [{
            "outcome_start_at": "2025-07-07T00:00:00Z",
            "component_fingerprint": components[0], "role": "mapping_fit",
        }],
        "daily_evidence_rows": [evidence_row],
        "archive_descriptors": model["source_provenance"],
    }
    evidence["assignment_hash"] = _hash(evidence["component_assignments"])
    evidence["archive_descriptor_hash"] = _hash(evidence["archive_descriptors"])
    evidence["evidence_hash"] = _hash(evidence["daily_evidence_rows"])

    assessment = {
        "component_fingerprint": components[0], "candidate_id": "candidate-a",
        "candidate_hash": "1" * 64, "corrected_lower_bound_ratio": "0.001",
        "mean_daily_return_ratio": "0.009", "maximum_drawdown_ratio": "0",
        "eligible": True,
    }
    mapping = {
        "artifact_version": "fixture-mapping-v1", "model_artifact_hash": model["artifact_hash"],
        "candidate_universe_hash": candidate_payload["candidate_universe_hash"],
        "candidate_ids": ["candidate-a"], "candidate_hashes": {"candidate-a": "1" * 64},
        "component_fingerprints": components,
        "entries": [
            {"component_fingerprint": components[0], "decision": "strategy", "strategy_candidate_id": "candidate-a", "rejection_reasons": []},
            *[
                {"component_fingerprint": item, "decision": "cash", "strategy_candidate_id": None, "rejection_reasons": ["no_eligible_candidate"]}
                for item in components[1:]
            ],
        ],
        "candidate_assessments": [assessment],
    }
    mapping["artifact_hash"] = _hash(mapping)

    transitions = [{"at": "2026-04-05T00:00:00Z", "from": None, "to": "candidate-a"}]
    comparison_trades = [{
        **trade, "exit_at": "2026-04-05T02:00:00Z",
        "exit_reason": "active_strategy_opposite_signal",
    }]
    equity = [
        {"at": "2026-04-05T00:00:00Z", "equity": "100"},
        {"at": "2026-04-05T02:00:00Z", "equity": "100.9"},
    ]
    dynamic = {
        "transitions": transitions, "transition_hash": _hash(transitions),
        "trades": comparison_trades, "trade_hash": _hash(comparison_trades),
        "equity_curve": equity, "equity_curve_hash": _hash(equity),
        "initial_equity": "100", "final_equity": "100.9", "return_ratio": "0.009",
        "max_drawdown_ratio": "0", "trade_count": 1,
        "active_strategy_opposite_exit_count": 1,
    }
    cash = {
        "trades": [], "equity_curve": [], "initial_equity": "100", "final_equity": "100",
        "return_ratio": "0", "max_drawdown_ratio": "0", "trade_count": 0,
    }
    baseline = {"decision": "strategy", "candidate_id": "candidate-a", "candidate_hash": "1" * 64}
    pretest = {
        "model": model, "candidate_manifest": candidate_payload,
        "evidence": {"mapping_fit": evidence}, "mapping": mapping,
        "global_fixed_baseline": baseline,
        "profile": {"profile_id": "three-day-daily-k4-v1"},
        "chronology": {"mapping_fit": {"end_at": "2026-04-01T00:00:00Z"}},
    }
    report = {
        "schema_version": "three-day-daily-k4-report-v1",
        "source_verification": {"raw_inputs": model["source_provenance"]},
        "candidate_manifest": candidate_payload, "model_artifact": model,
        "evidence": {"mapping_fit": evidence}, "strict_mapping": mapping,
        "strict_mapping_artifact_hash": mapping["artifact_hash"],
        "global_fixed_baseline": baseline, "pre_test_freeze_payload": pretest,
        "pre_test_freeze_hash": _hash(pretest),
        "test_provenance": {"pre_test_freeze_hash": _hash(pretest), "first_test_timestamp": "2026-04-04T00:00:00Z"},
        "test_comparisons": {"cash": cash, "k4_dynamic_active_strategy_opposite_exit": dynamic},
    }

    paths = {
        "report": tmp_path / "report.json", "markdown": tmp_path / "report.md",
        "model": tmp_path / "model.json", "mapping": tmp_path / "mapping.json",
    }
    paths["model"].write_bytes(canonical_json_bytes(model))
    paths["mapping"].write_bytes(canonical_json_bytes(mapping))
    paths["markdown"].write_text("fixture report\n", encoding="utf-8")
    report["output_hashes"] = {
        "model": hashlib.sha256(paths["model"].read_bytes()).hexdigest(),
        "mapping": hashlib.sha256(paths["mapping"].read_bytes()).hexdigest(),
        "markdown": hashlib.sha256(paths["markdown"].read_bytes()).hexdigest(),
    }
    paths["report"].write_bytes(canonical_json_bytes(report))
    return AuditInputs(**paths), report


def _factory(report: dict[str, object]):
    return lambda: copy.deepcopy(report["candidate_manifest"])


def test_independent_audit_reconstructs_bundle_and_emits_canonical_result(tmp_path) -> None:
    inputs, report = _write_bundle(tmp_path)

    result = audit_three_day_k4_daily_mapping(inputs, candidate_manifest_factory=_factory(report))

    assert result["passed"] is True
    assert result["failures"] == []
    assert result["checked_counts"]["raw_inputs"] == 1
    assert result["checked_counts"]["evidence_rows"] == 1
    assert result["checked_counts"]["test_trades"] == 1
    assert result["hashes"]["pre_test_freeze_hash"] == report["pre_test_freeze_hash"]
    assert canonical_json_bytes(result).endswith(b"\n")


def test_auditor_accepts_and_semantically_reparses_real_task7_model_schema() -> None:
    payload = json.loads(_artifact().to_json())
    failures: list[str] = []

    parsed = _audit_model(payload, payload, failures)

    assert parsed is not None
    assert parsed.artifact_hash == payload["artifact_hash"]
    assert failures == []


def test_cluster_fit_is_reconstructed_from_raw_root_not_published_parameters(
    monkeypatch, tmp_path
) -> None:
    import scripts.audit_three_day_k4_daily_mapping as module

    published = json.loads(_artifact().to_json())
    calls = []
    sentinel_vectors = (object(),)
    sentinel_provenance = ({"raw": "verified"},)
    monkeypatch.setattr(
        module, "_load_cluster_fit_vectors",
        lambda raw_root, provenance=(): calls.append(("load", raw_root)) or (sentinel_vectors, sentinel_provenance),
    )

    class Outcome:
        artifact = type("Artifact", (), {"canonical_payload": lambda self: published})()
        rejection_reasons = ()

    def refit(vectors, provenance, code_hash):
        calls.append(("fit", vectors, provenance, code_hash))
        return Outcome()

    monkeypatch.setattr(module, "_fit_cluster_model", refit)
    failures: list[str] = []

    rebuilt = _reconstruct_cluster_fit(
        {"source_verification": {"raw_kline_root": str(tmp_path)}},
        published,
        failures,
    )

    assert rebuilt is not None
    assert calls[0] == ("load", tmp_path)
    assert calls[1][1:3] == (sentinel_vectors, sentinel_provenance)
    assert failures == []


def test_cluster_fit_rejects_self_consistent_published_parameter_forgery(
    monkeypatch, tmp_path
) -> None:
    import scripts.audit_three_day_k4_daily_mapping as module

    original = json.loads(_artifact().to_json())
    forged = copy.deepcopy(original)
    forged["means"][0][0] += 1
    forged["artifact_hash"] = _hash({key: value for key, value in forged.items() if key != "artifact_hash"})
    monkeypatch.setattr(module, "_load_cluster_fit_vectors", lambda raw_root, provenance=(): ((object(),), ({},)))

    class Outcome:
        artifact = type("Artifact", (), {"canonical_payload": lambda self: original})()
        rejection_reasons = ()

    monkeypatch.setattr(module, "_fit_cluster_model", lambda *args: Outcome())
    failures: list[str] = []

    _reconstruct_cluster_fit(
        {"source_verification": {"raw_kline_root": str(tmp_path)}}, forged, failures
    )

    assert any("raw-refitted K4" in failure for failure in failures)


def test_consistent_report_and_ledger_trade_forgery_is_rejected_by_fresh_replay() -> None:
    original = {
        "candidate_id": "candidate-a",
        "outcome_interval": {"start_at": "2025-07-07T00:00:00+00:00"},
        "final_equity": "101", "net_pnl": "1", "net_return_ratio": "0.01",
    }
    forged = {**original, "final_equity": "102", "net_pnl": "2", "net_return_ratio": "0.02"}
    bundle = {
        "daily_evidence_rows": [forged],
        "component_assignments": ["a" * 24],
    }
    ledger = [{
        "phase": "mapping_fit", "outcome_start_at": "2025-07-07T00:00:00+00:00",
        "candidate_id": "candidate-a", "evidence": forged,
    }]
    failures: list[str] = []

    _compare_phase_reconstruction(
        "mapping_fit", bundle, ledger, [original], ["a" * 24], failures
    )

    assert not any("ledger/report" in item for item in failures)
    assert any("raw scheduler-replayed evidence" in item for item in failures)


def test_auditor_rebuilds_real_task7_mapping_schema_from_daily_evidence() -> None:
    from src.application.usecases.regime.build_daily_strategy_mapping_usecase import (
        BuildDailyStrategyMappingUseCase,
    )
    from src.domain.regime import daily_mapping_artifact_hash, ThreeDayDailyResearchProfile
    from src.domain.regime import ThreeDayDailyResearchProfile
    from tests.application.usecases.regime.test_build_daily_strategy_mapping_usecase import (
        valid_command,
    )

    command = valid_command()
    artifact = BuildDailyStrategyMappingUseCase().execute(command).artifact
    mapping_payload = artifact.canonical_payload()
    mapping_file = {**mapping_payload, "artifact_hash": daily_mapping_artifact_hash(artifact)}
    manifest = {
        "ordered_definition_hashes": [list(item) for item in command.candidate_manifest],
        "candidate_universe_hash": artifact.candidate_universe_hash,
    }
    report = {
        "strict_mapping": mapping_payload,
        "strict_mapping_artifact_hash": mapping_file["artifact_hash"],
        "evidence": {
            "mapping_fit": {
                "daily_evidence_rows": [item.canonical_payload() for item in command.evidence_rows]
            }
        },
    }
    model = {
        "artifact_hash": command.model_artifact_hash,
        "component_fingerprints": list(command.frozen_component_fingerprints),
    }
    failures: list[str] = []

    rebuilt = _audit_mapping(report, mapping_file, manifest, model, failures)

    assert rebuilt is not None
    assert daily_mapping_artifact_hash(rebuilt) == mapping_file["artifact_hash"]
    assert failures == []


def test_audit_fails_closed_when_raw_input_cannot_be_resolved(tmp_path) -> None:
    inputs, report = _write_bundle(tmp_path)
    report["model_artifact"]["source_provenance"][0].pop("local_path")
    report["source_verification"]["raw_inputs"][0].pop("local_path", None)
    model = json.loads(inputs.model.read_text(encoding="utf-8"))
    model["source_provenance"][0].pop("local_path")
    model["source_combined_hash"] = _hash({"archives": model["source_provenance"]})
    model["artifact_hash"] = _hash({key: value for key, value in model.items() if key != "artifact_hash"})
    report["model_artifact"] = copy.deepcopy(model)
    inputs.model.write_bytes(canonical_json_bytes(model))
    report["output_hashes"]["model"] = hashlib.sha256(inputs.model.read_bytes()).hexdigest()
    inputs.report.write_bytes(canonical_json_bytes(report))

    result = audit_three_day_k4_daily_mapping(
        inputs, candidate_manifest_factory=_factory(report)
    )

    assert result["passed"] is False
    assert any("no uniquely resolvable local file" in item for item in result["failures"])


def test_auditor_accepts_actual_task7_publication_envelope_and_byte_formats(tmp_path) -> None:
    from scripts.chart_regime_strategy_mapping import render_three_day_publication

    inputs, report = _write_bundle(tmp_path)
    report.pop("output_hashes")
    model = json.loads(inputs.model.read_text(encoding="utf-8"))
    mapping = json.loads(inputs.mapping.read_text(encoding="utf-8"))
    rendered = render_three_day_publication(
        report=report,
        model_json=canonical_json_bytes(model, newline=False),
        mapping_json=canonical_json_bytes(mapping),
    )
    inputs.report.write_bytes(rendered.report_json)
    inputs.markdown.write_bytes(rendered.report_markdown)
    inputs.model.write_bytes(rendered.model_json)
    inputs.mapping.write_bytes(rendered.mapping_json)

    result = audit_three_day_k4_daily_mapping(
        inputs, candidate_manifest_factory=_factory(report)
    )

    assert result["passed"] is True, result["failures"]


def test_real_typed_task7_publication_raw_root_and_ledgers_flow_through_audit(
    monkeypatch, tmp_path
) -> None:
    from dataclasses import replace
    import scripts.audit_three_day_k4_daily_mapping as module
    from scripts.chart_regime_strategy_mapping import render_three_day_publication
    from src.application.usecases.regime.build_daily_strategy_mapping_usecase import (
        BuildDailyStrategyMappingCommand, BuildDailyStrategyMappingUseCase,
        build_daily_statistical_calendar, select_global_fixed_daily_candidate,
    )
    from src.domain.regime import daily_mapping_artifact_hash, ThreeDayDailyResearchProfile
    from src.domain.regime.mapping import candidate_universe_hash
    from src.infrastructure.regime.three_day_k4_model_artifact import ThreeDayK4ModelArtifact
    from tests.application.usecases.regime.test_build_daily_strategy_mapping_usecase import (
        evidence, sha,
    )

    raw_root = tmp_path / "raw"
    base = _artifact()
    provenance = []
    for item in base.source_provenance:
        row = dict(item)
        path = raw_root / "BTCUSDT" / Path(str(row["url"])).name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        row.update(bytes=1, sha256=digest, expected_sha256=digest)
        provenance.append(row)
    kwargs = {
        key: value for key, value in base.__dict__.items()
        if key not in {"fit", "artifact_hash", "source_provenance"}
    }
    model = ThreeDayK4ModelArtifact.from_fit(
        base.fit, source_provenance=tuple(provenance), **kwargs
    )
    plan = build_daily_statistical_calendar(include_validation=True)
    components = model.component_fingerprints
    assigned = []
    rows = []
    candidate_hash = sha("candidate-a")
    for index, item in enumerate(plan):
        component = None if item.role == "purge" else components[index % 4]
        assigned.append(component)
        if component is not None:
            rows.append(replace(
                evidence(
                    day=item.day, component=component, candidate="candidate-a",
                    candidate_hash=candidate_hash,
                ),
                model_artifact_hash=model.artifact_hash,
            ))
    command = BuildDailyStrategyMappingCommand(
        model_artifact_hash=model.artifact_hash,
        candidate_manifest=(("candidate-a", candidate_hash),),
        frozen_component_fingerprints=components,
        calendar=tuple(item.day for item in plan),
        component_assignments=tuple(assigned), evidence_rows=tuple(rows),
        calendar_roles=tuple(item.role for item in plan),
    )
    mapping = BuildDailyStrategyMappingUseCase().execute(command).artifact
    mapping_payload = mapping.canonical_payload()
    mapping_file = {**mapping_payload, "artifact_hash": daily_mapping_artifact_hash(mapping)}
    manifest = {
        "candidate_count": 1, "candidate_ids": ["candidate-a"],
        "ordered_definition_hashes": [["candidate-a", candidate_hash]],
        "candidate_universe_hash": candidate_universe_hash(("candidate-a",)),
        "entries": [{"candidate_id": "candidate-a", "definition_hash": candidate_hash}],
    }
    manifest["manifest_hash"] = _hash(manifest)

    evidence_root = {}
    for phase in ("mapping_fit", "validation"):
        interval = getattr(ThreeDayDailyResearchProfile().fold, phase)
        phase_rows = [
            item for item in rows
            if interval.start_at <= item.outcome_start_at < interval.end_at
        ]
        phase_assignments = [item.component_fingerprint for item in phase_rows]
        ledger_path = tmp_path / f"evidence-{phase.replace('_', '-')}.jsonl"
        ledger_lines = [
            {
                "run_identity": "f" * 64, "phase": phase,
                "outcome_start_at": item.outcome_start_at.isoformat(),
                "component_fingerprint": item.component_fingerprint,
                "candidate_id": item.candidate_id, "evidence": item.canonical_payload(),
            }
            for item in phase_rows
        ]
        ledger_path.write_bytes(b"".join(canonical_json_bytes(item) for item in ledger_lines))
        evidence_root[phase] = {
            "phase": phase, "ledger_path": str(ledger_path),
            "ledger_hash": hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
            "archive_descriptors": [], "archive_descriptor_hash": _hash([]),
            "component_assignments": phase_assignments,
            "assignment_hash": _hash(phase_assignments),
            "calendar_rows": [{
                "outcome_start_at": item.outcome_start_at.isoformat().replace("+00:00", "Z"),
                "component_fingerprint": item.component_fingerprint, "role": phase,
            } for item in phase_rows],
            "daily_evidence_rows": [item.canonical_payload() for item in phase_rows],
        }
    baseline = select_global_fixed_daily_candidate(
        candidate_manifest=command.candidate_manifest, evidence_rows=tuple(rows)
    ).canonical_payload()
    model_payload = json.loads(model.to_json())
    pretest = {
        "model": model_payload, "candidate_manifest": manifest,
        "evidence": {"mapping": evidence_root["mapping_fit"], "validation": evidence_root["validation"]},
        "mapping": mapping_file, "global_fixed_baseline": baseline,
        "profile": {"profile_id": "three-day-daily-k4-v1"}, "chronology": {},
    }
    report = {
        "schema_version": "three-day-daily-k4-report-v1",
        "source_verification": {"raw_kline_root": str(raw_root), "feature_cache_root": str(tmp_path / "cache")},
        "candidate_manifest": manifest, "model_artifact": model_payload,
        "evidence": evidence_root, "strict_mapping": mapping_payload,
        "strict_mapping_artifact_hash": mapping_file["artifact_hash"],
        "global_fixed_baseline": baseline,
        "pre_test_freeze_payload": pretest, "pre_test_freeze_hash": _hash(pretest),
        "test_provenance": {"pre_test_freeze_hash": _hash(pretest)},
        "test_comparisons": {},
    }
    model_path, mapping_path = tmp_path / "publication-model.json", tmp_path / "publication-mapping.json"
    publication = render_three_day_publication(
        report=report, model_json=model.to_json().encode(),
        mapping_json=canonical_json_bytes(mapping_file),
    )
    inputs = AuditInputs(
        report=tmp_path / "publication.json", markdown=tmp_path / "publication.md",
        model=model_path, mapping=mapping_path,
    )
    inputs.report.write_bytes(publication.report_json)
    inputs.markdown.write_bytes(publication.report_markdown)
    inputs.model.write_bytes(publication.model_json)
    inputs.mapping.write_bytes(publication.mapping_json)

    monkeypatch.setattr(module, "_load_cluster_fit_vectors", lambda root, frozen=(): ((object(),), tuple(provenance)))
    monkeypatch.setattr(
        module, "_fit_cluster_model",
        lambda *args: type("Outcome", (), {"artifact": model, "rejection_reasons": ()})(),
    )
    monkeypatch.setattr(
        module, "_load_phase_vectors",
        lambda phase, root, provenance=(): (
            tuple(SimpleNamespace(fingerprint=value) for value in evidence_root[phase]["component_assignments"]),
            (),
        ),
    )
    monkeypatch.setattr(
        ThreeDayK4ModelArtifact, "assign",
        lambda self, vector: SimpleNamespace(fingerprint=vector.fingerprint),
    )
    def replay_phase(**values):
        bundle = values["bundle"]
        actual = module._load_actual_ledger_rows(values["phase"], bundle, None, values["failures"])
        replayed = list(bundle["daily_evidence_rows"])
        module._compare_phase_reconstruction(
            values["phase"], bundle, actual, replayed,
            bundle["component_assignments"], values["failures"],
        )
        return replayed
    monkeypatch.setattr(module, "_replay_phase_from_raw", replay_phase)
    monkeypatch.setattr(module, "_replay_untouched_test", lambda *args, **kwargs: None)

    result = audit_three_day_k4_daily_mapping(
        inputs, candidate_manifest_factory=lambda: copy.deepcopy(manifest)
    )

    assert result["passed"] is True, result["failures"]


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("archive", lambda r: r["model_artifact"]["source_provenance"][0].__setitem__("sha256", "0" * 64)),
        ("feature vector", lambda r: r["model_artifact"]["fit_input_vectors"][0]["values"].__setitem__(0, 9.0)),
        ("model parameter", lambda r: r["model_artifact"]["means"][0].__setitem__(0, 9.0)),
        ("fingerprint", lambda r: r["model_artifact"]["component_fingerprints"].__setitem__(0, "f" * 24)),
        ("candidate hash", lambda r: r["candidate_manifest"]["entries"][0].__setitem__("definition_hash", "2" * 64)),
        ("evidence return", lambda r: r["evidence"]["mapping_fit"]["daily_evidence_rows"][0].__setitem__("net_return_ratio", "0.5")),
        ("evidence trade", lambda r: r["evidence"]["mapping_fit"]["daily_evidence_rows"][0]["trades"][0].__setitem__("net_pnl", "3")),
        ("assignment", lambda r: r["evidence"]["mapping_fit"]["component_assignments"].__setitem__(0, "b" * 24)),
        ("corrected LCB", lambda r: r["strict_mapping"]["candidate_assessments"][0].__setitem__("corrected_lower_bound_ratio", "0.9")),
        ("mapping winner", lambda r: r["strict_mapping"]["entries"][0].__setitem__("decision", "cash")),
        ("freeze", lambda r: r.__setitem__("pre_test_freeze_hash", "0" * 64)),
        ("Test transition", lambda r: r["test_comparisons"]["k4_dynamic_active_strategy_opposite_exit"]["transitions"][0].__setitem__("to", "cash")),
        ("opposite exit", lambda r: r["test_comparisons"]["k4_dynamic_active_strategy_opposite_exit"].__setitem__("active_strategy_opposite_exit_count", 0)),
        ("equity", lambda r: r["test_comparisons"]["k4_dynamic_active_strategy_opposite_exit"]["equity_curve"][1].__setitem__("equity", "50")),
        ("baseline", lambda r: r["global_fixed_baseline"].__setitem__("candidate_id", "forged")),
        ("output hash", lambda r: r["output_hashes"].__setitem__("model", "0" * 64)),
    ],
)
def test_audit_rejects_each_mutation_one_at_a_time(tmp_path, label, mutate) -> None:
    inputs, original = _write_bundle(tmp_path)
    report = copy.deepcopy(original)
    mutate(report)
    inputs.report.write_bytes(canonical_json_bytes(report))

    result = audit_three_day_k4_daily_mapping(inputs, candidate_manifest_factory=_factory(original))

    assert result["passed"] is False, label
    assert result["failures"], label


def test_audit_proves_test_timestamps_are_absent_from_pretest_lineage(tmp_path) -> None:
    inputs, report = _write_bundle(tmp_path)
    report["pre_test_freeze_payload"]["evidence"]["mapping_fit"]["calendar_rows"][0][
        "outcome_start_at"
    ] = "2026-04-05T00:00:00Z"
    report["pre_test_freeze_hash"] = _hash(report["pre_test_freeze_payload"])
    inputs.report.write_bytes(canonical_json_bytes(report))

    result = audit_three_day_k4_daily_mapping(inputs, candidate_manifest_factory=_factory(report))

    assert result["passed"] is False
    assert any("Test timestamp" in failure for failure in result["failures"])


def test_leakage_audit_allows_only_canonical_test_interval_metadata() -> None:
    payload = {
        "model": {"profile": {"fold": {"test": {
            "start_at": "2026-04-04T00:00:00Z", "end_at": "2026-07-01T00:00:00Z"
        }}}},
        "mapping": {"research_profile": {"fold": {"test": {
            "start_at": "2026-04-04T00:00:00Z", "end_at": "2026-07-01T00:00:00Z"
        }}}},
    }
    report = {
        "pre_test_freeze_payload": payload,
        "pre_test_freeze_hash": _hash(payload),
        "test_provenance": {"pre_test_freeze_hash": _hash(payload)},
    }
    failures: list[str] = []

    _audit_freeze(report, failures)

    assert failures == []


@pytest.mark.parametrize("key", ("day", "leaked_day", "arbitrary_string"))
def test_leakage_audit_rejects_test_date_values_under_any_key(key: str) -> None:
    payload = {"evidence": {key: "2026-04-05"}}
    report = {
        "pre_test_freeze_payload": payload,
        "pre_test_freeze_hash": _hash(payload),
        "test_provenance": {"pre_test_freeze_hash": _hash(payload)},
    }
    failures: list[str] = []

    _audit_freeze(report, failures)

    assert any("Test timestamp" in failure for failure in failures)


def test_leakage_audit_rejects_test_date_nested_below_whitelisted_metadata() -> None:
    payload = {
        "model": {"profile": {"fold": {"test": {
            "start_at": "2026-04-04T00:00:00Z",
            "end_at": "2026-07-01T00:00:00Z",
            "injected": {"day": "2026-04-05"},
        }}}},
    }
    report = {
        "pre_test_freeze_payload": payload,
        "pre_test_freeze_hash": _hash(payload),
        "test_provenance": {"pre_test_freeze_hash": _hash(payload)},
    }
    failures: list[str] = []

    _audit_freeze(report, failures)

    assert any("Test timestamp" in failure for failure in failures)
