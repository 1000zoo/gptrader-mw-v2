from __future__ import annotations

from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.complete_frozen_three_day_k4_diagnosis as completion_script

from scripts.complete_frozen_three_day_k4_diagnosis import (
    DEFAULT_PARENT_RUN,
    DEFAULT_OUTPUT_ROOT,
    MANIFEST,
    ParentProvenance,
    PublicationError,
    _completion_identity_payload,
    _completion_implementation_receipt,
    _completion_run_id,
    _directory_bytes,
    _load_parent_provenance,
    _parse_args,
)
from src.domain.regime.frozen_k4_diagnosis_completion import (
    COMPLETION_IMPLEMENTATION_FILES,
    COMPLETION_SCOPE,
    DIAGNOSTIC_SCHEMA_VERSION,
)
from src.domain.regime.frozen_k4_failure_diagnostics import FrozenK4DiagnosisManifest


TEMPORAL = 2.3526219570607076
OOD = 0.04631322364411944
BITS = {
    "maximum_distance_exceedance_rate": (
        "3fa7b65de9d8ffd8",
        "3fa7b65de9d8ffd8",
    ),
    "maximum_matched_centroid_distance": (
        "4002d22b75eb6b05",
        "4002d22b75eb6b05",
    ),
}


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree_state(root: Path) -> tuple[tuple[str, str, bytes | None], ...]:
    rows: list[tuple[str, str, bytes | None]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            rows.append((relative, "link", None))
        elif path.is_dir():
            rows.append((relative, "directory", None))
        else:
            rows.append((relative, "file", path.read_bytes()))
    return tuple(rows)


def _metric(value: float) -> dict[str, object]:
    return {
        "absolute_error": 0.0,
        "exact_bit_match": True,
        "expected_value": value,
        "numeric_tolerance_match": True,
        "relative_error": 0.0,
        "reproduced_value": value,
    }


def _reproduction_payload(
    *,
    input_identity: dict[str, object] | None = None,
    status: str = "reproduced",
    numerator: int = 76,
    denominator: int = 1641,
) -> dict[str, object]:
    identity = input_identity or {"fixture": "frozen-source", "version": 1}
    identity_hash = _sha(_canonical_bytes(identity))
    return {
        "schema_version": "frozen-k4-failure-reproduction-v1",
        "input_identity": identity,
        "input_identity_sha256": identity_hash,
        "metric_ieee_float_bits": {key: list(value) for key, value in BITS.items()},
        "ood_exceedance_count": numerator,
        "ood_sample_count": denominator,
        "status": {
            "causal_evidence_sha256": None,
            "decomposition_allowed": True,
            "diagnostic_only": True,
            "mismatch_classification": None,
            "ood_denominator": denominator,
            "ood_exceedance_numerator": numerator,
            "primary_model_ood_reproduction": _metric(OOD),
            "status": status,
            "temporal_half_refit_stability_reproduction": _metric(TEMPORAL),
        },
    }


def _write_parent(
    root: Path,
    *,
    reproduction: dict[str, object] | None = None,
    dirname: str = "a" * 64,
) -> Path:
    parent = root / dirname
    parent.mkdir()
    reproduction = reproduction or _reproduction_payload()
    payloads = {
        "frozen_k4_failure_reproduction.json": _canonical_bytes(reproduction),
        "frozen_k4_cluster_diagnostics.csv": b"half_label,primary_component_index,half_component_index,primary_component_fingerprint,half_component_fingerprint,sample_count,exceedance_count,euclidean_distance,top_drift_features,diagnostic_only\nB,3,1,1111111111111111111111111111111111111111111111111111111111111111,2222222222222222222222222222222222222222222222222222222222222222,10,1,2.3526219570607076,rv_4h|rv_1d,true\n",
        "frozen_k4_feature_contributions.csv": b"half_label,primary_component_index,half_component_index,feature_name,squared_distance,contribution_ratio\nB,3,1,rv_4h,4,0.75\nB,3,1,rv_1d,1.534831,0.25\n",
        "frozen_k4_ood_samples.csv": b"ood\n",
        "frozen_k4_distance_comparison.csv": b"distance\n",
        "frozen_k4_failure_diagnosis.md": b"# report\n",
    }
    for name, data in payloads.items():
        (parent / name).write_bytes(data)
    manifest = FrozenK4DiagnosisManifest(
        run_id=dirname,
        input_identity_sha256=str(reproduction["input_identity_sha256"]),
        status="reproduced",
        file_sha256={name: _sha(data) for name, data in payloads.items()},
    )
    (parent / MANIFEST).write_bytes(_canonical_bytes(manifest.canonical_payload()))
    return parent


def _identity(parent: ParentProvenance, implementation_hash: str = "e" * 64):
    return _completion_identity_payload(
        parent,
        input_identity_sha256=parent.input_identity_sha256,
        registry_schema_version="btc-chart-regime-ohlcv-3d-v1",
        registry_sha256="d" * 64,
        implementation_sha256=implementation_hash,
    )


def _producer_tree(root: Path) -> None:
    for index, name in enumerate(COMPLETION_IMPLEMENTATION_FILES):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"producer-{index}\n".encode())


