from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from scripts.audit_three_day_k4_daily_mapping import (
    AuditInputs,
    _audit_mapping,
    _audit_model,
    _audit_freeze,
    _reconstruct_cluster_fit,
    _compare_phase_reconstruction,
    _load_verified_minute_market,
    audit_three_day_k4_daily_mapping,
    canonical_json_bytes,
)
from tests.infrastructure.regime.test_three_day_k4_model_artifact import _artifact


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value, newline=False)).hexdigest()


def _write_minute_zip(path: Path, start, count: int, *, skip_index: int | None = None):
    rows = []
    for index in range(count):
        if index == skip_index:
            continue
        opened = start + __import__("datetime").timedelta(minutes=index)
        opened_ms = int(opened.timestamp() * 1000)
        price = 100 + (index % 17) / 100
        rows.append(
            f"{opened_ms},{price},{price + 1},{price - 1},{price},1,"
            f"{opened_ms + 59999},100,1,0.5,50,0\n"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(path.stem + ".csv", "".join(rows))
    raw = path.read_bytes()
    return {
        "path": str(path), "source_url": f"https://example.invalid/{path.name}",
        "sha256": hashlib.sha256(raw).hexdigest(), "expected_sha256": hashlib.sha256(raw).hexdigest(),
        "byte_count": len(raw), "member_name": path.stem + ".csv",
    }


def _write_complete_feature_cache(root: Path, start, end, manifest) -> None:
    requirements: dict[str, set[str]] = {}
    for entry in manifest.entries:
        for alternative in entry.required_feature_alternatives:
            for name, sources in alternative:
                requirements.setdefault(name, set()).update(sources)
    selected_sources = {name: sorted(sources)[0] for name, sources in requirements.items()}
    sources = sorted(set(selected_sources.values()))
    rows = []
    cursor = start
    from datetime import timedelta
    while cursor < end:
        measured = cursor + timedelta(minutes=1)
        stamp = measured.isoformat()
        rows.append({
            "symbol": "BTCUSDT", "timeframe": "1m", "measured_at": stamp,
            "unavailable_sources": [],
            "features": {
                name: {
                    "value": "1", "source": source,
                    "observed_at": stamp, "available_at": stamp,
                }
                for name, source in selected_sources.items()
            },
        })
        cursor = measured
    cache = root / "complete.jsonl"
    root.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    identity = {
        "schema_version": "binance-usdm-market-features-v1",
        "start": start.isoformat(), "end": end.isoformat(), "sources": sources,
    }
    payload = {
        "symbol": "BTCUSDT", "timeframe": "1m", "row_count": len(rows),
        "output_hash": hashlib.sha256(cache.read_bytes()).hexdigest(),
        "cache_identity_hash": _hash(identity), "input_hashes": {}, "raw_hashes": {},
        "cache_identity": identity,
        "source_coverage": {source: {"available_rows": len(rows)} for source in sources},
        "provenance": {"fixture": "complete-offline"},
    }
    (root / "complete.manifest.json").write_bytes(canonical_json_bytes(payload, newline=False))


def test_verified_minute_market_parses_real_local_zip_and_fails_closed(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    start = datetime(2025, 7, 4, tzinfo=timezone.utc)
    archive = tmp_path / "raw" / "BTCUSDT" / "BTCUSDT-1m-2025-07.zip"
    descriptor = _write_minute_zip(archive, start, 5)

    market = _load_verified_minute_market(
        [descriptor], raw_root=tmp_path / "raw", start_at=start,
        end_at=start + timedelta(minutes=5),
    )

    assert len(market.candles) == 5
    assert market.candles[0].opened_at == start
    assert market.candles[-1].closed_at == start + timedelta(minutes=5)

    for mutation in ("missing", "hash", "gap"):
        changed = copy.deepcopy(descriptor)
        if mutation == "missing":
            Path(changed["path"]).unlink()
        elif mutation == "hash":
            changed["sha256"] = "0" * 64
        else:
            changed = _write_minute_zip(archive, start, 5, skip_index=2)
        with pytest.raises(ValueError, match="missing|hash|gap|cover"):
            _load_verified_minute_market(
                [changed], raw_root=tmp_path / "raw", start_at=start,
                end_at=start + timedelta(minutes=5),
            )
        if mutation == "missing":
            descriptor = _write_minute_zip(archive, start, 5)


def test_real_one_day_459_candidate_phase_replay_reconstructs_published_ledger(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal

    import scripts.audit_three_day_k4_daily_mapping as audit_module
    from scripts.chart_regime_strategy_mapping import (
        BACKTEST_ENGINE_VERSION,
        ThreeDayPhaseEvidence,
        _canonical_hash,
        _select_feature_cache,
        build_three_day_daily_candidate_manifest,
        canonical_daily_evidence_replay_contract,
    )
    from scripts.scheduler_driven_scalping_backtest import required_warmup_candles
    from src.application.services.daily_strategy_evidence import (
        AppendOnlyEvidenceLedger,
        DAILY_EVIDENCE_CODE_VERSION,
        DAILY_EVIDENCE_KEY_FIELDS,
        DAILY_EVIDENCE_SCHEMA_VERSION,
        DailyEvidenceRunIdentity,
        feature_provider_config_hash,
        market_snapshot_hash,
        run_daily_strategy_evidence,
    )
    from src.domain.regime import ThreeDayDailyResearchProfile
    from loguru import logger

    logger.remove()

    day = datetime(2025, 7, 7, tzinfo=timezone.utc)
    model = _artifact()
    manifest = build_three_day_daily_candidate_manifest(
        include_deferred=True, expected_count=459
    )
    raw_root = tmp_path / "raw"
    archive = raw_root / "BTCUSDT" / "BTCUSDT-1m-2025-07.zip"
    descriptor = _write_minute_zip(archive, day - timedelta(days=3), 4 * 24 * 60)
    canonical_url = (
        "https://data.binance.vision/data/futures/um/monthly/klines/"
        "BTCUSDT/1m/BTCUSDT-1m-2025-07.zip"
    )
    descriptor.update({
        "url": canonical_url, "source_url": canonical_url, "period": "2025-07",
        "bytes": descriptor["byte_count"], "member_identity": descriptor["member_name"],
    })

    vectors, vector_provenance = audit_module._load_phase_vectors(
        "mapping_fit", raw_root, [descriptor],
        start=day - timedelta(days=3), end=day + timedelta(days=1),
    )
    assignment = model.assign(vectors[0]).fingerprint
    candidates = tuple(entry.candidate for entry in manifest.entries)
    market_start = day - timedelta(minutes=required_warmup_candles(candidates, None))
    market_end = day + timedelta(days=1)
    market = _load_verified_minute_market(
        [descriptor], raw_root=raw_root, start_at=market_start, end_at=market_end,
    )
    cache_root = tmp_path / "features"
    _write_complete_feature_cache(cache_root, market_start, market_end, manifest)
    provider, cache_provenance = _select_feature_cache(
        cache_root, required_start=market_start, required_end=market_end,
        verify_full_file=True,
    )
    feature_provenance = getattr(provider, "feature_provenance", cache_provenance)
    source_coverage = getattr(provider, "feature_source_coverage", {})
    unavailable = getattr(provider, "feature_unavailable_counts", {})
    profile = ThreeDayDailyResearchProfile()
    interval = profile.fold.mapping_fit
    identity = DailyEvidenceRunIdentity(
        profile_id=profile.profile_id,
        feature_schema_version=vectors[0].schema_version,
        phase="mapping_fit", phase_start_at=interval.start_at, phase_end_at=interval.end_at,
        model_artifact_hash=model.artifact_hash,
        candidate_manifest_hash=manifest.manifest_hash,
        candidate_universe_hash=manifest.candidate_universe_hash,
        ordered_candidate_definition_hashes=manifest.ordered_definition_hashes,
        market_data_hash=market_snapshot_hash(market),
        feature_cache_hash=getattr(provider, "feature_cache_hash", None),
        feature_config_hash=feature_provider_config_hash(provider),
        feature_cache_schema_version=str(getattr(provider, "feature_cache_schema_version", "none-v1")),
        feature_provenance_hash=_canonical_hash(feature_provenance),
        feature_source_coverage_hash=_canonical_hash(source_coverage),
        feature_unavailable_counts_hash=_canonical_hash(unavailable),
        engine_version=BACKTEST_ENGINE_VERSION,
        cost_model=canonical_daily_evidence_replay_contract().cost_model,
        symbol="BTCUSDT", timeframe="1m", initial_equity=Decimal("10000"),
        code_version=DAILY_EVIDENCE_CODE_VERSION,
        evidence_schema_version=DAILY_EVIDENCE_SCHEMA_VERSION,
    )
    ledger_path = tmp_path / "mapping-fit.jsonl"
    rows = run_daily_strategy_evidence(
        manifest=manifest, phase="mapping_fit", outcome_start_at=day,
        component_fingerprint=assignment, market=market,
        market_feature_provider=provider, run_identity=identity,
        ledger=AppendOnlyEvidenceLedger(ledger_path, DAILY_EVIDENCE_KEY_FIELDS),
        replay_contract=canonical_daily_evidence_replay_contract(),
    )
    provider.close()
    phase = ThreeDayPhaseEvidence(
        "mapping_fit", tuple(rows), (day,), (assignment,), identity, ledger_path,
        hashlib.sha256(ledger_path.read_bytes()).hexdigest(), (descriptor,),
        tuple(vector_provenance), dict(feature_provenance), dict(source_coverage),
        dict(unavailable),
    ).canonical_payload()
    report = {
        "source_verification": {
            "raw_kline_root": str(raw_root), "feature_cache_root": str(cache_root),
        },
        "evidence": {"mapping_fit": phase},
    }
    publication = audit_module.canonical_json_bytes(report, newline=False)
    parsed_report = json.loads(publication)
    failures: list[str] = []

    replayed = audit_module._replay_phase_from_raw(
        phase="mapping_fit", bundle=parsed_report["evidence"]["mapping_fit"],
        report=parsed_report, model_artifact=model, manifest=manifest,
        ledger_override=None, failures=failures,
    )

    assert failures == []
    assert len(replayed) == 459
    assert replayed == phase["daily_evidence_rows"]

    tampered = copy.deepcopy(parsed_report["evidence"]["mapping_fit"])
    tampered["daily_evidence_rows"][0]["final_equity"] = "9999"
    tamper_failures: list[str] = []
    audit_module._compare_phase_reconstruction(
        "mapping_fit", tampered,
        AppendOnlyEvidenceLedger(ledger_path, DAILY_EVIDENCE_KEY_FIELDS).load(),
        replayed, [assignment], tamper_failures,
    )
    assert any("ledger/report evidence" in failure for failure in tamper_failures)
    assert any("raw scheduler-replayed evidence" in failure for failure in tamper_failures)


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
    report["output_binding_schema_version"] = "legacy-output-hashes-v1"
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
    import scripts.chart_regime_strategy_mapping as production

    published = json.loads(_artifact().to_json())
    calls = []
    sentinel_vectors = (object(),)
    sentinel_provenance = ({"raw": "verified"},)
    monkeypatch.setattr(
        module, "_load_cluster_fit_vectors",
        lambda raw_root, provenance=(): calls.append(("load", raw_root)) or (sentinel_vectors, sentinel_provenance),
    )

    artifact = type("Artifact", (), {"canonical_payload": lambda self: published})()

    def refit(vectors, provenance, code_hash):
        calls.append(("fit", vectors, provenance, code_hash))
        return artifact, None

    monkeypatch.setattr(module, "_independently_recompute_k4", refit)
    monkeypatch.setattr(
        production, "fit_fold_local_three_day_k4_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("production fit/gate conclusion must be ignored")
        ),
    )
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

    artifact = type("Artifact", (), {"canonical_payload": lambda self: original})()
    monkeypatch.setattr(
        module, "_independently_recompute_k4", lambda *args: (artifact, None)
    )
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
    report.pop("output_binding_schema_version")
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


def test_auditor_independently_accepts_exact_model_gate_terminal_branch(
    monkeypatch, tmp_path
) -> None:
    import scripts.audit_three_day_k4_daily_mapping as audit_module
    import scripts.chart_regime_strategy_mapping as experiment

    attempt_payload = {
        "schema_version": "three-day-k4-model-attempt-v1",
        "status": "failed-model-gates",
        "profile_id": "three-day-daily-k4-v1",
        "model_config": {
            "model_type": "gmm", "cluster_count": 4, "covariance_type": "diag",
            "random_seed": 20260714, "regularization": "0.000001",
        },
        "fit_interval": {
            "start_at": "2021-01-01T00:00:00+00:00",
            "end_at": "2025-06-30T00:00:00+00:00",
        },
        "source_provenance": [], "fit_input_vector_hash": "b" * 64,
        "fit_input_anchor_count": 1641, "code_provenance_hash": "c" * 64,
        "first_usable_anchor_at": "2021-01-01T00:00:00+00:00",
        "last_usable_anchor_at": "2025-06-29T00:00:00+00:00",
        "source_provenance_hash": _hash([]),
        "feature_names": ["feature"],
        "model_parameters": {
            "converged": True, "iterations": 1, "lower_bound": 0.0,
            "lower_bounds": [0.0], "upper_bounds": [1.0], "medians": [0.5],
            "scales": [1.0], "weights": [0.25] * 4,
            "means": [[0.0]] * 4, "covariances": [[1.0]] * 4,
            "component_fingerprints": [str(index) * 24 for index in range(4)],
        },
        "model_gates": {
            "maximum_matched_centroid_distance": 2.35,
            "maximum_matched_centroid_distance_threshold": 0.5,
            "maximum_matched_centroid_distance_passed": False,
            "passed": False,
        },
        "failed_gate_names": ["maximum_matched_centroid_distance"],
    }
    attempt = {
        **attempt_payload, "attempt_hash": experiment._canonical_hash(attempt_payload),
    }
    args = SimpleNamespace(
        raw_kline_root=tmp_path / "raw", evidence_rows_path=tmp_path / "evidence.jsonl",
        output_json=tmp_path / "report.json", output_markdown=tmp_path / "report.md",
        output_model=tmp_path / "model.json", output_mapping=tmp_path / "mapping.json",
    )
    experiment._publish_model_failure(
        args,
        experiment.ThreeDayModelGateFailure(experiment.ThreeDayK4FitOutcome(
            "failed-model-cash", None, ("maximum_matched_centroid_distance",), attempt,
        )),
    )
    monkeypatch.setattr(
        audit_module, "_reconstruct_failed_model_attempt",
        lambda report, published, failures: copy.deepcopy(attempt),
        raising=False,
    )

    result = audit_three_day_k4_daily_mapping(
        AuditInputs(args.output_json, args.output_markdown, args.output_model, args.output_mapping),
        candidate_manifest_factory=lambda: (_ for _ in ()).throw(
            AssertionError("candidate factory must remain unread")
        ),
    )

    assert result["passed"] is True, result["failures"]
    assert result["checked_counts"] == {
        "raw_inputs": 0, "candidates": 0, "evidence_rows": 0,
        "test_transitions": 0, "test_trades": 0,
    }
    assert result["hashes"]["model_attempt_hash"] == attempt["attempt_hash"]

    original_report = args.output_json.read_bytes()
    original_markdown = args.output_markdown.read_bytes()
    forged_markdown = original_markdown + b"forged but self-hashed\n"
    forged_report = json.loads(original_report)
    forged_report["publication"]["markdown_byte_hash"] = hashlib.sha256(
        forged_markdown
    ).hexdigest()
    args.output_json.write_bytes(
        (json.dumps(forged_report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    )
    args.output_markdown.write_bytes(forged_markdown)
    forged_result = audit_three_day_k4_daily_mapping(
        AuditInputs(args.output_json, args.output_markdown, args.output_model, args.output_mapping),
        candidate_manifest_factory=lambda: {},
    )
    assert forged_result["passed"] is False
    assert any("Markdown independent rerender" in item for item in forged_result["failures"])
    args.output_json.write_bytes(original_report)
    args.output_markdown.write_bytes(original_markdown)

    unexpected_ledger = audit_module._phase_ledger_override(
        args.evidence_rows_path, "mapping_fit"
    )
    unexpected_ledger.parent.mkdir(parents=True, exist_ok=True)
    unexpected_ledger.write_bytes(b"{}\n")
    with_ledger = audit_three_day_k4_daily_mapping(
        AuditInputs(args.output_json, args.output_markdown, args.output_model, args.output_mapping),
        candidate_manifest_factory=lambda: {},
    )
    assert with_ledger["passed"] is False
    assert any("unexpectedly has mapping_fit evidence ledger" in item for item in with_ledger["failures"])


def test_failed_model_refit_rejects_self_consistent_attempt_forgery(
    monkeypatch, tmp_path
) -> None:
    import scripts.audit_three_day_k4_daily_mapping as module

    original = {"attempt_hash": "a" * 64, "source_provenance": []}
    forged = {**original, "attempt_hash": "b" * 64}
    monkeypatch.setattr(
        module, "_load_cluster_fit_vectors", lambda *args: ((object(),), ({},))
    )

    assert not hasattr(module, "_fit_cluster_model")
    monkeypatch.setattr(
        module, "_independently_recompute_model_attempt", lambda *args: original
    )
    failures: list[str] = []

    rebuilt = module._reconstruct_failed_model_attempt(
        {"source_verification": {"raw_kline_root": str(tmp_path)}},
        forged, failures,
    )

    assert rebuilt == original
    assert any("raw-refitted failed K4 model attempt" in item for item in failures)


def test_failed_model_attempt_exact_schema_rejects_recursive_extra_field() -> None:
    import scripts.audit_three_day_k4_daily_mapping as module

    failures: list[str] = []
    module._exact_failed_attempt_schema({
        "schema_version": "three-day-k4-technical-failure-v1",
        "status": "technical_failure", "profile_id": "three-day-daily-k4-v1",
        "model_config": {
            "model_type": "gmm", "cluster_count": 4, "covariance_type": "diag",
            "random_seed": 20260714, "regularization": "0.000001",
        },
        "fit_interval": {"start_at": "a", "end_at": "b"},
        "fit_input_anchor_count": 1, "first_usable_anchor_at": "a",
        "last_usable_anchor_at": "b", "fit_input_vector_hash": "a" * 64,
        "source_provenance": [], "source_provenance_hash": "b" * 64,
        "code_provenance_hash": "c" * 64, "attempt_hash": "d" * 64,
        "technical_failure": {
            "stage": "fit_and_gate", "reason_code": "invalid_scaler",
            "test_results": "forged",
        },
    }, failures)

    assert any("technical failure exact schema" in item for item in failures)


@pytest.mark.parametrize("mutation", ("missing", "ambiguous", "missing_key", "extra_key"))
def test_output_binding_is_exact_and_fail_closed(tmp_path, mutation) -> None:
    inputs, report = _write_bundle(tmp_path)
    if mutation == "missing":
        report.pop("output_hashes")
        report.pop("output_binding_schema_version")
    elif mutation == "ambiguous":
        report["publication"] = {
            "hash_definition": "ambiguous", "report_payload_hash": "0" * 64,
            "model_byte_hash": "0" * 64, "mapping_byte_hash": "0" * 64,
            "markdown_byte_hash": "0" * 64,
        }
    elif mutation == "missing_key":
        report["output_hashes"].pop("markdown")
    else:
        report["output_hashes"]["unexpected"] = "0" * 64
    inputs.report.write_bytes(canonical_json_bytes(report))

    result = audit_three_day_k4_daily_mapping(
        inputs, candidate_manifest_factory=_factory(report)
    )

    assert result["passed"] is False
    assert any("output binding" in failure for failure in result["failures"])


def test_deleted_publication_binding_cannot_hide_tampered_markdown(tmp_path) -> None:
    from scripts.chart_regime_strategy_mapping import render_three_day_publication

    inputs, report = _write_bundle(tmp_path)
    report.pop("output_hashes")
    report.pop("output_binding_schema_version")
    rendered = render_three_day_publication(
        report=report, model_json=inputs.model.read_bytes(),
        mapping_json=inputs.mapping.read_bytes(),
    )
    envelope = json.loads(rendered.report_json)
    envelope.pop("publication")
    inputs.report.write_bytes(canonical_json_bytes(envelope))
    inputs.markdown.write_bytes(rendered.report_markdown + b"\nforged\n")

    result = audit_three_day_k4_daily_mapping(
        inputs, candidate_manifest_factory=_factory(report)
    )

    assert result["passed"] is False
    assert any("output binding" in failure for failure in result["failures"])


@pytest.mark.parametrize(
    "mutation", ("missing_key", "extra_key", "wrong_hash", "wrong_definition")
)
def test_publication_binding_rejects_malformed_or_wrong_companion_hash(
    tmp_path, mutation,
) -> None:
    from scripts.chart_regime_strategy_mapping import render_three_day_publication

    inputs, report = _write_bundle(tmp_path)
    report.pop("output_hashes")
    report.pop("output_binding_schema_version")
    rendered = render_three_day_publication(
        report=report, model_json=inputs.model.read_bytes(),
        mapping_json=inputs.mapping.read_bytes(),
    )
    envelope = json.loads(rendered.report_json)
    if mutation == "missing_key":
        envelope["publication"].pop("markdown_byte_hash")
    elif mutation == "extra_key":
        envelope["publication"]["unexpected"] = "0" * 64
    elif mutation == "wrong_hash":
        envelope["publication"]["markdown_byte_hash"] = "0" * 64
    else:
        envelope["publication"]["hash_definition"] = "forged hash semantics"
    inputs.report.write_bytes(canonical_json_bytes(envelope))
    inputs.markdown.write_bytes(rendered.report_markdown)
    inputs.model.write_bytes(rendered.model_json)
    inputs.mapping.write_bytes(rendered.mapping_json)

    result = audit_three_day_k4_daily_mapping(
        inputs, candidate_manifest_factory=_factory(report)
    )

    assert result["passed"] is False
    assert any(
        "output binding" in failure or "output hash mismatch" in failure
        or "hash_definition" in failure
        for failure in result["failures"]
    )


def test_audit_reads_each_publication_input_once(monkeypatch, tmp_path) -> None:
    inputs, report = _write_bundle(tmp_path)
    paths = {path.resolve() for path in (
        inputs.report, inputs.model, inputs.mapping, inputs.markdown,
    )}
    original = Path.read_bytes
    counts = {path: 0 for path in paths}

    def read_once(path):
        resolved = path.resolve()
        if resolved in counts:
            counts[resolved] += 1
            if counts[resolved] > 1:
                raise OSError("publication input was re-read after the audit snapshot")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read_once)

    result = audit_three_day_k4_daily_mapping(
        inputs, candidate_manifest_factory=_factory(report)
    )

    assert result["passed"] is True, result["failures"]
    assert set(counts.values()) == {1}


def test_mid_audit_file_replacement_cannot_change_bound_snapshot(
    monkeypatch, tmp_path,
) -> None:
    import scripts.audit_three_day_k4_daily_mapping as module

    inputs, report = _write_bundle(tmp_path)
    original_markdown = inputs.markdown.read_bytes()
    expected_hash = hashlib.sha256(original_markdown).hexdigest()
    original_audit_model = module._audit_model

    def replace_after_snapshot(*args, **kwargs):
        inputs.markdown.write_bytes(b"forged after audit snapshot\n")
        return original_audit_model(*args, **kwargs)

    monkeypatch.setattr(module, "_audit_model", replace_after_snapshot)

    result = audit_three_day_k4_daily_mapping(
        inputs, candidate_manifest_factory=_factory(report)
    )

    assert result["passed"] is True, result["failures"]
    assert result["hashes"]["markdown_file_hash"] == expected_hash
    assert hashlib.sha256(inputs.markdown.read_bytes()).hexdigest() != expected_hash


def test_production_daily_evidence_path_indexes_phase_once_and_passes_bounded_windows(
    monkeypatch,
) -> None:
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    import scripts.chart_regime_strategy_mapping as module
    from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe

    start = datetime(2025, 7, 1, tzinfo=timezone.utc)
    base = tuple(Candle(
        symbol=Symbol("BTC", "USDT"), timeframe=Timeframe(1, "m"),
        opened_at=start + timedelta(minutes=index),
        closed_at=start + timedelta(minutes=index + 1),
        open_price=Decimal("100"), high_price=Decimal("101"),
        low_price=Decimal("99"), close_price=Decimal("100"), volume=Decimal("1"),
    ) for index in range(15 * 24 * 60))

    class CountedCandle:
        accesses = 0

        def __init__(self, candle):
            self.candle = candle

        @property
        def opened_at(self):
            type(self).accesses += 1
            return self.candle.opened_at

        def __getattr__(self, name):
            return getattr(self.candle, name)

    market = MarketSnapshot(tuple(CountedCandle(candle) for candle in base))
    CountedCandle.accesses = 0
    days = tuple(start + timedelta(days=index) for index in range(3, 15))
    warmup = 1442

    _timeline, slices = module._build_verified_phase_daily_slices(market, days, warmup)
    manifest = module.build_three_day_daily_candidate_manifest(
        include_deferred=True, expected_count=459
    )
    observed = []

    def run_daily(**values):
        observed.append((len(values["manifest"].entries), len(values["market"].market.candles)))
        return ()

    monkeypatch.setattr(module, "run_daily_strategy_evidence", run_daily)
    module._run_verified_phase_daily_evidence(
        manifest=manifest, phase="mapping_fit", calendar=days,
        assignments=("a" * 24,) * len(days), daily_markets=slices,
        provider=object(), identity=object(), ledger=object(),
    )

    bounded = warmup + 1440
    assert tuple(len(item.market.candles) for item in slices) == (bounded,) * len(days)
    assert observed == [(459, bounded)] * len(days)
    assert CountedCandle.accesses <= 4 * len(base) + len(days) * (3 * bounded + 4)
    candidate_phase_scan = 459 * len(days) * len(base)
    assert CountedCandle.accesses < candidate_phase_scan / 500


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
        module, "_independently_recompute_k4", lambda *args: (model, None)
    )
    monkeypatch.setattr(
        module, "_load_phase_vectors",
        lambda phase, root, provenance=(), **kwargs: (
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
