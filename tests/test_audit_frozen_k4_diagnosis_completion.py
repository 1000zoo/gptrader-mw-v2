from __future__ import annotations

import importlib.util
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
from datetime import datetime, timedelta, timezone
from types import MappingProxyType, SimpleNamespace

import pytest

from src.application.services.frozen_k4_diagnosis_completion import (
    FixedSampleReceipt,
    OffsetOODRow,
)
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_frozen_k4_diagnosis_completion.py"


def _load():
    spec = importlib.util.spec_from_file_location("completion_auditor", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auditor_is_importable_and_independent() -> None:
    module = _load()
    assert callable(module.audit_frozen_k4_diagnosis_completion)
    source = SCRIPT.read_text(encoding="utf-8")
    assert "src.application.services.frozen_k4_diagnosis_completion" not in source
    assert "scripts.complete_frozen_three_day_k4_diagnosis" not in source


def test_empirical_centroid_vector_reconciles_production_rounding_order() -> None:
    auditor = _load()
    producer = -0.5340541477761451
    independently_recomputed = -0.5340541477761452

    auditor._compare_objects(
        [{"empirical_centroid": [producer, 0.25]}],
        [{"empirical_centroid": [independently_recomputed, 0.25]}],
        "empirical centroids",
    )


def test_empirical_centroid_vector_rejects_material_numeric_mutation() -> None:
    auditor = _load()

    with pytest.raises(auditor.AuditError, match="does not numerically reconcile"):
        auditor._compare_objects(
            [{"empirical_centroid": [-0.5340541477761451, 0.25]}],
            [{"empirical_centroid": [-0.5340541477761451, 0.250001]}],
            "empirical centroids",
        )


def test_empirical_centroid_csv_cell_rejects_material_numeric_mutation() -> None:
    auditor = _load()

    with pytest.raises(auditor.AuditError, match="does not numerically reconcile"):
        auditor._compare_centroid_csv_cell(
            "-0.53405414777614513;0.25000099999999997",
            [-0.5340541477761452, 0.25],
            "empirical centroid CSV",
        )


@pytest.mark.parametrize(
    ("cell", "expected", "message"),
    [
        ("0.25000000000000000", [0.25], "not canonical"),
        ("0.25;", [0.25], "vector shape"),
        ("nan", [0.25], "not finite"),
        ("", [0.25], "vector shape"),
    ],
)
def test_empirical_centroid_csv_cell_rejects_noncanonical_or_invalid_tokens(
    cell: str, expected: list[float], message: str,
) -> None:
    auditor = _load()

    with pytest.raises(auditor.AuditError, match=message):
        auditor._compare_centroid_csv_cell(cell, expected, "empirical centroid CSV")


def test_empirical_centroid_csv_cell_preserves_null_contract() -> None:
    auditor = _load()

    auditor._compare_centroid_csv_cell("", None, "empirical centroid CSV")
    with pytest.raises(auditor.AuditError, match="exactly reconcile"):
        auditor._compare_centroid_csv_cell("0", None, "empirical centroid CSV")


def test_canonical_json_rejects_nonfinite_and_noncanonical(tmp_path: Path) -> None:
    module = _load()
    path = tmp_path / "bad.json"
    path.write_bytes(b'{"value":NaN}')
    with pytest.raises(module.AuditError, match="JSON"):
        module._load_canonical_json(path)
    path.write_bytes(b'{ "value": 1 }')
    with pytest.raises(module.AuditError, match="canonical"):
        module._load_canonical_json(path)


@pytest.mark.parametrize("value", ["../x", "x/y", "x\\y", "", "."])
def test_artifact_names_are_canonical_basenames(value: str) -> None:
    module = _load()
    with pytest.raises(module.AuditError, match="basename"):
        module._canonical_basename(value)


def test_float_receipt_is_binary64_hex() -> None:
    module = _load()
    assert module._float_bits(2.3526219570607076) == "4002d22b75eb6b05"
    assert module._float_bits(0.04631322364411944) == "3fa7b65de9d8ffd8"


def test_conclusion_classification() -> None:
    module = _load()
    assert module._classification(3, 3) == "universal"
    assert module._classification(1, 3) == "mixed"
    assert module._classification(0, 3) == "subset-only"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _document(value: object) -> bytes:
    return _canonical(value) + b"\n"


def test_parent_manifest_verifies_every_artifact_byte(tmp_path: Path) -> None:
    module = _load()
    run_id = "a" * 64
    run = tmp_path / run_id
    run.mkdir()
    artifact = b"immutable\n"
    (run / "evidence.txt").write_bytes(artifact)
    manifest = {
        "run_id": run_id,
        "input_identity_sha256": "b" * 64,
        "file_sha256": {"evidence.txt": hashlib.sha256(artifact).hexdigest()},
        "status": "reproduced",
        "diagnostic_only": True,
        "primary_replacement_allowed": False,
    }
    (run / "manifest.json").write_bytes(_document(manifest))
    files = module._directory(run)
    assert module._read_manifest(run, files, child=False)["run_id"] == run_id
    (run / "evidence.txt").write_bytes(artifact + b"x")
    with pytest.raises(module.AuditError, match="hash mismatch.*evidence.txt"):
        module._read_manifest(run, module._directory(run), child=False)


def test_diagonal_assignment_and_transform_are_independently_recomputed() -> None:
    module = _load()
    primary = SimpleNamespace(
        feature_names=("x", "y"), lower_bounds=(0.0, 0.0),
        upper_bounds=(10.0, 10.0), medians=(1.0, 2.0), scales=(2.0, 4.0),
        means=((0.0, 0.0), (2.0, 2.0)),
        covariances=((1.0, 1.0), (1.0, 1.0)), weights=(0.5, 0.5),
    )
    vector = SimpleNamespace(values={"x": 99.0, "y": -5.0})
    transformed = module._transform(primary, (vector,))
    assert transformed == [[4.5, -0.5]]
    assert module._primary_assignment(primary, [0.1, 0.2]) == 0
    assert module._primary_assignment(primary, [2.1, 2.2]) == 1


def test_primary_assignment_uses_stored_covariance_without_a_floor() -> None:
    module = _load()
    primary = SimpleNamespace(
        means=((0.0,), (0.1,)), covariances=((1e-8,), (1.0,)),
        weights=(0.5, 0.5),
    )
    assert module._primary_assignment(primary, [0.002]) == 1


def test_parent_half_graph_binds_indices_and_fingerprints() -> None:
    module = _load()
    primary = SimpleNamespace(fingerprints=("a" * 24, "b" * 24, "c" * 24, "d" * 24))
    parent = {
        "half_replays": [
            {
                "receipt": {"half_label": label, "anchor_count": count},
                "matched_pairs": [
                    {
                        "half_label": label, "half_component_index": index,
                        "half_component_fingerprint": format(8 + half_number * 4 + index, "x") * 24,
                        "primary_component_index": index,
                        "primary_component_fingerprint": primary.fingerprints[index],
                    }
                    for index in range(4)
                ],
            }
            for half_number, (label, count) in enumerate((("A", 820), ("B", 821)))
        ]
    }
    graph = module._parent_half_graph(parent, primary)
    assert graph[("A", 0)][0] == 0
    bad = json.loads(json.dumps(parent))
    bad["half_replays"][0]["matched_pairs"][0]["primary_component_fingerprint"] = "f" * 24
    with pytest.raises(module.AuditError, match="parent matched-pair"):
        module._parent_half_graph(bad, primary)


def test_replay_receipts_reject_one_bit_mutation() -> None:
    module = _load()
    temporal = 2.3526219570607076
    ood = 0.04631322364411944
    bits = {
        "maximum_distance_exceedance_rate": [module._float_bits(ood), module._float_bits(ood)],
        "maximum_matched_centroid_distance": [module._float_bits(temporal), module._float_bits(temporal)],
    }
    parent = {
        "status": {
            "status": "reproduced", "ood_exceedance_numerator": 76,
            "ood_denominator": 1641,
            "temporal_half_refit_stability_reproduction": {
                "expected_value": temporal, "reproduced_value": temporal},
            "primary_model_ood_reproduction": {
                "expected_value": ood, "reproduced_value": ood},
        },
        "metric_ieee_float_bits": bits,
    }
    receipt = {
        "status": "reproduced", "temporal_expected_value": temporal,
        "temporal_reproduced_value": temporal, "ood_expected_value": ood,
        "ood_reproduced_value": ood, "ood_numerator": 76,
        "ood_denominator": 1641, "metric_ieee_float_bits": bits,
    }
    child = {
        "replay_parent_match_verified": True,
        "replay_parent_validation": {
            "match_verified": True, "parent_receipt": receipt,
            "new_replay_receipt": dict(receipt)},
    }
    module._verify_replay(parent, child)
    child["replay_parent_validation"]["new_replay_receipt"] = {
        **receipt, "ood_numerator": 75}
    with pytest.raises(module.AuditError, match="new_replay_receipt"):
        module._verify_replay(parent, child)


def _real_fixture_paths() -> tuple[Path, Path, Path, Path] | None:
    root = Path(__file__).parents[1]
    parent = root / "docs/backtests/frozen_k4_failure_diagnosis/d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af"
    completion_root = root / "docs/backtests/frozen_k4_diagnosis_completion"
    model = root / "docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json"
    raw = root / ".research-data/binance-usdm/raw/klines"
    runs = sorted(path for path in completion_root.iterdir() if path.is_dir()) if completion_root.is_dir() else []
    if len(runs) != 1 or not parent.is_dir() or not model.is_file() or not raw.is_dir():
        return None
    return parent, runs[0], model, raw


class _ForbiddenModule:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"independent auditor accessed forbidden helper: {name}")