def test_parent_loader_validates_hashes_receipt_and_exact_snapshot(tmp_path: Path) -> None:
    parent_dir = _write_parent(tmp_path)
    before = _directory_bytes(parent_dir)

    parent = _load_parent_provenance(parent_dir)

    assert parent.run_id == parent_dir.name
    assert parent.manifest_sha256 == _sha((parent_dir / MANIFEST).read_bytes())
    assert parent.directory_snapshot == before
    assert parent.replay.status == "reproduced"
    assert parent.replay.temporal_expected_value == TEMPORAL
    assert parent.replay.temporal_reproduced_value == TEMPORAL
    assert parent.replay.ood_expected_value == OOD
    assert parent.replay.ood_reproduced_value == OOD
    assert (parent.replay.ood_numerator, parent.replay.ood_denominator) == (76, 1641)
    assert dict(parent.replay.metric_ieee_float_bits) == BITS
    assert _directory_bytes(parent_dir) == before


@pytest.mark.parametrize(
    "mutation",
    ("missing", "extra", "nested", "corrupt", "run_id", "input_identity"),
)
def test_parent_loader_fails_closed_without_mutating_parent(
    tmp_path: Path, mutation: str
) -> None:
    parent_dir = _write_parent(tmp_path)
    if mutation == "missing":
        (parent_dir / "frozen_k4_ood_samples.csv").unlink()
    elif mutation == "extra":
        (parent_dir / "extra.txt").write_text("extra")
    elif mutation == "nested":
        (parent_dir / "nested").mkdir()
    elif mutation == "corrupt":
        (parent_dir / "frozen_k4_ood_samples.csv").write_text("corrupt")
    elif mutation == "run_id":
        parent_dir.rename(tmp_path / ("b" * 64))
        parent_dir = tmp_path / ("b" * 64)
    else:
        reproduction_path = parent_dir / "frozen_k4_failure_reproduction.json"
        reproduction = json.loads(reproduction_path.read_bytes())
        reproduction["input_identity_sha256"] = "f" * 64
        data = _canonical_bytes(reproduction)
        reproduction_path.write_bytes(data)
        manifest_path = parent_dir / MANIFEST
        manifest = json.loads(manifest_path.read_bytes())
        manifest["input_identity_sha256"] = "f" * 64
        manifest["file_sha256"][reproduction_path.name] = _sha(data)
        manifest_path.write_bytes(_canonical_bytes(manifest))
    before = _tree_state(parent_dir)

    with pytest.raises(PublicationError):
        _load_parent_provenance(parent_dir)

    assert _tree_state(parent_dir) == before


def test_parent_loader_rejects_symlink_or_reparse_entry(tmp_path: Path) -> None:
    parent_dir = _write_parent(tmp_path)
    target = tmp_path / "outside.txt"
    target.write_text("outside")
    link = parent_dir / "extra-link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    before = _tree_state(parent_dir)
    with pytest.raises(PublicationError):
        _load_parent_provenance(parent_dir)
    assert _tree_state(parent_dir) == before


@pytest.mark.parametrize("nested_file", (False, True))
def test_directory_snapshot_rejects_nested_entry_added_after_parent_load(
    tmp_path: Path, nested_file: bool
) -> None:
    parent_dir = _write_parent(tmp_path)
    parent = _load_parent_provenance(parent_dir)
    nested = parent_dir / "post-load-nested"
    nested.mkdir()
    if nested_file:
        (nested / "hidden.txt").write_text("not represented by a flat snapshot")

    with pytest.raises(PublicationError):
        _directory_bytes(parent_dir)

    assert MANIFEST in parent.directory_snapshot


