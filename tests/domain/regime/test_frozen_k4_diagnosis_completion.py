import hashlib
import json
from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from src.domain.regime.frozen_k4_diagnosis_completion import (
    COMPLETION_ARTIFACT_FILENAMES,
    COMPLETION_IMPLEMENTATION_FILES,
    COMPLETION_SCOPE,
    COMPONENT_ZERO_ANALYSIS_SCOPE,
    DIAGNOSTIC_SCHEMA_VERSION,
    RECURRENT_TOP1_THRESHOLD,
    SINGLE_FEATURE_THRESHOLD,
    VOLATILITY_FAMILY_THRESHOLD,
    FrozenK4DiagnosisCompletionManifest,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _implementation_hashes():
    return {
        name: (SHA_A, SHA_B, SHA_C)[index]
        for index, name in enumerate(COMPLETION_IMPLEMENTATION_FILES)
    }


def _aggregate(hashes):
    payload = json.dumps(
        dict(sorted(hashes.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manifest_kwargs():
    implementation_hashes = _implementation_hashes()
    return {
        "run_id": SHA_A,
        "parent_run_id": SHA_B,
        "parent_manifest_sha256": SHA_C,
        "input_identity_sha256": SHA_D,
        "registry_schema_version": "chart-feature-registry-v1",
        "registry_sha256": SHA_E,
        "implementation_file_sha256": implementation_hashes,
        "implementation_sha256": _aggregate(implementation_hashes),
        "completion_scope": COMPLETION_SCOPE,
        "replay_parent_match_verified": True,
        "thresholds": {
            "recurrent_top1_threshold": RECURRENT_TOP1_THRESHOLD,
            "single_feature_threshold": SINGLE_FEATURE_THRESHOLD,
            "volatility_family_threshold": VOLATILITY_FAMILY_THRESHOLD,
        },
        "file_sha256": {
            name: SHA_A for name in COMPLETION_ARTIFACT_FILENAMES
        },
        "file_bytes": {name: 1 for name in COMPLETION_ARTIFACT_FILENAMES},
    }


def test_contract_constants_and_top_level_scope_are_exact():
    assert DIAGNOSTIC_SCHEMA_VERSION == "frozen-k4-diagnosis-completion-v1"
    assert COMPLETION_SCOPE == "frozen-k4-diagnosis-completion"
    assert COMPONENT_ZERO_ANALYSIS_SCOPE == "primary-component-0-ood-exceedances"
    assert COMPLETION_SCOPE != COMPONENT_ZERO_ANALYSIS_SCOPE
    assert SINGLE_FEATURE_THRESHOLD == 0.50
    assert VOLATILITY_FAMILY_THRESHOLD == 0.70
    assert RECURRENT_TOP1_THRESHOLD == 0.50
    assert COMPLETION_IMPLEMENTATION_FILES == (
        "scripts/complete_frozen_three_day_k4_diagnosis.py",
        "src/application/services/frozen_k4_diagnosis_completion.py",
        "src/domain/regime/frozen_k4_diagnosis_completion.py",
    )
    assert COMPLETION_ARTIFACT_FILENAMES == frozenset(
        {
            "frozen_k4_diagnosis_completion.json",
            "frozen_k4_component_0_ood_feature_summary.csv",
            "frozen_k4_component_0_ood_family_summary.csv",
            "frozen_k4_offset_empirical_diagnostics.csv",
            "frozen_k4_offset_feature_contributions.csv",
            "frozen_k4_diagnosis_completion.md",
        }
    )


def test_valid_manifest_has_deterministic_complete_canonical_payload():
    manifest = FrozenK4DiagnosisCompletionManifest(**_manifest_kwargs())

    payload = manifest.canonical_payload()

    assert payload == {
        **_manifest_kwargs(),
        "implementation_file_sha256": dict(
            sorted(_manifest_kwargs()["implementation_file_sha256"].items())
        ),
        "thresholds": dict(sorted(_manifest_kwargs()["thresholds"].items())),
        "file_sha256": dict(sorted(_manifest_kwargs()["file_sha256"].items())),
        "file_bytes": dict(sorted(_manifest_kwargs()["file_bytes"].items())),
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "status": "completed",
        "diagnostic_only": True,
        "primary_replacement_allowed": False,
    }
    assert "analysis_scope" not in payload


def test_manifest_defensively_copies_and_freezes_all_mappings():
    kwargs = _manifest_kwargs()
    manifest = FrozenK4DiagnosisCompletionManifest(**kwargs)
    kwargs["thresholds"]["single_feature_threshold"] = 0.99
    kwargs["file_bytes"][next(iter(COMPLETION_ARTIFACT_FILENAMES))] = 99

    for value in (
        manifest.implementation_file_sha256,
        manifest.thresholds,
        manifest.file_sha256,
        manifest.file_bytes,
    ):
        assert isinstance(value, MappingProxyType)
        with pytest.raises(TypeError):
            value["new"] = "value"
    assert tuple(manifest.implementation_file_sha256) == tuple(
        sorted(COMPLETION_IMPLEMENTATION_FILES)
    )
    with pytest.raises(FrozenInstanceError):
        manifest.status = "changed"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_id", "A" * 64, "canonical SHA-256"),
        ("parent_run_id", "abc", "canonical SHA-256"),
        ("parent_manifest_sha256", "g" * 64, "canonical SHA-256"),
        ("input_identity_sha256", "", "canonical SHA-256"),
        ("registry_sha256", 1, "canonical SHA-256"),
        ("implementation_sha256", SHA_A, "implementation_sha256"),
        ("diagnostic_schema_version", "v2", "schema"),
        ("completion_scope", COMPONENT_ZERO_ANALYSIS_SCOPE, "completion scope"),
        ("completion_scope", "other", "completion scope"),
        ("status", "reproduced", "status"),
        ("replay_parent_match_verified", False, "replay"),
        ("replay_parent_match_verified", 1, "replay"),
        ("diagnostic_only", False, "diagnostic-only"),
        ("diagnostic_only", 1, "diagnostic-only"),
        ("primary_replacement_allowed", True, "replace"),
        ("primary_replacement_allowed", 0, "replace"),
    ],
)
def test_manifest_rejects_invalid_scalar_contract_fields(field, value, message):
    kwargs = _manifest_kwargs()
    kwargs[field] = value
    with pytest.raises((TypeError, ValueError), match=message):
        FrozenK4DiagnosisCompletionManifest(**kwargs)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: values.pop(COMPLETION_IMPLEMENTATION_FILES[0]),
        lambda values: values.__setitem__("src/domain/regime/extra.py", SHA_A),
        lambda values: values.__setitem__(
            "src\\domain\\regime\\frozen_k4_diagnosis_completion.py", SHA_A
        ),
        lambda values: values.__setitem__(COMPLETION_IMPLEMENTATION_FILES[0], "A" * 64),
    ],
)
def test_manifest_rejects_wrong_implementation_file_map(mutation):
    kwargs = _manifest_kwargs()
    mutation(kwargs["implementation_file_sha256"])
    kwargs["implementation_sha256"] = _aggregate(kwargs["implementation_file_sha256"])
    with pytest.raises(ValueError, match="implementation file"):
        FrozenK4DiagnosisCompletionManifest(**kwargs)


