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
from types import SimpleNamespace

import pytest

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


def _nested_namespace(value: object) -> object:
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _nested_namespace(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_nested_namespace(item) for item in value)
    return value


def _synthetic_end_to_end_fixture(tmp_path: Path):
    auditor = _load()
    import scripts.complete_frozen_three_day_k4_diagnosis as producer

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
        distance_thresholds=(1.0,) * 4,
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
            "assignment_source": "frozen_reproduced_assignments_and_ood_rows",
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
                centroid = [sum(vectors[i].values[name] for i in members) / len(members) for name in names]
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
        return [{
            "sample_scope": scope, "spacing_days": spacing, "offset": offset,
            "primary_component_index": component_index,
            "primary_component_fingerprint": primary_fps[component_index],
            "numerator": sum(receipts[i]["ood_exceeds"] for i in selected if assignments[i] == component_index),
            "denominator": sum(assignments[i] == component_index for i in selected),
            "rate": (sum(receipts[i]["ood_exceeds"] for i in selected if assignments[i] == component_index)
                     / sum(assignments[i] == component_index for i in selected)),
            "distance_source": "frozen_primary_ood_row",
            "threshold_source": "frozen_primary_component_threshold",
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

    completion = _nested_namespace({
        "completion_scope": auditor.SCOPE, "component_zero_ood": component,
        "full_sample_empirical": full_empirical, "full_sample_ood": full_ood,
        "offset_empirical": offsets, "offset_ood": offset_ood,
        "offset_conclusions": conclusions, "sample_receipts": receipts,
        "diagnostic_only": True,
    })
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
    artifacts = producer._render_completion_artifacts(
        completion, parent=SimpleNamespace(run_id=parent_id, manifest_sha256=parent_manifest_hash,
                                           input_identity_sha256=input_hash),
        implementation=SimpleNamespace(file_sha256=implementation_files, implementation_sha256=implementation_hash),
        replay_validation={"parent_receipt": replay_receipt, "new_replay_receipt": replay_receipt,
                           "match_verified": True}, fitted_parameter_summary=fitted)
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
                             identity=SimpleNamespace(canonical_payload=lambda: identity_payload))
    return auditor, parent, child, source


def test_synthetic_1641_row_fixture_is_audited_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    monkeypatch.setattr(auditor, "load_frozen_k4_diagnostic_source", lambda *_: source)
    monkeypatch.setitem(sys.modules, "src.application.services.frozen_k4_diagnosis_completion", _ForbiddenModule())
    monkeypatch.setitem(sys.modules, "scripts.complete_frozen_three_day_k4_diagnosis", _ForbiddenModule())
    receipt = auditor.audit_frozen_k4_diagnosis_completion(
        parent_run=parent, completion_run=child, model_attempt=tmp_path / "model",
        raw_kline_root=tmp_path / "raw")
    assert receipt["status"] == "verified"
    assert receipt["component_0_ood"] == "24/409"
    assert receipt["checked_offsets"] == 10


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


def test_synthetic_producer_mutation_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auditor, parent, child, source = _synthetic_end_to_end_fixture(tmp_path)
    fake_root = tmp_path / "producer-copy"
    for relative in auditor.IMPLEMENTATION_FILES:
        source_file = Path(__file__).parents[1].joinpath(*relative.split("/"))
        target = fake_root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_file.read_bytes())
    producer = fake_root / "scripts/complete_frozen_three_day_k4_diagnosis.py"
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


@pytest.mark.parametrize("mutation", ("component_flag", "markdown_claim"))
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
        (child / name).write_text(text.replace("Top five features:", "Top five mutated:"),
                                 encoding="utf-8", newline="")
    _rehash_child_artifact(child, name)
    with pytest.raises(auditor.AuditError, match="volatility_family_concentration|Markdown Component"):
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