def test_directory_snapshot_rejects_symlink_added_after_parent_load(
    tmp_path: Path,
) -> None:
    parent_dir = _write_parent(tmp_path)
    parent = _load_parent_provenance(parent_dir)
    target = tmp_path / "post-load-target.txt"
    target.write_text("outside")
    link = parent_dir / "post-load-link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")

    with pytest.raises(PublicationError):
        _directory_bytes(parent_dir)

    assert MANIFEST in parent.directory_snapshot


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("status", "status"), "reproduction_mismatch"),
        (("status", "ood_exceedance_numerator"), 75),
        (("status", "ood_denominator"), 1640),
        (("ood_exceedance_count",), 75),
        (("metric_ieee_float_bits", "maximum_matched_centroid_distance", 0), "0" * 16),
        (("status", "temporal_half_refit_stability_reproduction", "reproduced_value"), TEMPORAL + 1),
        (("status", "primary_model_ood_reproduction", "expected_value"), OOD + 0.01),
        (("status", "primary_model_ood_reproduction", "absolute_error"), -0.0),
    ),
)
def test_semantically_invalid_but_hash_valid_parent_receipt_is_rejected(
    tmp_path: Path, path: tuple[object, ...], value: object
) -> None:
    reproduction = _reproduction_payload()
    cursor: object = reproduction
    for part in path[:-1]:
        cursor = cursor[part]  # type: ignore[index]
    cursor[path[-1]] = value  # type: ignore[index]
    parent = _write_parent(tmp_path, reproduction=reproduction)
    with pytest.raises(PublicationError):
        _load_parent_provenance(parent)


def test_noncanonical_parent_json_is_rejected_even_when_manifest_hash_matches(
    tmp_path: Path,
) -> None:
    parent = _write_parent(tmp_path)
    reproduction_path = parent / "frozen_k4_failure_reproduction.json"
    reproduction_path.write_bytes(b" " + reproduction_path.read_bytes())
    manifest_path = parent / MANIFEST
    manifest = json.loads(manifest_path.read_bytes())
    manifest["file_sha256"][reproduction_path.name] = _sha(reproduction_path.read_bytes())
    manifest_path.write_bytes(_canonical_bytes(manifest))
    with pytest.raises(PublicationError):
        _load_parent_provenance(parent)


@pytest.mark.parametrize(
    "omitted",
    (
        ("diagnostic_only",),
        ("primary_replacement_allowed",),
        ("diagnostic_only", "primary_replacement_allowed"),
    ),
)
def test_parent_manifest_rejects_omitted_default_policy_fields(
    tmp_path: Path, omitted: tuple[str, ...]
) -> None:
    parent = _write_parent(tmp_path)
    manifest_path = parent / MANIFEST
    manifest = json.loads(manifest_path.read_bytes())
    for field in omitted:
        manifest.pop(field)
    manifest_path.write_bytes(_canonical_bytes(manifest))

    with pytest.raises(PublicationError):
        _load_parent_provenance(parent)


def test_output_root_cannot_be_inside_parent(tmp_path: Path) -> None:
    parent = _load_parent_provenance(_write_parent(tmp_path))
    with pytest.raises(PublicationError):
        _completion_identity_payload(
            parent,
            input_identity_sha256=parent.input_identity_sha256,
            registry_schema_version="btc-chart-regime-ohlcv-3d-v1",
            registry_sha256="d" * 64,
            implementation_sha256="e" * 64,
            output_root=parent.parent_dir / "child",
        )


def test_implementation_receipt_hashes_only_exact_canonical_producer_set(
    tmp_path: Path,
) -> None:
    _producer_tree(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "ignored.py").write_text("ignored")

    first = _completion_implementation_receipt(tmp_path)
    expected = {
        name: _sha((tmp_path / name).read_bytes())
        for name in COMPLETION_IMPLEMENTATION_FILES
    }
    assert dict(first.file_sha256) == dict(sorted(expected.items()))
    assert first.implementation_sha256 == _sha(
        json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    )

    (tmp_path / "tests" / "ignored.py").write_text("changed")
    assert _completion_implementation_receipt(tmp_path) == first
    producer = tmp_path / COMPLETION_IMPLEMENTATION_FILES[0]
    producer.write_bytes(producer.read_bytes() + b"x")
    second = _completion_implementation_receipt(tmp_path)
    assert second.file_sha256 != first.file_sha256
    assert second.implementation_sha256 != first.implementation_sha256


@pytest.mark.parametrize("failure", ("missing", "symlink", "noncanonical_root"))
def test_implementation_receipt_rejects_unsafe_producer_paths(
    tmp_path: Path, failure: str
) -> None:
    _producer_tree(tmp_path)
    if failure == "missing":
        (tmp_path / COMPLETION_IMPLEMENTATION_FILES[0]).unlink()
    elif failure == "symlink":
        producer = tmp_path / COMPLETION_IMPLEMENTATION_FILES[0]
        outside = tmp_path / "outside.py"
        outside.write_text("outside")
        producer.unlink()
        try:
            producer.symlink_to(outside)
        except OSError:
            pytest.skip("symlinks unavailable")
    else:
        tmp_path = tmp_path / ".." / tmp_path.name
    with pytest.raises(PublicationError):
        _completion_implementation_receipt(tmp_path)