def _csv_bytes(headers: tuple[str, ...], rows: list[dict[str, object]]) -> bytes:
    from io import StringIO
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        rendered = {}
        for name in headers:
            value = row.get(name)
            if value is None:
                rendered[name] = ""
            elif isinstance(value, bool):
                rendered[name] = "true" if value else "false"
            elif isinstance(value, float):
                rendered[name] = format(value, ".17g")
            else:
                rendered[name] = value
        writer.writerow(rendered)
    return buffer.getvalue().encode()


def _independent_artifacts(
    completion: dict[str, object], *, parent_id: str, parent_manifest_hash: str,
    input_hash: str, implementation_files: dict[str, str], implementation_hash: str,
    replay_receipt: dict[str, object], fitted: dict[str, object], registry_hash: str,
) -> dict[str, bytes]:
    component = completion["component_zero_ood"]
    payload = {
        "diagnostic_schema_version": "frozen-k4-diagnosis-completion-v1",
        "completion_scope": "frozen-k4-diagnosis-completion",
        "implementation_file_sha256": implementation_files,
        "implementation_sha256": implementation_hash,
        "replay_parent_match_verified": True,
        "replay_parent_validation": {"parent_receipt": replay_receipt,
                                     "new_replay_receipt": replay_receipt,
                                     "match_verified": True},
        "parent_provenance": {"parent_run_id": parent_id,
                              "parent_manifest_sha256": parent_manifest_hash,
                              "input_identity_sha256": input_hash},
        "registry_provenance": {"registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
                                "registry_sha256": registry_hash},
        "fixed_thresholds": {"single_feature_contribution_ratio": 0.5,
                             "volatility_family_contribution_ratio": 0.7,
                             "recurrent_feature_top1_ratio": 0.5},
        "component_zero_ood": component,
        "fitted_parameter_reference": fitted,
        "full_sample_empirical": completion["full_sample_empirical"],
        "full_sample_ood": completion["full_sample_ood"],
        "offset_empirical": completion["offset_empirical"],
        "offset_ood": completion["offset_ood"],
        "offset_consistency": completion["offset_conclusions"],
        "fixed_sample_receipts": completion["sample_receipts"],
        "diagnostic_only": True, "primary_replacement_allowed": False,
    }
    feature_headers = ("analysis_scope", "primary_component_index", "primary_component_fingerprint",
        "feature_name", "registry_family", "registry_schema_version", "registry_sha256",
        "contribution_sum", "contribution_ratio", "contribution_mean", "contribution_median",
        "top1_count", "top1_ratio", "top5_count", "top5_ratio", "rank")
    family_headers = ("analysis_scope", "primary_component_index", "primary_component_fingerprint",
        "family_name", "family_feature_names", "registry_schema_version", "registry_sha256",
        "contribution_sum", "contribution_ratio", "concentration_threshold",
        "concentration_rule_applies", "concentration_result")
    family_rows = [{**row, "family_feature_names": ";".join(row["family_feature_names"])}
                   for row in component["family_rows"]]
    empirical_feature_headers = ("sample_scope", "spacing_days", "offset", "half_label",
        "primary_component_index", "primary_component_fingerprint", "half_component_index",
        "half_component_fingerprint", "feature_name", "registry_family", "rank",
        "squared_distance", "contribution_ratio", "is_top_five")
    scopes = [completion["full_sample_empirical"], *completion["offset_empirical"]]
    empirical_feature_rows = []
    for scope in scopes:
        empirical_feature_rows.extend({**row, "is_top_five": row["rank"] <= 5}
                                      for row in scope["feature_rows"])
    diagnostic_headers = ("record_type", "sample_scope", "spacing_days", "offset",
        "offset_origin_anchor", "half_label", "primary_component_index",
        "primary_component_fingerprint", "half_component_index", "half_component_fingerprint",
        "sample_count", "sample_share", "centroid_status", "metric_name",
        "empirical_centroid", "distance", "ood_numerator", "ood_denominator", "ood_rate",
        "distance_source", "threshold_source", "maximum_drift_half_label",
        "maximum_drift_primary_component_index", "maximum_drift_primary_component_fingerprint",
        "maximum_drift_half_component_index", "maximum_drift_half_component_fingerprint",
        "maximum_ood_primary_component_index", "maximum_ood_primary_component_fingerprint",
        "top_five_drift_features", "drift_component_matches_full_sample",
        "ood_component_matches_full_sample", "ordered_top5_matches_full_sample",
        "top5_set_matches_full_sample")
    all_ood = [*completion["full_sample_ood"], *completion["offset_ood"]]
    ood_by_scope = {}
    for row in all_ood:
        ood_by_scope.setdefault((row["sample_scope"], row["spacing_days"], row["offset"]), []).append(row)
    scope_by_key = {(row["sample_scope"], row["spacing_days"], row["offset"]): row for row in scopes}

    def decorate(row: dict[str, object], key: tuple[object, object, object]) -> dict[str, object]:
        scope = scope_by_key[key]
        maximum_ood = min(ood_by_scope[key], key=lambda item: (-item["rate"], -item["numerator"],
                                                                -item["denominator"], item["primary_component_index"]))
        return {**row, "offset_origin_anchor": scope["centroid_rows"][0]["offset_origin_anchor"],
            "maximum_drift_half_label": scope["maximum_drift_half_label"],
            "maximum_drift_primary_component_index": scope["maximum_drift_primary_component_index"],
            "maximum_drift_primary_component_fingerprint": scope["maximum_drift_primary_component_fingerprint"],
            "maximum_drift_half_component_index": scope["maximum_drift_half_component_index"],
            "maximum_drift_half_component_fingerprint": scope["maximum_drift_half_component_fingerprint"],
            "maximum_ood_primary_component_index": maximum_ood["primary_component_index"],
            "maximum_ood_primary_component_fingerprint": maximum_ood["primary_component_fingerprint"]}

    diagnostics = []
    for scope in scopes:
        key = (scope["sample_scope"], scope["spacing_days"], scope["offset"])
        for row in scope["centroid_rows"]:
            diagnostics.append(decorate({**row, "record_type": "centroid",
                "empirical_centroid": None if row["empirical_centroid"] is None else ";".join(format(value, ".17g") for value in row["empirical_centroid"])}, key))
    for row in all_ood:
        key = (row["sample_scope"], row["spacing_days"], row["offset"])
        diagnostics.append(decorate({**row, "record_type": "ood", "ood_numerator": row["numerator"],
                                     "ood_denominator": row["denominator"], "ood_rate": row["rate"]}, key))
    for row in completion["offset_conclusions"]:
        key = ("offset_subsample", row["spacing_days"], row["offset"])
        diagnostics.append(decorate({**row, "record_type": "conclusion", "sample_scope": "offset_subsample",
                                     "top_five_drift_features": ";".join(row["top_five_drift_features"])}, key))
    record_order = {"centroid": 0, "ood": 1, "conclusion": 2}
    diagnostics.sort(key=lambda row: (0 if row["sample_scope"] == "full_sample" else 1,
        -1 if row.get("spacing_days") is None else row["spacing_days"],
        -1 if row.get("offset") is None else row["offset"], record_order[row["record_type"]],
        str(row.get("half_label") or ""), -1 if row.get("primary_component_index") is None else row["primary_component_index"],
        -1 if row.get("half_component_index") is None else row["half_component_index"]))
    lines = ["# Frozen K4 Diagnosis Completion", "",
        "This diagnostic-only report completes the frozen K4 cause diagnosis.", "",
        "## Component 0 OOD (24/409)", "",
        f"- Top five features: {', '.join(component['top_five_features'])}"]
    for row in component["family_rows"]:
        lines.append(f"- family {row['family_name']}: contribution_ratio={format(row['contribution_ratio'], '.17g')}")
    for key in ("single_feature_concentration", "volatility_family_concentration", "recurrent_feature_dominance"):
        lines.append(f"- {key}={'true' if component[key] else 'false'}")
    lines.extend(["", "## Distinct distance metrics", "",
        f"- fitted_parameter_centroid_distance={format(fitted['distance'], '.17g')}",
        f"- full_sample_empirical_centroid_distance={format(completion['full_sample_empirical']['maximum_drift_distance'], '.17g')}",
        "- offset_empirical_centroid_distance is reported for every 3-day and 7-day offset.", "",
        "## Offset consistency", ""])
    for row in completion["offset_conclusions"]:
        scope = scope_by_key[("offset_subsample", row["spacing_days"], row["offset"])]
        lines.append(f"- {row['spacing_days']}-day offset={row['offset']} origin={scope['centroid_rows'][0]['offset_origin_anchor']} "
            f"offset_empirical_centroid_distance: max={format(scope['maximum_drift_distance'], '.17g')} "
            f"half={scope['maximum_drift_half_label']} primary_component={scope['maximum_drift_primary_component_index']} "
            f"primary_fingerprint={scope['maximum_drift_primary_component_fingerprint']} "
            f"half_component={scope['maximum_drift_half_component_index']} half_fingerprint={scope['maximum_drift_half_component_fingerprint']} "
            f"maximum_ood_primary_component={row['maximum_ood_primary_component_index']} "
            f"maximum_ood_fingerprint={row['maximum_ood_primary_component_fingerprint']} "
            f"top_five={','.join(row['top_five_drift_features'])}")
    flags = (("drift component", "drift_component_matches_full_sample"),
             ("OOD component", "ood_component_matches_full_sample"),
             ("ordered top five", "ordered_top5_matches_full_sample"),
             ("top-five set", "top5_set_matches_full_sample"))
    for spacing in (3, 7):
        rows = [row for row in completion["offset_conclusions"] if row["spacing_days"] == spacing]
        for label, field in flags:
            count = sum(row[field] for row in rows)
            classification = "universal" if count == len(rows) else ("subset-only" if count == 0 else "mixed")
            lines.append(f"- {spacing}-day {label}: {count}/{len(rows)} ({classification})")
    lines.extend(["", "No model gate was re-evaluated and no strategy mapping was performed."])
    return {
        "frozen_k4_component_0_ood_feature_summary.csv": _csv_bytes(feature_headers, component["feature_rows"]),
        "frozen_k4_component_0_ood_family_summary.csv": _csv_bytes(family_headers, family_rows),
        "frozen_k4_offset_empirical_diagnostics.csv": _csv_bytes(diagnostic_headers, diagnostics),
        "frozen_k4_offset_feature_contributions.csv": _csv_bytes(empirical_feature_headers, empirical_feature_rows),
        "frozen_k4_diagnosis_completion.json": _document(payload),
        "frozen_k4_diagnosis_completion.md": ("\n".join(lines) + "\n").encode(),
    }


