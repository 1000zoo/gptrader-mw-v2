"""Independent verifier for the BTCUSDT three-day K4 daily-mapping publication.

The auditor deliberately consumes bytes and raw lineage again.  It does not call
the experiment orchestrator and never accepts a report's pass/fail summaries as
evidence.  Pure artifact parsers, candidate factories and accounting math are
reused so that the independently reconstructed values have exactly the same
domain semantics as the researched system.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class AuditInputs:
    report: Path
    markdown: Path
    model: Path
    mapping: Path

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            object.__setattr__(self, field, Path(getattr(self, field)))


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite decimal")
        return str(value.normalize()) if value else "0"
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite float")
    return value


def canonical_json_bytes(value: object, *, newline: bool = True) -> bytes:
    encoded = json.dumps(
        _canonical(value), allow_nan=False, ensure_ascii=True,
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return encoded + (b"\n" if newline else b"")


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value, newline=False)).hexdigest()


def _read_canonical_json(path: Path, failures: list[str], label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
        if not isinstance(value, dict):
            raise ValueError("top-level value is not an object")
        accepted = {canonical_json_bytes(value), canonical_json_bytes(value, newline=False)}
        if label == "report":
            accepted.add(
                (json.dumps(
                    value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
                ) + "\n").encode("utf-8")
            )
        if raw not in accepted:
            failures.append(f"{label} bytes are not canonical JSON")
        return value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        failures.append(f"{label} could not be read: {error}")
        return {}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _default_manifest() -> Mapping[str, object]:
    from scripts.chart_regime_strategy_mapping import (
        _freeze_boundary_payload,
        build_three_day_daily_candidate_manifest,
    )

    return _freeze_boundary_payload(
        build_three_day_daily_candidate_manifest(expected_count=459)
    )


def _same(expected: object, actual: object, failures: list[str], label: str) -> None:
    if _canonical(expected) != _canonical(actual):
        failures.append(f"{label} mismatch")


def _decimal(value: object, label: str, failures: list[str]) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        failures.append(f"{label} is not a decimal")
        return None
    if not result.is_finite():
        failures.append(f"{label} is nonfinite")
        return None
    return result


def _audit_raw_inputs(
    model: Mapping[str, object], report: Mapping[str, object], failures: list[str]
) -> int:
    descriptors = model.get("source_provenance", ())
    if not isinstance(descriptors, list):
        failures.append("model source provenance is not a list")
        return 0
    report_sources = report.get("source_verification", {})
    if isinstance(report_sources, Mapping) and "raw_inputs" in report_sources:
        _same(descriptors, report_sources["raw_inputs"], failures, "raw source lineage")
    checked = 0
    for index, descriptor in enumerate(descriptors):
        if not isinstance(descriptor, Mapping):
            failures.append(f"raw input {index} descriptor is invalid")
            continue
        raw_path = descriptor.get("local_path")
        if raw_path is None:
            # Real artifacts bind immutable archive URL/member/hash.  The loader
            # may not preserve a local_path, so locate the downloaded basename
            # beneath the verified raw root without trusting a report summary.
            source_root = report_sources.get("raw_kline_root") if isinstance(report_sources, Mapping) else None
            url = descriptor.get("url") or descriptor.get("source_url")
            if source_root and isinstance(url, str):
                matches = tuple(Path(str(source_root)).rglob(Path(url).name))
                raw_path = str(matches[0]) if len(matches) == 1 else None
        if raw_path is None:
            failures.append(f"raw input {index} has no uniquely resolvable local file")
            continue
        path = Path(str(raw_path))
        try:
            raw = path.read_bytes()
        except OSError as error:
            failures.append(f"raw input {index} could not be read: {error}")
            continue
        reported_bytes = descriptor.get("bytes", descriptor.get("byte_count"))
        if reported_bytes is not None and reported_bytes != len(raw):
            failures.append(f"raw input {index} byte count mismatch")
        if hashlib.sha256(raw).hexdigest() != descriptor.get("sha256"):
            failures.append(f"raw input {index} SHA-256 mismatch")
        checked += 1
    expected_combined = model.get("source_combined_hash")
    if expected_combined is not None and expected_combined != _hash({"archives": descriptors}):
        failures.append("model source combined hash mismatch")
    return checked


def _audit_model(
    report_model: Mapping[str, object], file_model: Mapping[str, object], failures: list[str]
) -> object | None:
    _same(file_model, report_model, failures, "report/model artifact binding")
    supplied = file_model.get("artifact_hash")
    unhashed = {key: value for key, value in file_model.items() if key != "artifact_hash"}
    if supplied != _hash(unhashed):
        failures.append("model artifact hash mismatch")
    vectors = file_model.get("fit_input_vectors")
    if vectors is not None and file_model.get("fit_input_vector_hash") != _hash(vectors):
        failures.append("model fit-input feature-vector hash mismatch")
    components = file_model.get("component_fingerprints")
    if "component_fingerprint_hash" in file_model and file_model.get("component_fingerprint_hash") != _hash(components):
        failures.append("model component fingerprint hash mismatch")
    parsed = None
    if file_model.get("artifact_version") == "three-day-k4-model-v2":
        try:
            from src.infrastructure.regime.three_day_k4_model_artifact import ThreeDayK4ModelArtifact

            parsed = ThreeDayK4ModelArtifact.from_json(canonical_json_bytes(file_model, newline=False))
        except (TypeError, ValueError) as error:
            failures.append(f"model parameters/fingerprints are invalid: {error}")
    else:
        means, covariances, weights = (
            file_model.get("means"), file_model.get("covariances"), file_model.get("weights")
        )
        if not all(isinstance(item, list) and len(item) == 4 for item in (means, covariances)) or not isinstance(weights, list) or len(weights) != 4:
            failures.append("model parameters do not describe K4")
    return parsed


def _audit_manifest(
    report: Mapping[str, object], factory: Callable[[], Mapping[str, object]], failures: list[str]
) -> Mapping[str, object]:
    manifest = report.get("candidate_manifest", {})
    try:
        rebuilt = factory()
    except Exception as error:
        failures.append(f"candidate factory reconstruction failed: {error}")
        return {}
    _same(rebuilt, manifest, failures, "candidate manifest")
    if isinstance(manifest, Mapping):
        base = {key: value for key, value in manifest.items() if key != "manifest_hash"}
        if "manifest_hash" in manifest and manifest.get("manifest_hash") != _hash(base):
            # The production manifest uses its domain canonical identity rather
            # than this generic envelope; equality to a fresh factory remains
            # authoritative there.  Generic fixtures use the envelope hash.
            if rebuilt != manifest:
                failures.append("candidate manifest hash mismatch")
    return manifest if isinstance(manifest, Mapping) else {}


def _gaussian_assignment(model: Mapping[str, object], values: Sequence[object]) -> str | None:
    means = model.get("means")
    covariances = model.get("covariances")
    weights = model.get("weights")
    numeric = model.get("numeric_index_to_fingerprint")
    if not all(isinstance(item, list) for item in (means, covariances, weights)) or not isinstance(numeric, Mapping):
        return None
    try:
        x = [float(value) for value in values]
        scores = []
        for weight, mean, covariance in zip(weights, means, covariances):
            score = math.log(float(weight)) - 0.5 * sum(
                math.log(2 * math.pi * float(var)) + (value - float(mu)) ** 2 / float(var)
                for value, mu, var in zip(x, mean, covariance)
            )
            scores.append(score)
        return str(numeric[str(max(range(len(scores)), key=scores.__getitem__))])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _audit_trade(trade: Mapping[str, object], failures: list[str], prefix: str) -> Decimal | None:
    values = {
        name: _decimal(trade.get(name), f"{prefix} {name}", failures)
        for name in ("entry_price", "exit_price", "quantity", "gross_pnl", "fee_paid", "net_pnl")
    }
    if any(value is None for value in values.values()):
        return None
    entry, exit_price, quantity = values["entry_price"], values["exit_price"], values["quantity"]
    expected_gross = (
        (exit_price - entry) * quantity
        if trade.get("direction") == "long" else (entry - exit_price) * quantity
    )
    if values["gross_pnl"] != expected_gross:
        failures.append(f"{prefix} gross PnL mismatch")
    if values["net_pnl"] != values["gross_pnl"] - values["fee_paid"]:
        failures.append(f"{prefix} net PnL mismatch")
    return values["net_pnl"]


def _audit_evidence(
    report: Mapping[str, object], model: Mapping[str, object], parsed_model: object | None,
    failures: list[str]
) -> tuple[int, list[Mapping[str, object]]]:
    evidence_root = report.get("evidence", {})
    if not isinstance(evidence_root, Mapping):
        failures.append("evidence root is invalid")
        return 0, []
    checked = 0
    all_rows: list[Mapping[str, object]] = []
    for phase, bundle in sorted(evidence_root.items()):
        if not isinstance(bundle, Mapping):
            failures.append(f"{phase} evidence bundle is invalid")
            continue
        assignments = bundle.get("component_assignments", [])
        if bundle.get("assignment_hash") != _hash(assignments):
            failures.append(f"{phase} assignment hash mismatch")
        archives = bundle.get("archive_descriptors", [])
        if "archive_descriptor_hash" in bundle and bundle.get("archive_descriptor_hash") != _hash(archives):
            failures.append(f"{phase} archive descriptor hash mismatch")
        for field in (
            "feature_provenance", "feature_source_coverage", "feature_unavailable_counts",
            "vector_provenance",
        ):
            hash_field = field + "_hash"
            if field in bundle and hash_field in bundle and bundle.get(hash_field) != _hash(bundle.get(field)):
                failures.append(f"{phase} {field.replace('_', ' ')} hash mismatch")
        identity = bundle.get("run_identity")
        if isinstance(identity, Mapping) and bundle.get("run_identity_hash") != _hash(identity):
            failures.append(f"{phase} evidence run identity hash mismatch")
        ledger_path = bundle.get("ledger_path")
        if isinstance(ledger_path, str) and bundle.get("ledger_hash") is not None:
            path = Path(ledger_path)
            if not path.is_absolute():
                path = ROOT / path
            try:
                ledger_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                failures.append(f"{phase} evidence ledger could not be read: {error}")
            else:
                if ledger_hash != bundle.get("ledger_hash"):
                    failures.append(f"{phase} evidence ledger hash mismatch")
        rows = bundle.get("daily_evidence_rows", [])
        if "evidence_hash" in bundle and bundle.get("evidence_hash") != _hash(rows):
            failures.append(f"{phase} evidence row hash mismatch")
        features = bundle.get("assignment_features")
        if isinstance(features, list) and isinstance(assignments, list):
            recomputed = [_gaussian_assignment(model, values) for values in features]
            if recomputed != assignments:
                failures.append(f"{phase} component assignment mismatch")
        elif parsed_model is not None and isinstance(assignments, list):
            calendar_for_reload = bundle.get("calendar_rows", [])
            source_verification = report.get("source_verification", {})
            raw_root = (
                source_verification.get("raw_kline_root")
                if isinstance(source_verification, Mapping) else None
            )
            try:
                if not raw_root or not isinstance(calendar_for_reload, list) or not calendar_for_reload:
                    raise ValueError("raw root or calendar is absent")
                days = [
                    datetime.fromisoformat(str(item["outcome_start_at"]).replace("Z", "+00:00"))
                    for item in calendar_for_reload if isinstance(item, Mapping)
                ]
                from datetime import timedelta
                from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
                    load_three_day_feature_history,
                )

                vectors, provenance = load_three_day_feature_history(
                    symbol="BTCUSDT", start=min(days) - timedelta(days=3),
                    end=max(days) + timedelta(days=1), raw_root=Path(str(raw_root)),
                    expected_anchor_count=len(days),
                )
                recomputed = [parsed_model.assign(vector).fingerprint for vector in vectors]
                if recomputed != assignments:
                    failures.append(f"{phase} raw feature/model assignment mismatch")
                if "vector_provenance" in bundle:
                    _same(list(provenance), bundle.get("vector_provenance"), failures, f"{phase} vector provenance")
                if "vector_provenance_hash" in bundle and bundle.get("vector_provenance_hash") != _hash(list(provenance)):
                    failures.append(f"{phase} vector provenance hash mismatch")
            except (OSError, TypeError, ValueError) as error:
                failures.append(f"{phase} raw feature assignment reconstruction failed: {error}")
        calendar_rows = bundle.get("calendar_rows", [])
        if isinstance(calendar_rows, list) and isinstance(assignments, list):
            labels = [item.get("component_fingerprint") for item in calendar_rows if isinstance(item, Mapping)]
            if labels != assignments:
                failures.append(f"{phase} calendar/assignment mismatch")
        if not isinstance(rows, list):
            failures.append(f"{phase} evidence rows are invalid")
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                failures.append(f"{phase} evidence row {index} is invalid")
                continue
            all_rows.append(row)
            if row.get("availability_status") == "unavailable":
                checked += 1
                continue
            initial = _decimal(row.get("initial_equity"), f"{phase} evidence initial equity", failures)
            final = _decimal(row.get("final_equity"), f"{phase} evidence final equity", failures)
            net = _decimal(row.get("net_pnl"), f"{phase} evidence net PnL", failures)
            ratio = _decimal(row.get("net_return_ratio"), f"{phase} evidence return", failures)
            trades = row.get("trades")
            if isinstance(trades, list):
                pnls = [_audit_trade(item, failures, f"{phase} evidence trade") for item in trades if isinstance(item, Mapping)]
                if None not in pnls and net is not None and sum(pnls, Decimal(0)) != net:
                    failures.append(f"{phase} evidence trade total mismatch")
                if row.get("closed_trade_count") != len(trades):
                    failures.append(f"{phase} evidence trade count mismatch")
            elif isinstance(row.get("trade_pnls"), list):
                pnls = [_decimal(item, f"{phase} evidence trade PnL", failures) for item in row["trade_pnls"]]
                if None not in pnls and net is not None and sum(pnls, Decimal(0)) != net:
                    failures.append(f"{phase} evidence trade PnL total mismatch")
            if None not in (initial, final, net, ratio) and initial != 0:
                if final - initial != net or net / initial != ratio:
                    failures.append(f"{phase} evidence return/accounting mismatch")
            checked += 1
    return checked, all_rows


def _winner_key(item: Mapping[str, object]) -> tuple[object, ...]:
    def neg(name: str) -> Decimal:
        return -Decimal(str(item.get(name, "0")))

    return (
        neg("corrected_lower_bound_ratio"), neg("return_without_best_episode_ratio"),
        neg("expected_shortfall_10_ratio"), Decimal(str(item.get("maximum_drawdown_ratio", "0"))),
        neg("median_daily_return_ratio"), str(item.get("candidate_id")),
    )


def _audit_mapping(
    report: Mapping[str, object], mapping_file: Mapping[str, object],
    manifest: Mapping[str, object], model: Mapping[str, object], failures: list[str],
) -> object | None:
    mapping = report.get("strict_mapping", {})
    report_mapping = dict(mapping) if isinstance(mapping, Mapping) else {}
    companion_without_hash = {
        key: value for key, value in mapping_file.items() if key != "artifact_hash"
    }
    if "artifact_hash" in report_mapping:
        _same(mapping_file, report_mapping, failures, "report/mapping artifact binding")
    else:
        _same(companion_without_hash, report_mapping, failures, "report/mapping artifact binding")
    supplied = mapping_file.get("artifact_hash")
    unhashed = {key: value for key, value in mapping_file.items() if key != "artifact_hash"}
    if supplied != _hash(unhashed):
        # Production mapping hash is computed by its typed domain artifact and
        # is also independently checked below when reconstruction is possible.
        if mapping_file.get("artifact_version") != "daily-strategy-mapping-v1":
            failures.append("mapping artifact hash mismatch")
    if report.get("strict_mapping_artifact_hash") != supplied:
        failures.append("strict mapping report hash mismatch")
    if mapping_file.get("model_artifact_hash") != model.get("artifact_hash"):
        failures.append("mapping/model identity mismatch")
    if mapping_file.get("candidate_universe_hash") != manifest.get("candidate_universe_hash"):
        failures.append("mapping/candidate universe mismatch")
    candidate_hashes = mapping_file.get("candidate_hashes", {})
    assessments = mapping_file.get("candidate_assessments", [])
    entries = mapping_file.get("entries", [])
    if not isinstance(assessments, list) or not isinstance(entries, list):
        failures.append("mapping assessments/entries are invalid")
        return None
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for item in assessments:
        if not isinstance(item, Mapping):
            failures.append("mapping assessment is invalid")
            continue
        candidate = item.get("candidate_id")
        if not isinstance(candidate_hashes, Mapping) or item.get("candidate_hash") != candidate_hashes.get(candidate):
            failures.append("mapping assessment candidate hash mismatch")
        grouped.setdefault(str(item.get("component_fingerprint")), []).append(item)
    for entry in entries:
        if not isinstance(entry, Mapping):
            failures.append("mapping entry is invalid")
            continue
        eligible = [item for item in grouped.get(str(entry.get("component_fingerprint")), []) if item.get("eligible") is True]
        expected = min(eligible, key=_winner_key).get("candidate_id") if eligible else None
        expected_decision = "strategy" if expected is not None else "cash"
        if entry.get("decision") != expected_decision or entry.get("strategy_candidate_id") != expected:
            failures.append("mapping cash/winner decision mismatch")
    if mapping_file.get("artifact_version") != "daily-strategy-mapping-v1":
        return None
    try:
        from src.application.services.daily_strategy_evidence import _evidence_from_payload
        from src.application.usecases.regime.build_daily_strategy_mapping_usecase import (
            BuildDailyStrategyMappingCommand,
            BuildDailyStrategyMappingUseCase,
        )
        from src.domain.regime.temporal import UtcInterval

        evidence_root = report.get("evidence", {})
        evidence_rows = tuple(
            _evidence_from_payload(row)
            for phase in sorted(evidence_root)
            for row in evidence_root[phase].get("daily_evidence_rows", [])
        )
        statistical = mapping_file.get("statistical_calendar", [])
        calendar = tuple(
            datetime.fromisoformat(str(item["day"]).replace("Z", "+00:00"))
            for item in statistical
        )
        evidence_intervals = tuple(
            (
                str(item["role"]),
                UtcInterval(
                    datetime.fromisoformat(str(item["start_at"]).replace("Z", "+00:00")),
                    datetime.fromisoformat(str(item["end_at"]).replace("Z", "+00:00")),
                ),
            )
            for item in mapping_file.get("evidence_intervals", [])
        )
        ledger_identities = tuple(
            (str(item["phase"]), str(item["ledger_hash"]), str(item["run_identity_hash"]))
            for item in mapping_file.get("evidence_ledger_identities", [])
        )
        ordered_manifest = tuple(
            (str(item[0]), str(item[1]))
            for item in manifest.get("ordered_definition_hashes", [])
        )
        command = BuildDailyStrategyMappingCommand(
            model_artifact_hash=str(model["artifact_hash"]),
            candidate_manifest=ordered_manifest,
            frozen_component_fingerprints=tuple(str(item) for item in model["component_fingerprints"]),
            calendar=calendar,
            component_assignments=tuple(item.get("component_fingerprint") for item in statistical),
            evidence_rows=evidence_rows,
            calendar_roles=tuple(str(item["role"]) for item in statistical),
            evidence_intervals=evidence_intervals,
            evidence_ledger_identities=ledger_identities,
        )
        rebuilt = BuildDailyStrategyMappingUseCase().execute(command).artifact
        _same(rebuilt.canonical_payload(), companion_without_hash, failures, "recomputed corrected-LCB mapping")
        from src.domain.regime import daily_mapping_artifact_hash

        if daily_mapping_artifact_hash(rebuilt) != supplied:
            failures.append("recomputed mapping artifact hash mismatch")
        return rebuilt
    except (KeyError, TypeError, ValueError) as error:
        failures.append(f"mapping statistics could not be independently reconstructed: {error}")
        return None


def _timestamp_strings(value: object, path: tuple[str, ...] = ()):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _timestamp_strings(item, (*path, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _timestamp_strings(item, (*path, str(index)))
    elif isinstance(value, str) and ("at" in path[-1].lower() if path else False):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return
        if parsed.tzinfo is not None:
            yield path, parsed.astimezone(timezone.utc)


def _audit_freeze(report: Mapping[str, object], failures: list[str]) -> None:
    payload = report.get("pre_test_freeze_payload")
    if not isinstance(payload, Mapping):
        # Published production reports expose every constituent. Reconstruct
        # the exact typed freeze envelope independently.
        profile = report.get("profile", {})
        pretest_profile = dict(profile) if isinstance(profile, Mapping) else {}
        if isinstance(pretest_profile.get("fold"), Mapping):
            pretest_profile["fold"] = {
                key: value for key, value in pretest_profile["fold"].items() if key != "test"
            }
        freeze_mapping = dict(report.get("strict_mapping", {})) if isinstance(report.get("strict_mapping"), Mapping) else {}
        freeze_mapping["artifact_hash"] = report.get("strict_mapping_artifact_hash")
        payload = {
            "freeze_schema_version": "three-day-pre-test-freeze-v1",
            "report_schema_version": "three-day-daily-k4-report-v1",
            "model": report.get("model_artifact"),
            "candidate_manifest": report.get("candidate_manifest"),
            "evidence": {
                "mapping": report.get("evidence", {}).get("mapping_fit") if isinstance(report.get("evidence"), Mapping) else None,
                "validation": report.get("evidence", {}).get("validation") if isinstance(report.get("evidence"), Mapping) else None,
            },
            "mapping": freeze_mapping,
            "global_fixed_baseline": report.get("global_fixed_baseline"),
            "profile": pretest_profile,
            "chronology": pretest_profile.get("fold"),
        }
    if report.get("pre_test_freeze_hash") != _hash(payload):
        failures.append("pre-Test freeze hash/identity mismatch")
    boundary = datetime(2026, 4, 4, tzinfo=timezone.utc)
    for path, timestamp in _timestamp_strings(payload):
        canonical_interval_metadata = (
            path[:4] == ("model", "profile", "fold", "test")
            or path[:4] == ("mapping", "research_profile", "fold", "test")
        )
        if canonical_interval_metadata:
            continue
        if timestamp >= boundary:
            failures.append("Test timestamp appears in pre-Test lineage at " + ".".join(path))
            break
    provenance = report.get("test_provenance", {})
    if isinstance(provenance, Mapping) and provenance.get("pre_test_freeze_hash") != report.get("pre_test_freeze_hash"):
        failures.append("Test provenance does not bind the pre-Test freeze")


def _drawdown(equities: Sequence[Decimal]) -> Decimal:
    if not equities:
        return Decimal(0)
    peak = equities[0]
    result = Decimal(0)
    for value in equities:
        peak = max(peak, value)
        if peak > 0:
            result = max(result, (peak - value) / peak)
    return result


def _audit_comparison(label: str, row: Mapping[str, object], failures: list[str]) -> tuple[int, int]:
    trades = row.get("trades", [])
    transition_count = 0
    if isinstance(row.get("transitions"), list):
        transitions = row["transitions"]
        transition_count = len(transitions)
        if row.get("transition_hash") != _hash(transitions):
            failures.append(f"{label} Test transition hash mismatch")
    elif isinstance(row.get("selection_events"), list):
        events = row["selection_events"]
        transition_types = {
            "cluster_transition": "component_transition_count",
            "strategy_transition": "strategy_transition_count",
            "cash_transition": "cash_transition_count",
        }
        previous = None
        for event in events:
            if not isinstance(event, Mapping):
                failures.append(f"{label} Test selection event is invalid")
                continue
            timestamp = event.get("boundary_at")
            if previous is not None and str(timestamp) < str(previous):
                failures.append(f"{label} Test selection events are not chronological")
            previous = timestamp
        for event_type, count_field in transition_types.items():
            reconstructed = sum(
                isinstance(event, Mapping) and event.get("type") == event_type
                for event in events
            )
            if row.get(count_field) != reconstructed:
                failures.append(f"{label} Test {count_field} mismatch")
            transition_count += reconstructed
    trade_count = len(trades) if isinstance(trades, list) else 0
    if isinstance(trades, list):
        if "trade_hash" in row and row.get("trade_hash") != _hash(trades):
            failures.append(f"{label} Test trade hash mismatch")
        if row.get("trade_count") != trade_count:
            failures.append(f"{label} Test trade count mismatch")
        for index, trade in enumerate(trades):
            if isinstance(trade, Mapping):
                _audit_trade(trade, failures, f"{label} Test trade {index}")
            else:
                failures.append(f"{label} Test trade {index} is invalid")
        opposite = sum(
            isinstance(trade, Mapping) and trade.get("exit_reason") == "active_strategy_opposite_signal"
            for trade in trades
        )
        if "active_strategy_opposite_exit_count" in row and row.get("active_strategy_opposite_exit_count") != opposite:
            failures.append(f"{label} active-strategy opposite-exit mismatch")
    curve = row.get("equity_curve", [])
    if isinstance(curve, list):
        if "equity_curve_hash" in row and row.get("equity_curve_hash") != _hash(curve):
            failures.append(f"{label} Test equity-curve hash mismatch")
        equities = []
        for point in curve:
            value = point.get("equity") if isinstance(point, Mapping) else point
            parsed = _decimal(value, f"{label} Test equity", failures)
            if parsed is not None:
                equities.append(parsed)
        initial = _decimal(row.get("initial_equity"), f"{label} initial equity", failures)
        final = _decimal(row.get("final_equity"), f"{label} final equity", failures)
        returned = _decimal(row.get("return_ratio"), f"{label} return", failures)
        reported_drawdown = _decimal(
            row.get("portfolio_max_drawdown_ratio", row.get("max_drawdown_ratio")),
            f"{label} drawdown", failures,
        )
        if initial is not None and final is not None and returned is not None and initial != 0:
            if (final - initial) / initial != returned:
                failures.append(f"{label} Test return/equity mismatch")
        if initial is not None and (not equities or equities[0] != initial):
            equities.insert(0, initial)
        if reported_drawdown is not None and equities and _drawdown(equities) != reported_drawdown:
            failures.append(f"{label} Test equity/MDD mismatch")
    return trade_count, transition_count


def _audit_test_and_baselines(
    report: Mapping[str, object], failures: list[str],
    *, manifest: Mapping[str, object], evidence_rows: Sequence[Mapping[str, object]],
) -> tuple[int, int]:
    comparisons = report.get("test_comparisons", {})
    if not isinstance(comparisons, Mapping):
        failures.append("Test comparisons are invalid")
        return 0, 0
    trades = transitions = 0
    for label, row in sorted(comparisons.items()):
        if not isinstance(row, Mapping):
            failures.append(f"{label} comparison is invalid")
            continue
        count, transition_count = _audit_comparison(str(label), row, failures)
        trades += count
        transitions += transition_count
    baseline = report.get("global_fixed_baseline", {})
    manifest = report.get("candidate_manifest", {})
    ids = manifest.get("candidate_ids", []) if isinstance(manifest, Mapping) else []
    if isinstance(baseline, Mapping):
        decision, candidate = baseline.get("decision"), baseline.get("candidate_id")
        if decision == "strategy" and candidate not in ids:
            failures.append("global fixed baseline candidate is outside frozen manifest")
        if decision == "cash" and candidate is not None:
            failures.append("global fixed cash baseline contains a candidate")
        assessments = baseline.get("assessments")
        if isinstance(assessments, list):
            eligible = [item for item in assessments if isinstance(item, Mapping) and item.get("eligible") is True]
            expected = min(eligible, key=_winner_key).get("candidate_id") if eligible else None
            if candidate != expected:
                failures.append("global fixed baseline winner mismatch")
        if assessments is not None:
            try:
                from src.application.services.daily_strategy_evidence import _evidence_from_payload
                from src.application.usecases.regime.build_daily_strategy_mapping_usecase import (
                    select_global_fixed_daily_candidate,
                )

                rebuilt = select_global_fixed_daily_candidate(
                    candidate_manifest=tuple(
                        (str(item[0]), str(item[1]))
                        for item in manifest.get("ordered_definition_hashes", [])
                    ),
                    evidence_rows=tuple(_evidence_from_payload(item) for item in evidence_rows),
                )
                _same(rebuilt.canonical_payload(), baseline, failures, "recomputed global fixed baseline")
            except (KeyError, TypeError, ValueError) as error:
                failures.append(f"global fixed baseline could not be reconstructed: {error}")
    else:
        failures.append("global fixed baseline is invalid")
    return trades, transitions


def _replay_untouched_test(
    report: Mapping[str, object], parsed_model: object, rebuilt_mapping: object,
    failures: list[str],
) -> None:
    """Re-run all six Test comparisons through engines, not report helpers."""
    sources = report.get("source_verification", {})
    if not isinstance(sources, Mapping) or not sources.get("raw_kline_root"):
        failures.append("untouched Test replay requires verified raw_kline_root")
        return
    provider = None
    try:
        from datetime import timedelta
        from scripts.chart_regime_strategy_mapping import (
            _load_exact_minute_market,
            _manual_router_candidate,
            _select_feature_cache,
            build_three_day_daily_candidate_manifest,
            default_candidate,
        )
        from scripts.scheduler_driven_scalping_backtest import (
            PositionExitPolicy,
            run_scheduler_driven_backtest,
            run_scheduler_driven_daily_regime_backtest,
        )
        from src.domain.regime import ThreeDayDailyResearchProfile

        profile = ThreeDayDailyResearchProfile()
        interval = profile.fold.test
        context_start = interval.start_at - timedelta(days=3)
        market, _ = _load_exact_minute_market(
            symbol="BTCUSDT", raw_kline_root=Path(str(sources["raw_kline_root"])),
            start_at=context_start, end_at=interval.end_at,
        )
        provider, _ = _select_feature_cache(
            sources.get("feature_cache_root"), required_start=context_start,
            required_end=interval.end_at, verify_full_file=True,
        )
        manifest = build_three_day_daily_candidate_manifest(expected_count=459)
        candidates = tuple(entry.candidate for entry in manifest.entries)
        by_id = {item.candidate_id: item for item in candidates}
        initial = Decimal("10000")

        def static(candidate):
            return run_scheduler_driven_backtest(
                market, context_start_at=context_start, start_at=interval.start_at,
                end_at=interval.end_at, candidate=candidate,
                market_feature_provider=provider, initial_equity=initial,
                include_trade_details=True, force_close_at_end=True,
                include_deferred=True,
            )

        def dynamic(policy):
            return run_scheduler_driven_daily_regime_backtest(
                market, start_at=interval.start_at, end_at=interval.end_at,
                candidates=candidates, model_artifact=parsed_model,
                mapping_artifact=rebuilt_mapping, position_exit_policy=policy,
                candidate_manifest=manifest, market_feature_provider=provider,
                initial_equity=initial, include_deferred=True, force_close_at_end=True,
            )

        baseline = report.get("global_fixed_baseline", {})
        global_id = baseline.get("candidate_id") if isinstance(baseline, Mapping) else None
        cash = {
            "status": "completed", "candidate_id": "cash",
            "initial_equity": str(initial), "final_equity": str(initial),
            "return_ratio": "0", "max_drawdown_ratio": "0", "trade_count": 0,
            "trades": [], "equity_curve": [],
        }
        rebuilt = {
            "cash": cash,
            "current_adopted_fixed": static(default_candidate()),
            "pre_test_global_best_fixed": cash if global_id is None else static(by_id[str(global_id)]),
            "k4_dynamic_entry_owner_exit": dynamic(PositionExitPolicy.ENTRY_OWNER_ONLY),
            "k4_dynamic_active_strategy_opposite_exit": dynamic(PositionExitPolicy.ACTIVE_STRATEGY_OPPOSITE),
            "existing_manual_regime_router": static(_manual_router_candidate()),
        }
        _same(rebuilt, report.get("test_comparisons"), failures, "scheduler-replayed Test comparisons")
    except (KeyError, LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        failures.append(f"untouched Test scheduler replay failed: {error}")
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def audit_three_day_k4_daily_mapping(
    inputs: AuditInputs,
    *,
    candidate_manifest_factory: Callable[[], Mapping[str, object]] = _default_manifest,
) -> dict[str, object]:
    failures: list[str] = []
    report = _read_canonical_json(inputs.report, failures, "report")
    model = _read_canonical_json(inputs.model, failures, "model")
    mapping = _read_canonical_json(inputs.mapping, failures, "mapping")
    if not inputs.markdown.is_file():
        failures.append("markdown output is missing")

    parsed_model = _audit_model(
        report.get("model_artifact", {}) if isinstance(report.get("model_artifact"), Mapping) else {},
        model, failures,
    )
    raw_count = _audit_raw_inputs(model, report, failures)
    manifest = _audit_manifest(report, candidate_manifest_factory, failures)
    evidence_count, evidence_rows = _audit_evidence(report, model, parsed_model, failures)
    rebuilt_mapping = _audit_mapping(report, mapping, manifest, model, failures)
    _audit_freeze(report, failures)
    test_trade_count, transition_count = _audit_test_and_baselines(
        report, failures, manifest=manifest, evidence_rows=evidence_rows
    )
    if parsed_model is not None and rebuilt_mapping is not None:
        _replay_untouched_test(report, parsed_model, rebuilt_mapping, failures)

    output_hashes = report.get("output_hashes")
    publication = report.get("publication")
    if output_hashes is None and isinstance(publication, Mapping):
        payload = {key: value for key, value in report.items() if key != "publication"}
        if publication.get("report_payload_hash") != _hash(payload):
            failures.append("report publication payload hash mismatch")
        output_hashes = {
            "model": publication.get("model_byte_hash"),
            "mapping": publication.get("mapping_byte_hash"),
            "markdown": publication.get("markdown_byte_hash"),
        }
    actual_files = {
        "model": inputs.model, "mapping": inputs.mapping, "markdown": inputs.markdown,
    }
    if isinstance(output_hashes, Mapping):
        for label, path in actual_files.items():
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                failures.append(f"{label} output could not be read: {error}")
                continue
            if output_hashes.get(label) != actual:
                failures.append(f"{label} report output hash mismatch")
    elif output_hashes is not None:
        failures.append("report output hashes are invalid")

    hashes = {
        "report_file_hash": hashlib.sha256(inputs.report.read_bytes()).hexdigest() if inputs.report.is_file() else None,
        "model_file_hash": hashlib.sha256(inputs.model.read_bytes()).hexdigest() if inputs.model.is_file() else None,
        "mapping_file_hash": hashlib.sha256(inputs.mapping.read_bytes()).hexdigest() if inputs.mapping.is_file() else None,
        "markdown_file_hash": hashlib.sha256(inputs.markdown.read_bytes()).hexdigest() if inputs.markdown.is_file() else None,
        "pre_test_freeze_hash": report.get("pre_test_freeze_hash"),
        "model_artifact_hash": model.get("artifact_hash"),
        "mapping_artifact_hash": mapping.get("artifact_hash"),
    }
    return {
        "schema_version": "three-day-k4-daily-independent-audit-v1",
        "passed": not failures,
        "checked_counts": {
            "raw_inputs": raw_count,
            "candidates": int(manifest.get("candidate_count", 0)) if isinstance(manifest, Mapping) else 0,
            "evidence_rows": evidence_count,
            "test_transitions": transition_count,
            "test_trades": test_trade_count,
        },
        "hashes": hashes,
        "failures": failures,
    }


def _default_paths(report: Path) -> AuditInputs:
    stem = report.with_suffix("")
    return AuditInputs(
        report=report, markdown=stem.with_suffix(".md"),
        model=stem.with_name(stem.name + "-model").with_suffix(".json"),
        mapping=stem.with_name(stem.name + "-mapping").with_suffix(".json"),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--mapping", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    defaults = _default_paths(args.report)
    inputs = AuditInputs(
        report=args.report,
        markdown=args.markdown or defaults.markdown,
        model=args.model or defaults.model,
        mapping=args.mapping or defaults.mapping,
    )
    result = audit_three_day_k4_daily_mapping(inputs)
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