@pytest.mark.parametrize(
    "paths",
    (
        (
            COMPLETION_IMPLEMENTATION_FILES[0],
            COMPLETION_IMPLEMENTATION_FILES[0],
            COMPLETION_IMPLEMENTATION_FILES[2],
        ),
        (
            "../outside.py",
            COMPLETION_IMPLEMENTATION_FILES[1],
            COMPLETION_IMPLEMENTATION_FILES[2],
        ),
        (
            "scripts\\complete_frozen_three_day_k4_diagnosis.py",
            COMPLETION_IMPLEMENTATION_FILES[1],
            COMPLETION_IMPLEMENTATION_FILES[2],
        ),
    ),
)
def test_implementation_receipt_rejects_mutated_path_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paths: tuple[str, str, str],
) -> None:
    _producer_tree(tmp_path)
    monkeypatch.setattr(completion_script, "COMPLETION_IMPLEMENTATION_FILES", paths)
    with pytest.raises(PublicationError):
        _completion_implementation_receipt(tmp_path)


def test_child_identity_is_deterministic_and_binds_every_identity_field(
    tmp_path: Path,
) -> None:
    parent = _load_parent_provenance(_write_parent(tmp_path))
    baseline = _identity(parent)
    assert baseline["diagnostic_schema_version"] == DIAGNOSTIC_SCHEMA_VERSION
    assert baseline["completion_scope"] == COMPLETION_SCOPE
    assert baseline["replay_parent_match_verified"] is True
    assert _completion_run_id(baseline, parent.run_id) == _completion_run_id(
        dict(baseline), parent.run_id
    )

    replacements = {
        "diagnostic_schema_version": "frozen-k4-diagnosis-completion-v2",
        "parent_manifest_sha256": "1" * 64,
        "input_identity_sha256": "2" * 64,
        "registry_sha256": "3" * 64,
        "implementation_sha256": "4" * 64,
        "completion_scope": "different-completion",
    }
    baseline_run = _completion_run_id(baseline, parent.run_id)
    for key, value in replacements.items():
        changed = dict(baseline)
        changed[key] = value
        assert _completion_run_id(changed, parent.run_id) != baseline_run
    changed = dict(baseline)
    changed["thresholds"] = dict(changed["thresholds"], recurrent_feature_top1_ratio=0.51)
    assert _completion_run_id(changed, parent.run_id) != baseline_run


def test_child_identity_rejects_input_mismatch_and_parent_collision(tmp_path: Path) -> None:
    parent = _load_parent_provenance(_write_parent(tmp_path))
    with pytest.raises(PublicationError):
        _completion_identity_payload(
            parent,
            input_identity_sha256="0" * 64,
            registry_schema_version="btc-chart-regime-ohlcv-3d-v1",
            registry_sha256="d" * 64,
            implementation_sha256="e" * 64,
        )
    payload = _identity(parent)
    collision = replace(parent, run_id=_completion_run_id(payload, parent.run_id))
    with pytest.raises(PublicationError):
        _completion_run_id(payload, collision.run_id)


def test_argument_defaults_and_explicit_paths() -> None:
    defaults = _parse_args([])
    assert defaults.parent_run == DEFAULT_PARENT_RUN
    assert defaults.output_root == DEFAULT_OUTPUT_ROOT
    args = _parse_args(
        [
            "--parent-run", "parent", "--model-attempt", "model.json",
            "--raw-kline-root", "raw", "--output-root", "output",
        ]
    )
    assert args.parent_run == Path("parent")
    assert args.model_attempt == Path("model.json")
    assert args.raw_kline_root == Path("raw")
    assert args.output_root == Path("output")


def _metric_object(value: float) -> SimpleNamespace:
    return SimpleNamespace(expected_value=value, reproduced_value=value)