def _synthetic_end_to_end_fixture(tmp_path: Path, auditor=None):
    auditor = auditor or _load()

    names = ("rv_4h", "rv_1d", "rv_3d", "rv_ratio_1d_3d", "range_ratio_3d")
    registry = {row.name: row for row in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
    primary_fps = tuple(str(index) * 24 for index in range(1, 5))
    half_fps = {
        (half, component): format(5 + half_number * 4 + component, "x") * 24
        for half_number, half in enumerate(("A", "B")) for component in range(4)
    }
    primary = SimpleNamespace(
        feature_names=names, lower_bounds=(-100.0,) * 5, upper_bounds=(100.0,) * 5,
        medians=(0.0,) * 5, scales=(1.0,) * 5, fingerprints=primary_fps,
        means=tuple((float(component * 10),) * 5 for component in range(4)),
        covariances=((1.0,) * 5,) * 4, weights=(0.25,) * 4,
        # Frozen GMM fits do not carry per-component thresholds.  The replay
        # contract pins one squared-Mahalanobis threshold in the attempt gate.
        distance_thresholds=(),
    )
    counts = (409, 410, 411, 411)
    ood_counts = (24, 17, 17, 18)
    assignments = [component for component, count in enumerate(counts) for _ in range(count)]
    seen = [0, 0, 0, 0]
    vectors = []
    receipts = []
    start = datetime(2021, 1, 1, tzinfo=timezone.utc)
    for index, component in enumerate(assignments):
        is_ood = seen[component] < ood_counts[component]
        seen[component] += 1
        delta = 0.5 if is_ood else 0.0
        values = {name: component * 10.0 + delta for name in names}
        anchor = start + timedelta(days=index)
        vectors.append(SimpleNamespace(values=values, anchor_at=anchor))
        half = "A" if index < 820 else "B"
        half_component = index % 4
        squared = 5 * delta * delta
        receipts.append({
            "global_index": index, "anchor_at": anchor.isoformat().replace("+00:00", "Z"),
            "half_label": half, "half_component_index": half_component,
            "half_component_fingerprint": half_fps[(half, half_component)],
            "matched_primary_component_index": half_component,
            "matched_primary_component_fingerprint": primary_fps[half_component],
            "primary_component_index": component,
            "primary_component_fingerprint": primary_fps[component],
            "squared_mahalanobis": squared, "ood_threshold": 1.0,
            "ood_exceeds": is_ood,
            "assignment_source": "existing_reproduced_assignments",
        })

    registry_payload = {
        "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        "retained_feature_names": list(names),
        "registry": [{
            "name": row.name, "family": row.family,
            "aggregation_minutes": row.aggregation_minutes,
            "lookback_minutes": row.lookback_minutes, "formula": row.formula,
        } for row in THREE_DAY_CHART_FEATURE_REGISTRY_V1],
    }
    registry_hash = hashlib.sha256(_canonical(registry_payload)).hexdigest()
    feature_rows = []
    for rank, name in enumerate(names, 1):
        feature_rows.append({
            "analysis_scope": auditor.COMPONENT_SCOPE, "primary_component_index": 0,
            "primary_component_fingerprint": primary_fps[0], "feature_name": name,
            "registry_family": registry[name].family,
            "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
            "registry_sha256": registry_hash, "contribution_sum": 6.0,
            "contribution_ratio": 0.2, "contribution_mean": 0.25,
            "contribution_median": 0.25, "top1_count": 24 if rank == 1 else 0,
            "top1_ratio": 1.0 if rank == 1 else 0.0, "top5_count": 24,
            "top5_ratio": 1.0, "rank": rank,
        })
    family_rows = [
        {"analysis_scope": auditor.COMPONENT_SCOPE, "primary_component_index": 0,
         "primary_component_fingerprint": primary_fps[0], "family_name": "volatility",
         "family_feature_names": list(names[:4]),
         "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
         "registry_sha256": registry_hash, "contribution_sum": 24.0,
         "contribution_ratio": 0.8, "concentration_threshold": 0.7,
         "concentration_rule_applies": True, "concentration_result": True},
        {"analysis_scope": auditor.COMPONENT_SCOPE, "primary_component_index": 0,
         "primary_component_fingerprint": primary_fps[0], "family_name": "range",
         "family_feature_names": [names[4]],
         "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
         "registry_sha256": registry_hash, "contribution_sum": 6.0,
         "contribution_ratio": 0.2, "concentration_threshold": 0.7,
         "concentration_rule_applies": False, "concentration_result": False},
    ]
    component = {
        "analysis_scope": auditor.COMPONENT_SCOPE, "primary_component_index": 0,
        "primary_component_fingerprint": primary_fps[0], "assigned_sample_count": 409,
        "ood_sample_count": 24, "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        "registry_sha256": registry_hash, "feature_rows": feature_rows,
        "family_rows": family_rows, "top_five_features": list(names),
        "single_feature_concentration": False, "volatility_family_concentration": True,
        "recurrent_feature_dominance": True, "diagnostic_only": True,
    }

    def empirical(spacing: int | None, offset: int | None):
        sample_scope = "full_sample" if spacing is None else "offset_subsample"
        selected = list(range(1641)) if spacing is None else [i for i in range(1641) if i % spacing == offset]
        centroid_rows = []
        empirical_features = []
        for half in ("A", "B"):
            half_count = sum(receipts[i]["half_label"] == half for i in selected)
            for component_index in range(4):
                members = [i for i in selected if receipts[i]["half_label"] == half
                           and receipts[i]["half_component_index"] == component_index]
                common = {
                    "sample_scope": sample_scope, "spacing_days": spacing, "offset": offset,
                    "offset_origin_anchor": receipts[0]["anchor_at"], "half_label": half,
                    "primary_component_index": component_index,
                    "half_component_index": component_index,
                    "primary_component_fingerprint": primary_fps[component_index],
                    "half_component_fingerprint": half_fps[(half, component_index)],
                    "sample_count": len(members), "sample_share": len(members) / half_count,
                    "metric_name": "full_sample_empirical_centroid_distance" if spacing is None else "offset_empirical_centroid_distance",
                    "assignment_source": "frozen_reproduced_half_assignment",
                    "refit_performed": False, "rematch_performed": False, "diagnostic_only": True,
                }
                if not members:
                    centroid_rows.append({**common, "centroid_status": "insufficient_sample",
                                          "empirical_centroid": None, "distance": None})
                    continue
                # Mirror the production empirical-mean order: dividing every
                # binary64 value before ``fsum`` can differ by one ULP from an
                # independent ``fsum(values) / count`` recomputation.
                centroid = [
                    math.fsum(vectors[i].values[name] / len(members) for i in members)
                    for name in names
                ]
                squares = [(value - component_index * 10.0) ** 2 for value in centroid]
                distance = math.sqrt(sum(squares))
                centroid_rows.append({**common, "centroid_status": "computed",
                                      "empirical_centroid": centroid, "distance": distance})
                for rank, feature_index in enumerate(range(5), 1):
                    empirical_features.append({
                        "sample_scope": sample_scope, "spacing_days": spacing, "offset": offset,
                        "half_label": half, "primary_component_index": component_index,
                        "half_component_index": component_index,
                        "primary_component_fingerprint": primary_fps[component_index],
                        "half_component_fingerprint": half_fps[(half, component_index)],
                        "feature_name": names[feature_index], "registry_family": registry[names[feature_index]].family,
                        "squared_distance": squares[feature_index],
                        "contribution_ratio": squares[feature_index] / sum(squares) if distance else 0.0,
                        "rank": rank,
                    })
        maximum = min((row for row in centroid_rows if row["distance"] is not None),
                      key=lambda row: (-row["distance"], row["half_label"],
                                       row["primary_component_index"], row["half_component_index"]))
        top = [row["feature_name"] for row in empirical_features
               if row["half_label"] == maximum["half_label"]
               and row["half_component_index"] == maximum["half_component_index"]][:5]
        return {
            "sample_scope": sample_scope, "spacing_days": spacing, "offset": offset,
            "selected_sample_count": len(selected), "centroid_rows": centroid_rows,
            "feature_rows": empirical_features,
            "maximum_drift_half_label": maximum["half_label"],
            "maximum_drift_primary_component_index": maximum["primary_component_index"],
            "maximum_drift_half_component_index": maximum["half_component_index"],
            "maximum_drift_primary_component_fingerprint": maximum["primary_component_fingerprint"],
            "maximum_drift_half_component_fingerprint": maximum["half_component_fingerprint"],
            "maximum_drift_distance": maximum["distance"], "top_five_drift_features": top,
        }

    full_empirical = empirical(None, None)
    offsets = [empirical(spacing, offset) for spacing in (3, 7) for offset in range(spacing)]

    def ood_rows(spacing: int | None, offset: int | None):
        scope = "full_sample" if spacing is None else "offset_subsample"
        selected = list(range(1641)) if spacing is None else [i for i in range(1641) if i % spacing == offset]
        production_provenance = OffsetOODRow(
            scope, spacing, offset, 0, primary_fps[0], 0, 0, None,
        )
        return [{
            "sample_scope": scope, "spacing_days": spacing, "offset": offset,
            "primary_component_index": component_index,
            "primary_component_fingerprint": primary_fps[component_index],
            "numerator": sum(receipts[i]["ood_exceeds"] for i in selected if assignments[i] == component_index),
            "denominator": sum(assignments[i] == component_index for i in selected),
            "rate": (sum(receipts[i]["ood_exceeds"] for i in selected if assignments[i] == component_index)
                     / sum(assignments[i] == component_index for i in selected)),
            "distance_source": production_provenance.distance_source,
            "threshold_source": production_provenance.threshold_source,
        } for component_index in range(4)]

    full_ood = ood_rows(None, None)
    offset_ood = [row for spacing in (3, 7) for offset in range(spacing) for row in ood_rows(spacing, offset)]
    full_max_ood = min(full_ood, key=lambda row: (-row["rate"], -row["numerator"], -row["denominator"], row["primary_component_index"]))
    conclusions = []
    for scope in offsets:
        rows = [row for row in offset_ood if row["spacing_days"] == scope["spacing_days"] and row["offset"] == scope["offset"]]
        maximum_ood = min(rows, key=lambda row: (-row["rate"], -row["numerator"], -row["denominator"], row["primary_component_index"]))
        top = scope["top_five_drift_features"]
        conclusions.append({
            "spacing_days": scope["spacing_days"], "offset": scope["offset"],
            "maximum_drift_half_label": scope["maximum_drift_half_label"],
            "maximum_drift_primary_component_index": scope["maximum_drift_primary_component_index"],
            "maximum_drift_primary_component_fingerprint": scope["maximum_drift_primary_component_fingerprint"],
            "maximum_drift_half_component_index": scope["maximum_drift_half_component_index"],
            "maximum_drift_half_component_fingerprint": scope["maximum_drift_half_component_fingerprint"],
            "maximum_ood_primary_component_index": maximum_ood["primary_component_index"],
            "maximum_ood_primary_component_fingerprint": maximum_ood["primary_component_fingerprint"],
            "top_five_drift_features": top,
            "drift_component_matches_full_sample": scope["maximum_drift_primary_component_index"] == full_empirical["maximum_drift_primary_component_index"],
            "ood_component_matches_full_sample": maximum_ood["primary_component_index"] == full_max_ood["primary_component_index"],
            "ordered_top5_matches_full_sample": top == full_empirical["top_five_drift_features"],
            "top5_set_matches_full_sample": set(top) == set(full_empirical["top_five_drift_features"]),
        })

    completion = {
        "completion_scope": auditor.SCOPE, "component_zero_ood": component,
        "full_sample_empirical": full_empirical, "full_sample_ood": full_ood,
        "offset_empirical": offsets, "offset_ood": offset_ood,
        "offset_conclusions": conclusions, "sample_receipts": receipts,
        "diagnostic_only": True,
    }
    temporal = 2.3526219570607076
    ood_rate = 0.04631322364411944
    bits = {
        "maximum_distance_exceedance_rate": [auditor._float_bits(ood_rate)] * 2,
        "maximum_matched_centroid_distance": [auditor._float_bits(temporal)] * 2,
    }
    replay_receipt = {
        "status": "reproduced", "temporal_expected_value": temporal,
        "temporal_reproduced_value": temporal, "ood_expected_value": ood_rate,
        "ood_reproduced_value": ood_rate, "ood_numerator": 76,
        "ood_denominator": 1641, "metric_ieee_float_bits": bits,
    }
    parent_id = "a" * 64
    parent = tmp_path / parent_id
    parent.mkdir()
    cluster_header = "half_label,primary_component_index,half_component_index,primary_component_fingerprint,half_component_fingerprint,sample_count,exceedance_count,euclidean_distance,top_drift_features,diagnostic_only\n"
    cluster_row = f"B,3,3,{primary_fps[3]},{half_fps[('B', 3)]},411,18,{format(temporal, '.17g')},{'|'.join(names)},true\n"
    parent_reproduction = {
        "status": {"status": "reproduced", "ood_exceedance_numerator": 76, "ood_denominator": 1641,
            "temporal_half_refit_stability_reproduction": {"expected_value": temporal, "reproduced_value": temporal},
            "primary_model_ood_reproduction": {"expected_value": ood_rate, "reproduced_value": ood_rate}},
        "metric_ieee_float_bits": bits,
        "half_replays": [{
            "receipt": {"half_label": half, "anchor_count": 820 if half == "A" else 821},
            "matched_pairs": [{"half_label": half, "half_component_index": component_index,
                "half_component_fingerprint": half_fps[(half, component_index)],
                "primary_component_index": component_index,
                "primary_component_fingerprint": primary_fps[component_index]}
                for component_index in range(4)]}
            for half in ("A", "B")],
    }
    parent_payloads = {
        "frozen_k4_cluster_diagnostics.csv": (cluster_header + cluster_row).encode(),
        auditor.PARENT_REPRODUCTION: _document(parent_reproduction),
    }
    identity_payload = {"synthetic_fixture": "frozen-k4-audit-v1"}
    input_hash = hashlib.sha256(_document(identity_payload)).hexdigest()
    parent_manifest = {"run_id": parent_id, "input_identity_sha256": input_hash,
        "file_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in parent_payloads.items()},
        "status": "reproduced", "diagnostic_only": True, "primary_replacement_allowed": False}
    for name, data in parent_payloads.items():
        (parent / name).write_bytes(data)
    (parent / "manifest.json").write_bytes(_document(parent_manifest))
    parent_manifest_hash = hashlib.sha256((parent / "manifest.json").read_bytes()).hexdigest()
    implementation_files = {relative: hashlib.sha256(Path(__file__).parents[1].joinpath(*relative.split("/")).read_bytes()).hexdigest()
                            for relative in auditor.IMPLEMENTATION_FILES}
    implementation_hash = hashlib.sha256(_canonical(implementation_files)).hexdigest()
    fitted = {"metric_name": "fitted_parameter_centroid_distance", "half_label": "B",
        "primary_component_index": 3, "half_component_index": 3,
        "primary_component_fingerprint": primary_fps[3], "half_component_fingerprint": half_fps[("B", 3)],
        "distance": temporal, "top_five_drift_features": names}
    artifacts = _independent_artifacts(
        completion, parent_id=parent_id, parent_manifest_hash=parent_manifest_hash,
        input_hash=input_hash, implementation_files=implementation_files,
        implementation_hash=implementation_hash, replay_receipt=replay_receipt,
        fitted=fitted, registry_hash=registry_hash,
    )
    identity = {"diagnostic_schema_version": auditor.SCHEMA, "parent_run_id": parent_id,
        "parent_manifest_sha256": parent_manifest_hash, "input_identity_sha256": input_hash,
        "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        "registry_sha256": registry_hash, "implementation_sha256": implementation_hash,
        "completion_scope": auditor.SCOPE, "replay_parent_match_verified": True,
        "thresholds": auditor.THRESHOLDS}
    child_id = hashlib.sha256(_document(identity)).hexdigest()
    child = tmp_path / child_id
    child.mkdir()
    for name, data in artifacts.items():
        (child / name).write_bytes(data)
    child_manifest = {"run_id": child_id, "parent_run_id": parent_id,
        "parent_manifest_sha256": parent_manifest_hash, "input_identity_sha256": input_hash,
        "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION, "registry_sha256": registry_hash,
        "implementation_file_sha256": implementation_files, "implementation_sha256": implementation_hash,
        "completion_scope": auditor.SCOPE, "replay_parent_match_verified": True,
        "thresholds": auditor.THRESHOLDS,
        "file_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in artifacts.items()},
        "file_bytes": {name: len(data) for name, data in artifacts.items()},
        "diagnostic_schema_version": auditor.SCHEMA, "status": "completed",
        "diagnostic_only": True, "primary_replacement_allowed": False}
    (child / "manifest.json").write_bytes(_document(child_manifest))
    source = SimpleNamespace(primary_fit=primary, vectors=tuple(vectors),
                             attempt_payload=MappingProxyType({
                                 "model_gates": MappingProxyType({"distance_threshold": 1.0})
                             }),
                             identity=SimpleNamespace(canonical_payload=lambda: identity_payload))
    return auditor, parent, child, source


def test_synthetic_1641_row_fixture_is_audited_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "src.application.services.frozen_k4_diagnosis_completion", _ForbiddenModule())
    monkeypatch.setitem(sys.modules, "scripts.complete_frozen_three_day_k4_diagnosis", _ForbiddenModule())
    auditor = _load()
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path, auditor)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    receipt = auditor.audit_frozen_k4_diagnosis_completion(
        parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
        raw_kline_root=tmp_path / "raw")
    assert receipt["status"] == "verified"
    assert receipt["component_0_ood"] == "24/409"
    assert receipt["checked_offsets"] == 10


