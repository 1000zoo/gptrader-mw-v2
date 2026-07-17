from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.audit_three_day_k4_daily_mapping import (
    AuditInputs,
    _audit_mapping,
    _audit_model,
    _audit_freeze,
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


def test_auditor_rebuilds_real_task7_mapping_schema_from_daily_evidence() -> None:
    from src.application.usecases.regime.build_daily_strategy_mapping_usecase import (
        BuildDailyStrategyMappingUseCase,
    )
    from src.domain.regime import daily_mapping_artifact_hash
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