def _completion_fixture() -> SimpleNamespace:
    fingerprint = "1" * 64
    half_fingerprint = "2" * 64
    feature_rows = (
        SimpleNamespace(analysis_scope="primary-component-0-ood-exceedances", primary_component_index=0, primary_component_fingerprint=fingerprint, feature_name="rv_4h", registry_family="volatility", registry_schema_version="registry-v1", registry_sha256="d" * 64, contribution_sum=12.0, contribution_ratio=.75, contribution_mean=.5, contribution_median=.4, top1_count=18, top1_ratio=.75, top5_count=24, top5_ratio=1.0, rank=1),
        SimpleNamespace(analysis_scope="primary-component-0-ood-exceedances", primary_component_index=0, primary_component_fingerprint=fingerprint, feature_name="range_ratio_3d", registry_family="range", registry_schema_version="registry-v1", registry_sha256="d" * 64, contribution_sum=4.0, contribution_ratio=.25, contribution_mean=1 / 6, contribution_median=.1, top1_count=6, top1_ratio=.25, top5_count=24, top5_ratio=1.0, rank=2),
    )
    family_rows = (
        SimpleNamespace(analysis_scope="primary-component-0-ood-exceedances", primary_component_index=0, primary_component_fingerprint=fingerprint, family_name="volatility", family_feature_names=("rv_4h",), registry_schema_version="registry-v1", registry_sha256="d" * 64, contribution_sum=12.0, contribution_ratio=.75, concentration_threshold=.7, concentration_rule_applies=True, concentration_result=True),
        SimpleNamespace(analysis_scope="primary-component-0-ood-exceedances", primary_component_index=0, primary_component_fingerprint=fingerprint, family_name="range", family_feature_names=("range_ratio_3d",), registry_schema_version="registry-v1", registry_sha256="d" * 64, contribution_sum=4.0, contribution_ratio=.25, concentration_threshold=.7, concentration_rule_applies=False, concentration_result=False),
    )
    component = SimpleNamespace(analysis_scope="primary-component-0-ood-exceedances", primary_component_index=0, primary_component_fingerprint=fingerprint, assigned_sample_count=409, ood_sample_count=24, registry_schema_version="registry-v1", registry_sha256="d" * 64, feature_rows=feature_rows, family_rows=family_rows, top_five_features=("rv_4h", "range_ratio_3d"), single_feature_concentration=True, volatility_family_concentration=True, recurrent_feature_dominance=True, diagnostic_only=True)
    def empirical(scope: str, spacing: int | None, offset: int | None) -> SimpleNamespace:
        metric = "full_sample_empirical_centroid_distance" if spacing is None else "offset_empirical_centroid_distance"
        centroid = SimpleNamespace(sample_scope=scope, spacing_days=spacing, offset=offset, offset_origin_anchor="anchor-0000", half_label="A", primary_component_index=3, half_component_index=1, primary_component_fingerprint=fingerprint, half_component_fingerprint=half_fingerprint, sample_count=1, sample_share=1.0, centroid_status="available", metric_name=metric, empirical_centroid=(1.0, 2.0), distance=2.0, assignment_source="frozen_reproduced_half_assignment", refit_performed=False, rematch_performed=False, diagnostic_only=True)
        contribution = SimpleNamespace(sample_scope=scope, spacing_days=spacing, offset=offset, half_label="A", primary_component_index=3, half_component_index=1, primary_component_fingerprint=fingerprint, half_component_fingerprint=half_fingerprint, feature_name="rv_4h", registry_family="volatility", squared_distance=4.0, contribution_ratio=1.0, rank=1)
        return SimpleNamespace(sample_scope=scope, spacing_days=spacing, offset=offset, selected_sample_count=1, centroid_rows=(centroid,), feature_rows=(contribution,), maximum_drift_half_label="A", maximum_drift_primary_component_index=3, maximum_drift_half_component_index=1, maximum_drift_primary_component_fingerprint=fingerprint, maximum_drift_half_component_fingerprint=half_fingerprint, maximum_drift_distance=2.0, top_five_drift_features=("rv_4h",))
    offsets = tuple(empirical("offset_subsample", spacing, offset) for spacing in (3, 7) for offset in range(spacing))
    conclusions = tuple(SimpleNamespace(spacing_days=row.spacing_days, offset=row.offset, maximum_drift_half_label="A", maximum_drift_primary_component_index=3, maximum_drift_primary_component_fingerprint=fingerprint, maximum_drift_half_component_index=1, maximum_drift_half_component_fingerprint=half_fingerprint, maximum_ood_primary_component_index=0, maximum_ood_primary_component_fingerprint=fingerprint, top_five_drift_features=("rv_4h",), drift_component_matches_full_sample=True, ood_component_matches_full_sample=(row.offset % 2 == 0), ordered_top5_matches_full_sample=True, top5_set_matches_full_sample=True) for row in offsets)
    full_ood = (SimpleNamespace(sample_scope="full_sample", spacing_days=None, offset=None, primary_component_index=0, primary_component_fingerprint=fingerprint, numerator=24, denominator=409, rate=24 / 409, distance_source="frozen_primary_ood_row", threshold_source="frozen_primary_component_threshold"),)
    offset_ood = tuple(SimpleNamespace(sample_scope="offset_subsample", spacing_days=row.spacing_days, offset=row.offset, primary_component_index=0, primary_component_fingerprint=fingerprint, numerator=1, denominator=10, rate=.1, distance_source="frozen_primary_ood_row", threshold_source="frozen_primary_component_threshold") for row in offsets)
    receipts = tuple(SimpleNamespace(global_index=index, anchor_at=f"anchor-{index:04d}", half_label="A" if index < 820 else "B", half_component_index=1, half_component_fingerprint=half_fingerprint, matched_primary_component_index=3, matched_primary_component_fingerprint=fingerprint, primary_component_index=0, primary_component_fingerprint=fingerprint, squared_mahalanobis=1.0, ood_threshold=2.0, ood_exceeds=False, assignment_source="frozen_reproduced_assignments_and_ood_rows") for index in range(1641))
    return SimpleNamespace(completion_scope=COMPLETION_SCOPE, component_zero_ood=component, full_sample_empirical=empirical("full_sample", None, None), full_sample_ood=full_ood, offset_empirical=offsets, offset_ood=offset_ood, offset_conclusions=conclusions, sample_receipts=receipts, diagnostic_only=True)


