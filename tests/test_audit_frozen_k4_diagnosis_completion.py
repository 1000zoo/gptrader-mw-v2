from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


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
    (run / "manifest.json").write_bytes(_canonical(manifest))
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