def test_full_audit_accepts_production_sample_receipt_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    producer_receipt = FixedSampleReceipt(
        0, "2021-01-01T00:00:00Z", "A", 0, "8" * 24,
        0, "a" * 24, 0, "a" * 24, 0.5, 1.0, False,
    )
    name = "frozen_k4_diagnosis_completion.json"
    payload = json.loads((child / name).read_bytes())
    for receipt in payload["fixed_sample_receipts"]:
        receipt["assignment_source"] = producer_receipt.assignment_source
    (child / name).write_bytes(_document(payload))
    _rehash_child_artifact(child, name)

    receipt = auditor.audit_frozen_k4_diagnosis_completion(
        parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
        raw_kline_root=tmp_path / "raw")

    assert receipt["status"] == "verified"


@pytest.mark.parametrize("mutation", [
    "frozen_k4_diagnosis_completion.json",
    "frozen_k4_component_0_ood_feature_summary.csv",
    "frozen_k4_component_0_ood_family_summary.csv",
    "frozen_k4_offset_empirical_diagnostics.csv",
    "frozen_k4_offset_feature_contributions.csv",
    "frozen_k4_diagnosis_completion.md",
])
def test_synthetic_artifact_mutations_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    target = child / mutation
    target.write_bytes(target.read_bytes() + b"x")
    with pytest.raises(auditor.AuditError, match="artifact hash mismatch"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


@pytest.mark.parametrize("mutated_relative", (
    "scripts/complete_frozen_three_day_k4_diagnosis.py",
    "src/application/services/frozen_k4_diagnosis_completion.py",
    "src/domain/regime/frozen_k4_diagnosis_completion.py",
))
def test_synthetic_producer_mutation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutated_relative: str,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    fake_root = tmp_path / "producer-copy"
    for relative in auditor.IMPLEMENTATION_FILES:
        source_file = Path(__file__).parents[1].joinpath(*relative.split("/"))
        target = fake_root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_file.read_bytes())
    producer = fake_root.joinpath(*mutated_relative.split("/"))
    producer.write_bytes(producer.read_bytes() + b"\n# one-byte-identity-mutation\n")
    monkeypatch.setattr(auditor, "REPO_ROOT", fake_root)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    with pytest.raises(auditor.AuditError, match="producer implementation"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


def _rehash_child_artifact(child: Path, name: str) -> None:
    manifest_path = child / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    data = (child / name).read_bytes()
    manifest["file_sha256"][name] = hashlib.sha256(data).hexdigest()
    manifest["file_bytes"][name] = len(data)
    manifest_path.write_bytes(_document(manifest))


@pytest.mark.parametrize("mutation", (
    "component_flag", "markdown_claim", "appended_false_flag", "conflicting_offset",
))
def test_synthetic_analytical_mutations_fail_after_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    if mutation == "component_flag":
        name = "frozen_k4_diagnosis_completion.json"
        payload = json.loads((child / name).read_bytes())
        payload["component_zero_ood"]["volatility_family_concentration"] = False
        (child / name).write_bytes(_document(payload))
    else:
        name = "frozen_k4_diagnosis_completion.md"
        text = (child / name).read_text(encoding="utf-8")
        if mutation == "markdown_claim":
            text = text.replace("Top five features:", "Top five mutated:")
        elif mutation == "appended_false_flag":
            text += "- volatility_family_concentration=false\n"
        else:
            detail = next(line for line in text.splitlines() if "3-day offset=0" in line)
            text += detail.replace("offset=0", "offset=0 conflicting=true") + "\n"
        (child / name).write_text(text, encoding="utf-8", newline="")
    _rehash_child_artifact(child, name)
    with pytest.raises(auditor.AuditError, match="volatility_family_concentration|Markdown bytes"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


@pytest.mark.parametrize("record_type", ("ood", "conclusion"))
def test_synthetic_duplicate_diagnostic_identity_fails_after_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_type: str,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    name = "frozen_k4_offset_empirical_diagnostics.csv"
    with (child / name).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        rows = list(reader)
    indices = [index for index, row in enumerate(rows) if row["record_type"] == record_type]
    rows[indices[1]] = dict(rows[indices[0]])
    with (child / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    _rehash_child_artifact(child, name)
    with pytest.raises(auditor.AuditError, match=f"{record_type.upper() if record_type == 'ood' else record_type} identities"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


def _rename_child_for_manifest_identity(child: Path) -> Path:
    manifest_path = child / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    identity = {
        "diagnostic_schema_version": manifest["diagnostic_schema_version"],
        "parent_run_id": manifest["parent_run_id"],
        "parent_manifest_sha256": manifest["parent_manifest_sha256"],
        "input_identity_sha256": manifest["input_identity_sha256"],
        "registry_schema_version": manifest["registry_schema_version"],
        "registry_sha256": manifest["registry_sha256"],
        "implementation_sha256": manifest["implementation_sha256"],
        "completion_scope": manifest["completion_scope"],
        "replay_parent_match_verified": manifest["replay_parent_match_verified"],
        "thresholds": manifest["thresholds"],
    }
    new_id = hashlib.sha256(_document(identity)).hexdigest()
    manifest["run_id"] = new_id
    manifest_path.write_bytes(_document(manifest))
    target = child.parent / new_id
    child.rename(target)
    return target


def test_full_audit_rejects_rehashed_half_boundary_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    name = "frozen_k4_diagnosis_completion.json"
    payload = json.loads((child / name).read_bytes())
    payload["fixed_sample_receipts"][0]["half_label"] = "B"
    (child / name).write_bytes(_document(payload))
    _rehash_child_artifact(child, name)
    with pytest.raises(auditor.AuditError, match="sample half boundary"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


def test_full_audit_rejects_rehashed_parent_match_graph_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    reproduction_path = parent / auditor.PARENT_REPRODUCTION
    reproduction = json.loads(reproduction_path.read_bytes())
    reproduction["half_replays"][0]["matched_pairs"][0]["half_component_fingerprint"] = "f" * 24
    reproduction_path.write_bytes(_document(reproduction))
    parent_manifest_path = parent / "manifest.json"
    parent_manifest = json.loads(parent_manifest_path.read_bytes())
    parent_manifest["file_sha256"][auditor.PARENT_REPRODUCTION] = hashlib.sha256(reproduction_path.read_bytes()).hexdigest()
    parent_manifest_path.write_bytes(_document(parent_manifest))
    new_parent_hash = hashlib.sha256(parent_manifest_path.read_bytes()).hexdigest()
    json_name = "frozen_k4_diagnosis_completion.json"
    payload = json.loads((child / json_name).read_bytes())
    payload["parent_provenance"]["parent_manifest_sha256"] = new_parent_hash
    (child / json_name).write_bytes(_document(payload))
    child_manifest_path = child / "manifest.json"
    child_manifest = json.loads(child_manifest_path.read_bytes())
    child_manifest["parent_manifest_sha256"] = new_parent_hash
    child_manifest["file_sha256"][json_name] = hashlib.sha256((child / json_name).read_bytes()).hexdigest()
    child_manifest["file_bytes"][json_name] = (child / json_name).stat().st_size
    child_manifest_path.write_bytes(_document(child_manifest))
    child = _rename_child_for_manifest_identity(child)
    with pytest.raises(auditor.AuditError, match="sample receipt parent matched-pair identity"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


def test_full_audit_rejects_rehashed_manifest_registry_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    forged_hash = "f" * 64
    json_name = "frozen_k4_diagnosis_completion.json"
    payload = json.loads((child / json_name).read_bytes())
    payload["registry_provenance"]["registry_sha256"] = forged_hash
    (child / json_name).write_bytes(_document(payload))
    manifest_path = child / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["registry_sha256"] = forged_hash
    manifest["file_sha256"][json_name] = hashlib.sha256((child / json_name).read_bytes()).hexdigest()
    manifest["file_bytes"][json_name] = (child / json_name).stat().st_size
    manifest_path.write_bytes(_document(manifest))
    child = _rename_child_for_manifest_identity(child)
    with pytest.raises(auditor.AuditError, match="independently recomputed registry hash"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


def test_full_audit_rejects_parent_child_run_id_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    collision_root = tmp_path / "collision-root"
    collision_root.mkdir()
    collision = collision_root / parent.name
    shutil.copytree(child, collision)
    manifest_path = collision / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["run_id"] = parent.name
    manifest_path.write_bytes(_document(manifest))
    with pytest.raises(auditor.AuditError, match="parent and child run IDs must differ"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=collision, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


@pytest.mark.parametrize("mutation", ("extra_top_level", "component_diagnostic_false"))
def test_full_audit_rejects_rehashed_json_schema_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    name = "frozen_k4_diagnosis_completion.json"
    payload = json.loads((child / name).read_bytes())
    if mutation == "extra_top_level":
        payload["surplus_claim"] = "forbidden"
    else:
        payload["component_zero_ood"]["diagnostic_only"] = False
    (child / name).write_bytes(_document(payload))
    _rehash_child_artifact(child, name)
    with pytest.raises(auditor.AuditError, match="completion JSON fields|Component 0 diagnostic-only"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


@pytest.mark.parametrize("record_type,unused_field,value", (
    ("centroid", "ood_numerator", "999"),
    ("ood", "half_label", "A"),
    ("conclusion", "sample_count", "1"),
))
def test_full_audit_rejects_rehashed_unused_tagged_csv_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_type: str,
    unused_field: str, value: str,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    name = "frozen_k4_offset_empirical_diagnostics.csv"
    with (child / name).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        rows = list(reader)
    target = next(row for row in rows if row["record_type"] == record_type)
    target[unused_field] = value
    with (child / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    _rehash_child_artifact(child, name)
    with pytest.raises(auditor.AuditError, match=f"field {unused_field} differs"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


@pytest.mark.parametrize("root_name", ("parent", "completion"))
def test_full_audit_rejects_root_symlink_before_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root_name: str,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    link = tmp_path / f"{root_name}-link"
    try:
        link.symlink_to(parent if root_name == "parent" else child, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this OS")
    kwargs = {"parent_run": link if root_name == "parent" else parent,
              "completion_run": link if root_name == "completion" else child,
              "model_attempt": tmp_path / "model", "raw_kline_root": tmp_path / "raw"}
    with pytest.raises(auditor.AuditError, match=f"{root_name} root must be a real directory"):
        auditor.audit_frozen_k4_diagnosis_completion(**kwargs)


@pytest.mark.parametrize("root_name", ("parent", "completion"))
def test_full_audit_rejects_root_reparse_before_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root_name: str,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    original = auditor._is_link_or_reparse
    blocked = parent if root_name == "parent" else child
    monkeypatch.setattr(
        auditor, "_is_link_or_reparse",
        lambda path: True if Path(path) == blocked else original(Path(path)),
    )
    with pytest.raises(auditor.AuditError, match=f"{root_name} root must be a real directory"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


@pytest.mark.parametrize("error", (OSError("io"), ValueError("value")))
def test_source_loader_failures_are_normalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception,
) -> None:
    auditor, parent, child, _ = _synthetic_end_to_end_fixture(tmp_path)
    def fail(*_: object) -> object:
        raise error
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", fail)
    with pytest.raises(auditor.AuditError, match="source could not be loaded"):
        auditor.audit_frozen_k4_diagnosis_completion(
            parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
            raw_kline_root=tmp_path / "raw")


def test_real_published_fixture_is_audited_end_to_end_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _real_fixture_paths()
    if paths is None:
        pytest.skip("canonical Task 9 completion fixture is not published yet")
    monkeypatch.setitem(sys.modules, "src.application.services.frozen_k4_diagnosis_completion", _ForbiddenModule())
    monkeypatch.setitem(sys.modules, "scripts.complete_frozen_three_day_k4_diagnosis", _ForbiddenModule())
    module = _load()
    parent, child, model, raw = paths
    receipt = module.audit_frozen_k4_diagnosis_completion(
        parent_run=parent, completion_run=child, model_attempt=model, raw_kline_root=raw)
    assert receipt["status"] == "verified"
    assert receipt["checked_file_count"] == 7
    assert receipt["checked_offsets"] == 10
    assert receipt["component_0_ood"] == "24/409"


@pytest.mark.parametrize("mutation", (
    "artifact:frozen_k4_diagnosis_completion.json",
    "artifact:frozen_k4_component_0_ood_feature_summary.csv",
    "artifact:frozen_k4_component_0_ood_family_summary.csv",
    "artifact:frozen_k4_offset_empirical_diagnostics.csv",
    "artifact:frozen_k4_offset_feature_contributions.csv",
    "artifact:frozen_k4_diagnosis_completion.md",
    "producer",
))
def test_real_fixture_mutations_fail_closed_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    paths = _real_fixture_paths()
    if paths is None:
        pytest.skip("canonical Task 9 completion fixture is not published yet")
    module = _load()
    parent, child, model, raw = paths
    if mutation.startswith("artifact:"):
        copied = tmp_path / child.name
        shutil.copytree(child, copied)
        target = copied / mutation.split(":", 1)[1]
        target.write_bytes(target.read_bytes() + b"x")
        with pytest.raises(module.AuditError, match="artifact hash mismatch"):
            module.audit_frozen_k4_diagnosis_completion(
                parent_run=parent, completion_run=copied,
                model_attempt=model, raw_kline_root=raw)
    else:
        fake_root = tmp_path / "repo"
        for relative in module.IMPLEMENTATION_FILES:
            source = Path(__file__).parents[1].joinpath(*relative.split("/"))
            target = fake_root.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        producer = fake_root / "scripts/complete_frozen_three_day_k4_diagnosis.py"
        producer.write_bytes(producer.read_bytes() + b"\n# mutation\n")
        monkeypatch.setattr(module, "REPO_ROOT", fake_root)
        with pytest.raises(module.AuditError, match="producer implementation"):
            module.audit_frozen_k4_diagnosis_completion(
                parent_run=parent, completion_run=child,
                model_attempt=model, raw_kline_root=raw)