def test_rendered_completion_has_exact_artifacts_scopes_and_metric_names() -> None:
    completion = _completion_fixture()
    artifacts = completion_script._render_completion_artifacts(
        completion,
        parent=SimpleNamespace(run_id="a" * 64, manifest_sha256="b" * 64, input_identity_sha256="c" * 64, replay=SimpleNamespace()),
        implementation=SimpleNamespace(file_sha256={name: "e" * 64 for name in COMPLETION_IMPLEMENTATION_FILES}, implementation_sha256="f" * 64),
        replay_validation={"parent_receipt": {}, "new_replay_receipt": {}, "match_verified": True},
        fitted_parameter_summary={"metric_name": "fitted_parameter_centroid_distance", "distance": TEMPORAL},
    )
    assert set(artifacts) == completion_script.COMPLETION_ARTIFACT_FILENAMES
    payload = json.loads(artifacts["frozen_k4_diagnosis_completion.json"])
    assert payload["completion_scope"] == COMPLETION_SCOPE
    assert "analysis_scope" not in payload
    assert payload["component_zero_ood"]["analysis_scope"] == "primary-component-0-ood-exceedances"
    assert payload["implementation_sha256"] == "f" * 64
    assert payload["replay_parent_match_verified"] is True
    assert payload["full_sample_empirical"]["centroid_rows"][0]["metric_name"] == "full_sample_empirical_centroid_distance"
    assert len(payload["offset_consistency"]) == 10
    text = artifacts["frozen_k4_diagnosis_completion.md"].decode()
    assert "fitted_parameter_centroid_distance" in text
    assert "full_sample_empirical_centroid_distance" in text
    assert "offset_empirical_centroid_distance" in text
    assert "mixed" in text
    assert text.count("offset_empirical_centroid_distance:") == 10
    assert "maximum_ood_primary_component=0" in text
    assert "primary_fingerprint=" in text and "half_fingerprint=" in text
    assert "gate pass" not in text.lower() and "gate fail" not in text.lower()
    for name, data in artifacts.items():
        assert b"None" not in data
        if name.endswith(".csv"):
            assert b",nan," not in data.lower()

    feature_csv = list(csv.DictReader(artifacts["frozen_k4_component_0_ood_feature_summary.csv"].decode().splitlines()))
    assert tuple(feature_csv[0]) == completion_script._FEATURE_HEADERS
    assert all(row["analysis_scope"] == "primary-component-0-ood-exceedances" for row in feature_csv)
    assert all(row["primary_component_index"] == "0" for row in feature_csv)
    family_csv = list(csv.DictReader(artifacts["frozen_k4_component_0_ood_family_summary.csv"].decode().splitlines()))
    assert tuple(family_csv[0]) == completion_script._FAMILY_HEADERS
    diagnostics = list(csv.DictReader(artifacts["frozen_k4_offset_empirical_diagnostics.csv"].decode().splitlines()))
    assert {row["record_type"] for row in diagnostics} == {"centroid", "ood", "conclusion"}
    assert all(row["spacing_days"] == "" and row["offset"] == "" for row in diagnostics if row["sample_scope"] == "full_sample")
    assert all(row["offset_origin_anchor"] == "anchor-0000" for row in diagnostics)
    assert all(row["maximum_drift_primary_component_fingerprint"] for row in diagnostics if row["record_type"] in {"centroid", "ood"})
    full_rows = [row for row in diagnostics if row["sample_scope"] == "full_sample"]
    assert {row["maximum_drift_primary_component_index"] for row in full_rows} == {"3"}
    assert {row["maximum_ood_primary_component_index"] for row in full_rows} == {"0"}
    empirical_features = list(csv.DictReader(artifacts["frozen_k4_offset_feature_contributions.csv"].decode().splitlines()))
    assert tuple(empirical_features[0]) == completion_script._EMPIRICAL_FEATURE_HEADERS
    assert {row["metric_name"] for row in diagnostics if row["record_type"] == "centroid"} == {"full_sample_empirical_centroid_distance", "offset_empirical_centroid_distance"}