@pytest.mark.parametrize(
    "thresholds",
    [
        {},
        {
            "recurrent_top1_threshold": 0.50,
            "single_feature_threshold": 0.51,
            "volatility_family_threshold": 0.70,
        },
        {
            "recurrent_top1_threshold": 0.50,
            "single_feature_threshold": 0.50,
            "volatility_family_threshold": 0.70,
            "extra": 1.0,
        },
    ],
)
def test_manifest_rejects_nonexact_threshold_contract(thresholds):
    kwargs = _manifest_kwargs()
    kwargs["thresholds"] = thresholds
    with pytest.raises(ValueError, match="threshold"):
        FrozenK4DiagnosisCompletionManifest(**kwargs)


@pytest.mark.parametrize(
    ("field", "mutation", "message"),
    [
        (
            "file_sha256",
            lambda values: values.pop(next(iter(COMPLETION_ARTIFACT_FILENAMES))),
            "artifact filename set",
        ),
        (
            "file_bytes",
            lambda values: values.__setitem__("extra.csv", 1),
            "artifact filename set",
        ),
        (
            "file_sha256",
            lambda values: values.__setitem__("../bad.csv", SHA_A),
            "canonical basenames",
        ),
        (
            "file_sha256",
            lambda values: values.__setitem__(
                next(iter(COMPLETION_ARTIFACT_FILENAMES)), "A" * 64
            ),
            "canonical SHA-256",
        ),
        (
            "file_bytes",
            lambda values: values.__setitem__(
                next(iter(COMPLETION_ARTIFACT_FILENAMES)), 0
            ),
            "positive integer",
        ),
        (
            "file_bytes",
            lambda values: values.__setitem__(
                next(iter(COMPLETION_ARTIFACT_FILENAMES)), True
            ),
            "positive integer",
        ),
    ],
)
def test_manifest_rejects_invalid_artifact_maps(field, mutation, message):
    kwargs = _manifest_kwargs()
    mutation(kwargs[field])
    with pytest.raises(ValueError, match=message):
        FrozenK4DiagnosisCompletionManifest(**kwargs)
