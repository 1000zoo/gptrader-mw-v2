from dataclasses import FrozenInstanceError
import hashlib
import json

import pytest

from src.domain.regime.frozen_k4_failure_diagnostics import (
    DiagnosisStatus,
    FrozenK4DiagnosisManifest,
    FrozenK4InputIdentity,
    HalfFitReceipt,
    MatchedPair,
    MetricReproduction,
    OODRow,
    SensitivityRow,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_0 = "0" * 64
SHA_1 = "1" * 64
SHA_2 = "2" * 64
FP_A = "a" * 24
FP_B = "b" * 24

SUCCESS_FILES = {
    "frozen_k4_failure_reproduction.json": SHA_A,
    "frozen_k4_cluster_diagnostics.csv": SHA_B,
    "frozen_k4_feature_contributions.csv": SHA_C,
    "frozen_k4_ood_samples.csv": SHA_D,
    "frozen_k4_distance_comparison.csv": SHA_E,
    "frozen_k4_failure_diagnosis.md": SHA_F,
}
MISMATCH_FILES = {
    "frozen_k4_failure_reproduction.json": SHA_A,
    "frozen_k4_failure_diagnosis.md": SHA_F,
}


def _identity() -> FrozenK4InputIdentity:
    return FrozenK4InputIdentity(
        failed_model_attempt_sha256=SHA_A,
        model_file_sha256=SHA_B,
        primary_parameters_sha256=SHA_C,
        scaler_sha256=SHA_D,
        clipping_bounds_sha256=SHA_E,
        feature_schema_sha256=SHA_F,
        source_provenance_sha256=SHA_0,
        source_anchor_manifest_sha256=SHA_1,
        feature_vectors_sha256=SHA_2,
        dependency_metadata_sha256=SHA_A,
        split_at="2023-04-01T00:00:00Z",
        half_a_range=("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
        half_b_range=("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z"),
    )


def test_metric_reproduction_records_bits_tolerance_and_errors():
    result = MetricReproduction.compare(2.3526219570607076, 2.3526219570607076)

    assert result.exact_bit_match is True
    assert result.numeric_tolerance_match is True
    assert result.absolute_error == 0.0
    assert result.relative_error == 0.0


def test_metric_reproduction_rejects_value_outside_frozen_tolerance():
    result = MetricReproduction.compare(2.3526219570607076, 2.3526219571)

    assert result.numeric_tolerance_match is False


def test_metric_reproduction_compares_exact_float64_bits():
    result = MetricReproduction.compare(0.0, -0.0)

    assert result.exact_bit_match is False
    assert result.numeric_tolerance_match is True


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_metric_reproduction_rejects_non_finite_values(value):
    with pytest.raises(ValueError, match="finite"):
        MetricReproduction.compare(1.0, value)


def test_input_identity_requires_canonical_sha256_and_half_open_ranges():
    identity = _identity()

    assert identity.canonical_payload()["half_a_range"] == (
        "2021-01-01T00:00:00Z",
        "2023-04-01T00:00:00Z",
    )
    with pytest.raises(ValueError, match="canonical SHA-256"):
        FrozenK4InputIdentity(
            **{
                **identity.canonical_payload(),
                "model_file_sha256": SHA_B.upper(),
            }
        )


def test_input_identity_payload_is_deterministic_and_detached():
    identity = _identity()
    first = identity.canonical_payload()
    second = identity.canonical_payload()

    assert first == second
    assert first is not second
    first["model_file_sha256"] = SHA_A
    assert identity.model_file_sha256 == SHA_B


def test_feature_vector_hash_changes_canonical_identity_without_exposing_state():
    original = _identity()
    mutated_payload = original.canonical_payload()
    mutated_payload["feature_vectors_sha256"] = SHA_F
    mutated = FrozenK4InputIdentity(**mutated_payload)

    original_bytes = json.dumps(
        original.canonical_payload(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    mutated_bytes = json.dumps(
        mutated.canonical_payload(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert original.feature_vectors_sha256 == SHA_2
    assert mutated.feature_vectors_sha256 == SHA_F
    assert hashlib.sha256(original_bytes).digest() != hashlib.sha256(mutated_bytes).digest()
    mutated_payload["feature_vectors_sha256"] = SHA_0
    assert mutated.feature_vectors_sha256 == SHA_F


def test_feature_vector_hash_requires_canonical_sha256():
    payload = _identity().canonical_payload()
    payload["feature_vectors_sha256"] = SHA_F.upper()

    with pytest.raises(ValueError, match="canonical SHA-256"):
        FrozenK4InputIdentity(**payload)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        (
            "half_a_range",
            ("2021-01-02T00:00:00Z", "2023-04-01T00:00:00Z"),
        ),
        (
            "half_b_range",
            ("2023-04-01T00:00:00Z", "2025-06-29T00:00:00Z"),
        ),
    ],
)
def test_input_identity_rejects_non_frozen_half_boundaries(field_name, value):
    payload = _identity().canonical_payload()
    payload[field_name] = value

    with pytest.raises(ValueError, match="frozen half ranges"):
        FrozenK4InputIdentity(**payload)


def test_half_fit_receipt_enforces_labels_and_diagnostic_only_flags():
    receipt = HalfFitReceipt(
        half_label="A",
        anchor_count=820,
        fit_sha256=SHA_A,
        anchor_range=("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
    )

    assert receipt.diagnostic_only is True
    assert receipt.primary_replacement_allowed is False
    with pytest.raises(ValueError, match="half label"):
        HalfFitReceipt("C", 820, SHA_A)
    with pytest.raises(ValueError, match="diagnostic-only"):
        HalfFitReceipt("A", 820, SHA_A, diagnostic_only=False)
    with pytest.raises(ValueError, match="replace"):
        HalfFitReceipt("A", 820, SHA_A, primary_replacement_allowed=True)


@pytest.mark.parametrize(
    ("half_label", "anchor_count", "anchor_range"),
    [
        (
            "A",
            821,
            ("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
        ),
        (
            "B",
            820,
            ("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z"),
        ),
        (
            "A",
            820,
            ("2023-04-01T00:00:00Z", "2025-06-30T00:00:00Z"),
        ),
        (
            "B",
            821,
            ("2021-01-01T00:00:00Z", "2023-04-01T00:00:00Z"),
        ),
    ],
)
def test_half_fit_receipt_rejects_wrong_count_or_label_range_pair(
    half_label, anchor_count, anchor_range
):
    with pytest.raises(ValueError, match="frozen half"):
        HalfFitReceipt(half_label, anchor_count, SHA_A, anchor_range)


def test_matched_pair_uses_half_label_fingerprints_and_finite_distances():
    pair = MatchedPair("B", FP_A, FP_B, 1, 3, 2.5, 2.5)

    assert pair.canonical_payload()["half_label"] == "B"
    with pytest.raises(ValueError, match="finite"):
        MatchedPair("B", FP_A, FP_B, 1, 3, float("nan"), 2.5)


def test_declared_float_fields_normalize_in_canonical_payloads():
    metric_int = MetricReproduction(1, 2, False, False, 1, 1)
    metric_float = MetricReproduction(1.0, 2.0, False, False, 1.0, 1.0)
    pair_int = MatchedPair("A", FP_A, FP_B, 0, 1, 2, 2)
    pair_float = MatchedPair("A", FP_A, FP_B, 0, 1, 2.0, 2.0)
    ood_int = OODRow("2021-01-01T00:00:00Z", 0, FP_A, 10, 9, True)
    ood_float = OODRow("2021-01-01T00:00:00Z", 0, FP_A, 10.0, 9.0, True)
    sensitivity_int = SensitivityRow("A", FP_A, "mean", 0, 2)
    sensitivity_float = SensitivityRow("A", FP_A, "mean", 0, 2.0)

    for integer_contract, float_contract in (
        (metric_int, metric_float),
        (pair_int, pair_float),
        (ood_int, ood_float),
        (sensitivity_int, sensitivity_float),
    ):
        integer_payload = integer_contract.canonical_payload()
        float_payload = float_contract.canonical_payload()
        assert integer_payload == float_payload
        assert json.dumps(
            integer_payload, sort_keys=True, separators=(",", ":")
        ) == json.dumps(float_payload, sort_keys=True, separators=(",", ":"))

    assert all(
        isinstance(value, float)
        for value in (
            metric_int.expected_value,
            metric_int.reproduced_value,
            metric_int.absolute_error,
            metric_int.relative_error,
            pair_int.matching_cost,
            pair_int.euclidean_distance,
            ood_int.squared_mahalanobis,
            ood_int.threshold,
            sensitivity_int.centroid_distance,
        )
    )


@pytest.mark.parametrize("value", [10**400, -(10**400)])
def test_finite_validation_converts_overflow_to_value_error(value):
    with pytest.raises(ValueError, match="finite"):
        MetricReproduction.compare(1.0, value)


@pytest.mark.parametrize("value", [True, False])
def test_finite_validation_still_rejects_booleans(value):
    with pytest.raises(ValueError, match="finite"):
        MetricReproduction.compare(value, 1.0)


@pytest.mark.parametrize(
    "fingerprint",
    ["a" * 23, "a" * 25, "A" * 24, "g" * 24],
)
def test_component_fingerprint_requires_exactly_24_lowercase_hex(fingerprint):
    with pytest.raises(ValueError, match="24 lowercase hexadecimal"):
        MatchedPair("A", fingerprint, FP_B, 0, 1, 1.0, 1.0)


@pytest.mark.parametrize("index", [True, -1, 4, 5])
def test_matched_pair_rejects_component_index_outside_frozen_k4(index):
    with pytest.raises(ValueError, match="0 through 3"):
        MatchedPair("A", FP_A, FP_B, index, 1, 1.0, 1.0)


def test_ood_row_uses_strict_greater_than_comparison():
    equal = OODRow.classify(
        anchor_at="2021-01-01T00:00:00Z",
        assigned_component_index=1,
        assigned_component_fingerprint=FP_A,
        squared_mahalanobis=10.0,
        threshold=10.0,
    )
    above = OODRow.classify(
        anchor_at="2021-01-02T00:00:00Z",
        assigned_component_index=1,
        assigned_component_fingerprint=FP_A,
        squared_mahalanobis=10.0000000001,
        threshold=10.0,
    )

    assert equal.comparison_operator == ">"
    assert equal.exceeds is False
    assert above.exceeds is True


@pytest.mark.parametrize("index", [False, -1, 4, 10])
def test_ood_row_rejects_component_index_outside_frozen_k4(index):
    with pytest.raises(ValueError, match="0 through 3"):
        OODRow.classify(
            anchor_at="2021-01-01T00:00:00Z",
            assigned_component_index=index,
            assigned_component_fingerprint=FP_A,
            squared_mahalanobis=10.0,
            threshold=9.0,
        )


def test_sensitivity_row_cannot_claim_refit_or_runtime_use():
    row = SensitivityRow(
        half_label="A",
        component_fingerprint=FP_A,
        statistic="coordinate_median",
        excluded_count=3,
        centroid_distance=1.25,
    )

    assert row.assignment_source == "frozen_reproduced_half_assignment"
    assert row.refit_after_exclusion is False
    assert row.diagnostic_only is True
    with pytest.raises(ValueError, match="assignment source"):
        SensitivityRow(
            "A",
            FP_A,
            "coordinate_median",
            3,
            1.25,
            assignment_source="new_fit",
        )


def test_diagnosis_status_preserves_integer_ood_fraction_and_gates_decomposition():
    temporal = MetricReproduction.compare(2.3526219570607076, 2.3526219570607076)
    ood = MetricReproduction.compare(38 / 821, 38 / 821)
    status = DiagnosisStatus.reproduced(
        temporal=temporal,
        primary_ood=ood,
        ood_exceedance_numerator=38,
        ood_denominator=821,
    )

    assert status.decomposition_allowed is True
    assert status.ood_exceedance_numerator == 38
    assert status.ood_denominator == 821
    with pytest.raises(ValueError, match="integers"):
        DiagnosisStatus.reproduced(temporal, ood, 38.0, 821)


def test_diagnosis_status_cannot_open_decomposition_after_mismatch():
    temporal = MetricReproduction.compare(2.0, 2.1)
    ood = MetricReproduction.compare(0.1, 0.1)

    status = DiagnosisStatus.mismatch(
        temporal=temporal,
        primary_ood=ood,
        ood_exceedance_numerator=1,
        ood_denominator=10,
        mismatch_classification="projection-mismatch",
    )

    assert status.decomposition_allowed is False
    assert status.status == "reproduction_mismatch"


def test_diagnosis_status_accepts_causal_terminal_mismatch_when_metrics_match():
    temporal = MetricReproduction.compare(2.0, 2.0)
    ood = MetricReproduction.compare(0.1, 0.1)

    status = DiagnosisStatus.causal_mismatch(
        temporal=temporal,
        primary_ood=ood,
        ood_exceedance_numerator=1,
        ood_denominator=10,
        mismatch_classification="projection-mismatch",
        causal_evidence_sha256=SHA_A,
    )

    assert status.status == "causal_reproduction_mismatch"
    assert status.decomposition_allowed is False
    assert status.causal_evidence_sha256 == SHA_A


def test_pure_numeric_mismatch_still_rejects_equal_metrics_without_causal_evidence():
    equal = MetricReproduction.compare(1.0, 1.0)

    with pytest.raises(ValueError, match="reproduction mismatch"):
        DiagnosisStatus.mismatch(equal, equal, 1, 1, "projection-mismatch")


def test_final_manifest_copies_and_sorts_file_hashes():
    hashes = dict(reversed(tuple(SUCCESS_FILES.items())))
    manifest = FrozenK4DiagnosisManifest(
        run_id=SHA_C,
        input_identity_sha256=SHA_D,
        status="reproduced",
        file_sha256=hashes,
    )
    hashes["later.txt"] = SHA_E

    assert tuple(manifest.file_sha256) == tuple(sorted(SUCCESS_FILES))
    payload = manifest.canonical_payload()
    assert tuple(payload["file_sha256"]) == tuple(sorted(SUCCESS_FILES))
    payload["file_sha256"]["frozen_k4_cluster_diagnostics.csv"] = SHA_A
    assert manifest.file_sha256["frozen_k4_cluster_diagnostics.csv"] == SHA_B
    with pytest.raises(FrozenInstanceError):
        manifest.status = "reproduction_mismatch"


def test_final_manifest_accepts_only_reproduction_files_after_mismatch():
    manifest = FrozenK4DiagnosisManifest(
        run_id=SHA_C,
        input_identity_sha256=SHA_D,
        status="reproduction_mismatch",
        file_sha256=MISMATCH_FILES,
    )

    assert set(manifest.file_sha256) == set(MISMATCH_FILES)


@pytest.mark.parametrize(
    ("status", "file_sha256"),
    [
        ("reproduced", {}),
        (
            "reproduced",
            {
                name: value
                for name, value in SUCCESS_FILES.items()
                if name != "frozen_k4_ood_samples.csv"
            },
        ),
        ("reproduced", {**SUCCESS_FILES, "manifest.json": SHA_0}),
        (
            "reproduction_mismatch",
            {**MISMATCH_FILES, "frozen_k4_cluster_diagnostics.csv": SHA_B},
        ),
        ("reproduction_mismatch", {"frozen_k4_failure_reproduction.json": SHA_A}),
    ],
)
def test_final_manifest_rejects_missing_or_extra_status_artifacts(
    status, file_sha256
):
    with pytest.raises(ValueError, match="artifact filename set"):
        FrozenK4DiagnosisManifest(
            run_id=SHA_C,
            input_identity_sha256=SHA_D,
            status=status,
            file_sha256=file_sha256,
        )