@pytest.mark.parametrize("failure", ("scope", "receipt_count", "receipt_order"))
def test_renderer_rejects_invalid_nested_scope_or_sample_receipt_ledger(failure: str) -> None:
    completion = _completion_fixture()
    if failure == "scope":
        completion.component_zero_ood.analysis_scope = "wrong"
    elif failure == "receipt_count":
        completion.sample_receipts = completion.sample_receipts[:-1]
    else:
        completion.sample_receipts = tuple(reversed(completion.sample_receipts))
    with pytest.raises(PublicationError):
        completion_script._render_completion_artifacts(
            completion,
            parent=SimpleNamespace(run_id="a" * 64, manifest_sha256="b" * 64, input_identity_sha256="c" * 64, replay=SimpleNamespace()),
            implementation=SimpleNamespace(file_sha256={name: "e" * 64 for name in COMPLETION_IMPLEMENTATION_FILES}, implementation_sha256="f" * 64),
            replay_validation={"parent_receipt": {}, "new_replay_receipt": {}, "match_verified": True},
            fitted_parameter_summary={"metric_name": "fitted_parameter_centroid_distance", "distance": TEMPORAL},
        )


@pytest.mark.parametrize(
    "field",
    ("status", "temporal_expected", "temporal_reproduced", "ood_expected", "ood_reproduced", "numerator", "denominator", "bits"),
)
def test_replay_validation_rejects_every_parent_receipt_mismatch_before_completion(field: str) -> None:
    parent = SimpleNamespace(replay=SimpleNamespace(status="reproduced", temporal_expected_value=TEMPORAL, temporal_reproduced_value=TEMPORAL, ood_expected_value=OOD, ood_reproduced_value=OOD, ood_numerator=76, ood_denominator=1641, metric_ieee_float_bits=BITS))
    replay = SimpleNamespace(status=SimpleNamespace(status="reproduced", temporal_half_refit_stability_reproduction=_metric_object(TEMPORAL), primary_model_ood_reproduction=_metric_object(OOD), ood_exceedance_numerator=76, ood_denominator=1641), metric_ieee_float_bits=BITS)
    assert completion_script._validate_replay_matches_parent(parent, replay)["match_verified"] is True
    bad = SimpleNamespace(**replay.__dict__)
    bad.status = SimpleNamespace(**replay.status.__dict__)
    bad.status.temporal_half_refit_stability_reproduction = SimpleNamespace(**replay.status.temporal_half_refit_stability_reproduction.__dict__)
    bad.status.primary_model_ood_reproduction = SimpleNamespace(**replay.status.primary_model_ood_reproduction.__dict__)
    if field == "status": bad.status.status = "reproduction_mismatch"
    elif field == "temporal_expected": bad.status.temporal_half_refit_stability_reproduction.expected_value += 1
    elif field == "temporal_reproduced": bad.status.temporal_half_refit_stability_reproduction.reproduced_value += 1
    elif field == "ood_expected": bad.status.primary_model_ood_reproduction.expected_value += .01
    elif field == "ood_reproduced": bad.status.primary_model_ood_reproduction.reproduced_value += .01
    elif field == "numerator": bad.status.ood_exceedance_numerator = 75
    elif field == "denominator": bad.status.ood_denominator = 1640
    else: bad.metric_ieee_float_bits = {**BITS, "maximum_distance_exceedance_rate": ("0" * 16, "0" * 16)}
    with pytest.raises(PublicationError):
        completion_script._validate_replay_matches_parent(parent, bad)


def _matching_replay() -> SimpleNamespace:
    return SimpleNamespace(
        status=SimpleNamespace(
            status="reproduced",
            temporal_half_refit_stability_reproduction=_metric_object(TEMPORAL),
            primary_model_ood_reproduction=_metric_object(OOD),
            ood_exceedance_numerator=76,
            ood_denominator=1641,
        ),
        metric_ieee_float_bits=BITS,
    )


def test_publisher_is_atomic_deterministic_and_preserves_parent(tmp_path: Path) -> None:
    (tmp_path / "parent-root").mkdir()
    parent_dir = _write_parent(tmp_path / "parent-root")
    before = _tree_state(parent_dir)
    source = SimpleNamespace(
        identity=SimpleNamespace(canonical_payload=lambda: {"fixture": "frozen-source", "version": 1}),
        primary_fit=object(),
        vectors=(),
    )
    calls: list[str] = []
    kwargs = dict(
        parent_run=parent_dir,
        model_attempt=tmp_path / "model.json",
        raw_kline_root=tmp_path / "raw",
        output_root=tmp_path / "children",
        source_loader=lambda *_: source,
        replay_runner=lambda _: _matching_replay(),
        decomposition_runner=lambda *_: (calls.append("decomposition") or object()),
        completion_runner=lambda *_: (calls.append("completion") or _completion_fixture()),
    )
    first = completion_script.publish_frozen_k4_diagnosis_completion(**kwargs)
    second = completion_script.publish_frozen_k4_diagnosis_completion(**kwargs)
    assert first == second
    assert _tree_state(parent_dir) == before
    manifest = json.loads((first / MANIFEST).read_bytes())
    assert set(manifest["file_sha256"]) == completion_script.COMPLETION_ARTIFACT_FILENAMES
    assert set(manifest["file_bytes"]) == completion_script.COMPLETION_ARTIFACT_FILENAMES
    assert MANIFEST not in manifest["file_sha256"]
    assert manifest["implementation_file_sha256"]
    assert manifest["replay_parent_match_verified"] is True
    assert calls == ["decomposition", "completion", "decomposition", "completion"]
    for name, expected_hash in manifest["file_sha256"].items():
        data = (first / name).read_bytes()
        assert _sha(data) == expected_hash
        assert len(data) == manifest["file_bytes"][name]


