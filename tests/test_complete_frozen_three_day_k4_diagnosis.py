from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

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
        "frozen_k4_cluster_diagnostics.csv": b"cluster\n",
        "frozen_k4_feature_contributions.csv": b"feature\n",
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
