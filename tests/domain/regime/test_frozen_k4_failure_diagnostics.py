from dataclasses import FrozenInstanceError

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
        dependency_metadata_sha256=SHA_2,
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


def test_half_fit_receipt_enforces_labels_and_diagnostic_only_flags():
    receipt = HalfFitReceipt(
        half_label="A",
        anchor_count=820,
        fit_sha256=SHA_A,
    )

    assert receipt.diagnostic_only is True
    assert receipt.primary_replacement_allowed is False
    with pytest.raises(ValueError, match="half label"):
        HalfFitReceipt("C", 820, SHA_A)
    with pytest.raises(ValueError, match="diagnostic-only"):
        HalfFitReceipt("A", 820, SHA_A, diagnostic_only=False)
    with pytest.raises(ValueError, match="replace"):
        HalfFitReceipt("A", 820, SHA_A, primary_replacement_allowed=True)


def test_matched_pair_uses_half_label_fingerprints_and_finite_distances():
    pair = MatchedPair("B", SHA_A, SHA_B, 1, 3, 2.5, 2.5)

    assert pair.canonical_payload()["half_label"] == "B"
    with pytest.raises(ValueError, match="finite"):
        MatchedPair("B", SHA_A, SHA_B, 1, 3, float("nan"), 2.5)


def test_ood_row_uses_strict_greater_than_comparison():
    equal = OODRow.classify(
        anchor_at="2021-01-01T00:00:00Z",
        assigned_component_index=1,
        assigned_component_fingerprint=SHA_A,
        squared_mahalanobis=10.0,
        threshold=10.0,
    )
    above = OODRow.classify(
        anchor_at="2021-01-02T00:00:00Z",
        assigned_component_index=1,
        assigned_component_fingerprint=SHA_A,
        squared_mahalanobis=10.0000000001,
        threshold=10.0,
    )

    assert equal.comparison_operator == ">"
    assert equal.exceeds is False
    assert above.exceeds is True


def test_sensitivity_row_cannot_claim_refit_or_runtime_use():
    row = SensitivityRow(
        half_label="A",
        component_fingerprint=SHA_A,
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
            SHA_A,
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


def test_final_manifest_copies_and_sorts_file_hashes():
    hashes = {"z.json": SHA_A, "a.csv": SHA_B}
    manifest = FrozenK4DiagnosisManifest(
        run_id=SHA_C,
        input_identity_sha256=SHA_D,
        status="reproduced",
        file_sha256=hashes,
    )
    hashes["later.txt"] = SHA_E

    assert tuple(manifest.file_sha256) == ("a.csv", "z.json")
    payload = manifest.canonical_payload()
    assert tuple(payload["file_sha256"]) == ("a.csv", "z.json")
    payload["file_sha256"]["a.csv"] = SHA_A
    assert manifest.file_sha256["a.csv"] == SHA_B
    with pytest.raises(FrozenInstanceError):
        manifest.status = "reproduction_mismatch"