def test_publisher_replay_mismatch_stops_before_decomposition_completion_or_publication(
    tmp_path: Path,
) -> None:
    (tmp_path / "parent-root").mkdir()
    parent_dir = _write_parent(tmp_path / "parent-root")
    before = _tree_state(parent_dir)
    source = SimpleNamespace(
        identity=SimpleNamespace(canonical_payload=lambda: {"fixture": "frozen-source", "version": 1}),
        primary_fit=object(), vectors=(),
    )
    bad = _matching_replay()
    bad.status.status = "reproduction_mismatch"
    calls: list[str] = []
    output = tmp_path / "children"
    with pytest.raises(PublicationError):
        completion_script.publish_frozen_k4_diagnosis_completion(
            parent_run=parent_dir,
            model_attempt=tmp_path / "model.json",
            raw_kline_root=tmp_path / "raw",
            output_root=output,
            source_loader=lambda *_: source,
            replay_runner=lambda _: bad,
            decomposition_runner=lambda *_: calls.append("decomposition"),
            completion_runner=lambda *_: calls.append("completion"),
        )
    assert calls == []
    assert not output.exists()
    assert _tree_state(parent_dir) == before


def test_atomic_replace_failure_cleans_temp_and_preserves_parent(tmp_path: Path) -> None:
    (tmp_path / "parent-root").mkdir()
    parent_dir = _write_parent(tmp_path / "parent-root")
    before = _tree_state(parent_dir)
    source = SimpleNamespace(identity=SimpleNamespace(canonical_payload=lambda: {"fixture": "frozen-source", "version": 1}), primary_fit=object(), vectors=())
    output = tmp_path / "children"
    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("seam failure")
    with pytest.raises(OSError, match="seam failure"):
        completion_script.publish_frozen_k4_diagnosis_completion(
            parent_run=parent_dir, model_attempt=tmp_path / "model.json",
            raw_kline_root=tmp_path / "raw", output_root=output,
            source_loader=lambda *_: source, replay_runner=lambda _: _matching_replay(),
            decomposition_runner=lambda *_: object(), completion_runner=lambda *_: _completion_fixture(),
            replace_directory=fail_replace,
        )
    assert list(output.iterdir()) == []
    assert _tree_state(parent_dir) == before


def test_atomic_replace_bad_partial_target_is_removed(tmp_path: Path) -> None:
    output = tmp_path / "out"
    final = output / ("a" * 64)
    def partial(_source: Path, target: Path) -> None:
        target.mkdir()
        (target / "bad").write_text("partial")
        raise OSError("partial")
    with pytest.raises(PublicationError, match="partial final"):
        completion_script._publish_atomically(output, final, {"one": b"1"}, partial)
    assert not final.exists()
    assert list(output.iterdir()) == []


def test_outer_parent_guard_covers_unwrapped_late_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "parent-root").mkdir()
    parent_dir = _write_parent(tmp_path / "parent-root")
    source = SimpleNamespace(identity=SimpleNamespace(canonical_payload=lambda: {"fixture": "frozen-source", "version": 1}), primary_fit=object(), vectors=())
    def mutate_then_fail(_parent: object, _replay: object) -> object:
        (parent_dir / "frozen_k4_ood_samples.csv").write_text("mutated")
        raise RuntimeError("late seam")
    monkeypatch.setattr(completion_script, "_validate_replay_matches_parent", mutate_then_fail)
    with pytest.raises(PublicationError, match="immutable parent changed"):
        completion_script.publish_frozen_k4_diagnosis_completion(
            parent_run=parent_dir, model_attempt=tmp_path / "model.json",
            raw_kline_root=tmp_path / "raw", output_root=tmp_path / "children",
            source_loader=lambda *_: source, replay_runner=lambda _: _matching_replay(),
            decomposition_runner=lambda *_: object(), completion_runner=lambda *_: _completion_fixture(),
        )
