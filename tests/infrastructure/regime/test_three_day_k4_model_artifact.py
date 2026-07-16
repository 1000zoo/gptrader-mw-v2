from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json

import pytest

from src.domain.regime import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    ThreeDayChartFeatureVector,
)
from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.model import RegimeModelConfig, component_fingerprint
from src.infrastructure.regime.three_day_k4_model_artifact import (
    THREE_DAY_K4_MODEL_ARTIFACT_VERSION,
    ThreeDayK4ModelArtifact,
)
from src.infrastructure.regime.sklearn_cluster_diagnostic import SklearnClusterDiagnostic
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import iter_archive_requests


UTC = timezone.utc
NAMES = tuple(THREE_DAY_CHART_FEATURE_REGISTRY_V1[index].name for index in (0, 5, 9, 13))


def _fit() -> ClusterDiagnosticFit:
    config = RegimeModelConfig("gmm", 4, 20260714, "diag", 1e-6)
    means = ((-2.0,) * 4, (-0.5,) * 4, (0.5,) * 4, (2.0,) * 4)
    weights = (0.1, 0.2, 0.3, 0.4)
    covariances = ((1.0,) * 4,) * 4
    records = sorted(
        (
            component_fingerprint(
                model_type="gmm",
                feature_schema_version="btc-chart-regime-ohlcv-3d-v1",
                feature_names=NAMES,
                mean=mean,
                covariance=covariances[index],
                weight=weights[index],
            ),
            mean,
            weights[index],
            covariances[index],
        )
        for index, mean in enumerate(means)
    )
    return ClusterDiagnosticFit(
        schema_version="btc-chart-regime-ohlcv-3d-v1",
        symbol="BTCUSDT",
        config=config,
        feature_names=NAMES,
        lower_bounds=(-10.0,) * 4,
        upper_bounds=(10.0,) * 4,
        medians=(0.0,) * 4,
        scales=(1.0,) * 4,
        fingerprints=tuple(row[0] for row in records),
        means=tuple(row[1] for row in records),
        weights=tuple(row[2] for row in records),
        covariances=tuple(row[3] for row in records),
        distance_thresholds=(),
        converged=True,
        iterations=7,
        lower_bound=-1.25,
    )


def _artifact() -> ThreeDayK4ModelArtifact:
    context_start = datetime(2020, 12, 29, tzinfo=UTC)
    training_end = datetime(2025, 6, 30, tzinfo=UTC)
    provenance = tuple(
        {
            "period": request.period,
            "url": request.url,
            "member_identity": request.filename.removesuffix(".zip") + ".csv",
            "bytes": 123,
            "sha256": "a" * 64,
            "expected_sha256": "a" * 64,
            "checksum_verified": True,
            "source": "klines",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "granularity": request.granularity,
            "requested_start_at": "2020-12-29T00:00:00Z",
            "requested_end_at": "2025-06-30T00:00:00Z",
        }
        for request in iter_archive_requests(
            "klines", "BTCUSDT", context_start, training_end,
            now=training_end + timedelta(days=32),
        )
    )
    return ThreeDayK4ModelArtifact.from_fit(
        _fit(),
        training_start_at=datetime(2021, 1, 1, tzinfo=UTC),
        training_end_at=datetime(2025, 6, 30, tzinfo=UTC),
        first_usable_anchor_at=datetime(2021, 1, 1, tzinfo=UTC),
        last_usable_anchor_at=datetime(2025, 6, 29, tzinfo=UTC),
        usable_anchor_count=1641,
        source_provenance=provenance,
        feature_history_hash="c" * 64,
        fit_input_vector_hash="c" * 64,
        code_provenance_hash="d" * 64,
        model_gates={
            "convergence_required": True,
            "converged": True,
            "iterations": 7,
            "lower_bound": -1.25,
            "finite_scaler_required": True,
            "finite_scaler": True,
            "finite_model_parameters_required": True,
            "finite_model_parameters": True,
            "positive_weights_required": True,
            "minimum_weight": 0.1,
            "weight_sum_expected": 1.0,
            "weight_sum_tolerance": 1e-8,
            "weight_sum": 1.0,
            "covariance_floor_threshold": 1e-6,
            "minimum_covariance": 1.0,
            "component_count_expected": 4,
            "component_count": 4,
            "all_components_represented_required": True,
            "minimum_adjusted_rand_index": 0.9,
            "minimum_adjusted_rand_index_threshold": 0.8,
            "minimum_normalized_mutual_information": 0.9,
            "minimum_normalized_mutual_information_threshold": 0.8,
            "maximum_matched_centroid_distance": 0.4,
            "maximum_matched_centroid_distance_threshold": 0.5,
            "maximum_prevalence_drift": 0.1,
            "maximum_prevalence_drift_threshold": 0.2,
            "low_confidence_rate": 0.1,
            "maximum_low_confidence_rate_threshold": 0.25,
            "gmm_probability_threshold": 0.65,
            "gmm_margin_threshold": 0.10,
            "minimum_observed_dominant_probability": 0.8,
            "minimum_observed_probability_margin": 0.2,
            "distance_threshold": "not_applicable_for_gmm",
            "distance_result": "not_applicable_for_gmm",
            "distance_threshold_policy": "not_applicable_for_gmm",
            "feature_registry_version_expected": "three-day-chart-feature-registry-v1",
            "feature_registry_exact": True,
            "feature_family_cap_maximum_count": 5,
            "feature_family_cap_maximum_share": 0.5,
            "feature_family_observed_maximum_count": 1,
            "feature_family_observed_maximum_share": 0.25,
            "feature_family_cap_passed": True,
            "all_components_represented": True,
            "all_chronological_blocks_represented_required": True,
            "all_chronological_blocks_represented": True,
            "nondegenerate_confidence": True,
            "passed": True,
        },
    )


def _vector() -> ThreeDayChartFeatureVector:
    values = {spec.name: 0.0 for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
    return ThreeDayChartFeatureVector(
        "BTCUSDT",
        datetime(2025, 7, 7, tzinfo=UTC),
        datetime(2025, 7, 4, tzinfo=UTC),
        values,
    )


def test_artifact_round_trip_is_canonical_context_independent_and_assignment_equivalent() -> None:
    artifact = _artifact()
    encoded = artifact.to_json()
    restored = ThreeDayK4ModelArtifact.from_json(encoded)

    assert artifact.artifact_version == THREE_DAY_K4_MODEL_ARTIFACT_VERSION
    assert restored.to_json() == encoded
    assert restored.artifact_hash == artifact.artifact_hash
    assert len(set(restored.component_fingerprints)) == 4
    assert all(len(value) == 24 and value == value.lower() for value in restored.component_fingerprints)
    assert restored.assign(_vector()) == artifact.assign(_vector())
    expected = SklearnClusterDiagnostic().assign(
        _fit(), (_vector(),), THREE_DAY_CHART_FEATURE_REGISTRY_V1
    )[0]
    actual = restored.assign(_vector())
    expected_index = _fit().fingerprints.index(expected.fingerprint)
    assert actual.fingerprint == restored.numeric_index_to_fingerprint[expected_index]
    assert actual.dominant_probability == pytest.approx(expected.dominant_probability, abs=1e-15)
    assert actual.second_probability == pytest.approx(expected.second_probability, abs=1e-15)


def test_artifact_component_ids_use_original_feature_space_profiles() -> None:
    fit = _fit()
    scaled = ClusterDiagnosticFit(
        **{
            **fit.__dict__,
            "medians": (10.0, 20.0, 30.0, 40.0),
            "scales": (2.0, 3.0, 4.0, 5.0),
            "fingerprints": tuple(
                component_fingerprint(
                    model_type="gmm",
                    feature_schema_version=fit.schema_version,
                    feature_names=fit.feature_names,
                    mean=mean,
                    covariance=fit.covariances[index],
                    weight=fit.weights[index],
                )
                for index, mean in enumerate(fit.means)
            ),
        }
    )
    artifact = ThreeDayK4ModelArtifact.from_fit(
        scaled,
        **{key: value for key, value in _artifact().__dict__.items() if key not in {"fit", "artifact_hash"}},
    )
    expected = tuple(
        component_fingerprint(
            model_type="gmm",
            feature_schema_version=scaled.schema_version,
            feature_names=scaled.feature_names,
            mean=tuple(mean[i] * scaled.scales[i] + scaled.medians[i] for i in range(4)),
            covariance=tuple(covariance[i] * scaled.scales[i] ** 2 for i in range(4)),
            weight=scaled.weights[index],
        )
        for index, (mean, covariance) in enumerate(zip(scaled.means, scaled.covariances))
    )
    assert tuple(artifact.numeric_index_to_fingerprint.values()) == expected
    assert artifact.canonical_fingerprint_order == tuple(sorted(expected))
    assert expected != scaled.fingerprints
    assert ThreeDayK4ModelArtifact.from_json(artifact.to_json()).assign(_vector()).fingerprint in expected


@pytest.mark.parametrize("mode", ("precision_collapse", "overflow"))
def test_artifact_rejects_ambiguous_or_nonfinite_original_space_component_profiles(mode: str) -> None:
    fit = _fit()
    if mode == "precision_collapse":
        records = sorted(
            (
                component_fingerprint(
                    model_type="gmm", feature_schema_version=fit.schema_version,
                    feature_names=fit.feature_names, mean=mean,
                    covariance=fit.covariances[index], weight=0.25,
                ),
                mean,
                fit.covariances[index],
            )
            for index, mean in enumerate(fit.means)
        )
        changed = replace(
            fit,
            medians=(1e308,) * 4,
            fingerprints=tuple(row[0] for row in records),
            means=tuple(row[1] for row in records),
            covariances=tuple(row[2] for row in records),
            weights=(0.25,) * 4,
        )
    else:
        changed = replace(fit, scales=(1e308,) * 4)
    base = _artifact()
    kwargs = {key: value for key, value in base.__dict__.items() if key not in {"fit", "artifact_hash"}}
    with pytest.raises(ValueError, match="original-space|ambiguous|nonfinite|unique"):
        ThreeDayK4ModelArtifact.from_fit(changed, **kwargs)


@pytest.mark.parametrize("field", ("profile_id", "feature_schema_version", "training_start_at", "feature_history_hash"))
def test_artifact_rejects_bound_contract_drift(field: str) -> None:
    payload = json.loads(_artifact().to_json())
    payload[field] = "forged"
    with pytest.raises(ValueError, match=field.replace("_", " ") + "|incompatible|hash|training"):
        ThreeDayK4ModelArtifact.from_json(json.dumps(payload))


def test_artifact_json_fails_closed_for_duplicate_missing_extra_and_unknown_fields() -> None:
    encoded = _artifact().to_json()
    with pytest.raises(ValueError, match="duplicate JSON key"):
        ThreeDayK4ModelArtifact.from_json(encoded[:-1] + ',"symbol":"BTCUSDT"}')

    for mutation in ("missing", "extra"):
        payload = json.loads(encoded)
        if mutation == "missing":
            payload.pop("symbol")
        else:
            payload["strategy_outcomes"] = []
        with pytest.raises(ValueError, match="fields"):
            ThreeDayK4ModelArtifact.from_json(json.dumps(payload))


@pytest.mark.parametrize("mutation", ("pretty", "reordered", "newline"))
def test_artifact_json_requires_exact_canonical_bytes(mutation: str) -> None:
    payload = json.loads(_artifact().to_json())
    if mutation == "pretty":
        encoded = json.dumps(payload, indent=2, sort_keys=True)
    elif mutation == "reordered":
        encoded = json.dumps(dict(reversed(tuple(payload.items()))), separators=(",", ":"), sort_keys=False)
    else:
        encoded = _artifact().to_json() + "\n"
    with pytest.raises(ValueError, match="canonical"):
        ThreeDayK4ModelArtifact.from_json(encoded)


def test_artifact_rejects_component_and_numeric_parameter_corruption() -> None:
    for mutate in (
        lambda payload: payload["component_fingerprints"].__setitem__(0, "f" * 24),
        lambda payload: payload["weights"].__setitem__(0, -0.1),
        lambda payload: payload["covariances"][0].__setitem__(0, 0.0),
    ):
        payload = json.loads(_artifact().to_json())
        payload.pop("artifact_hash")
        mutate(payload)
        with pytest.raises(ValueError):
            ThreeDayK4ModelArtifact.from_json(json.dumps(payload))


@pytest.mark.parametrize("mode", ("duplicate", "omitted", "extra", "reordered"))
def test_artifact_constructor_rejects_nonexact_archive_provenance(mode: str) -> None:
    base = _artifact()
    rows = list(base.source_provenance)
    if mode == "duplicate":
        rows.insert(1, rows[0])
    elif mode == "omitted":
        rows.pop(1)
    elif mode == "extra":
        rows.append(rows[-1])
    else:
        rows[0], rows[1] = rows[1], rows[0]
    kwargs = {key: value for key, value in base.__dict__.items() if key not in {"fit", "artifact_hash", "source_provenance"}}
    with pytest.raises(ValueError, match="provenance"):
        ThreeDayK4ModelArtifact.from_fit(base.fit, source_provenance=tuple(rows), **kwargs)


def test_model_gates_are_immutable_exact_and_fail_closed_for_missing_or_extra_fields() -> None:
    base = _artifact()
    with pytest.raises(TypeError):
        base.model_gates["passed"] = False
    for mode in ("missing", "extra"):
        gates = dict(base.model_gates)
        if mode == "missing":
            gates.pop("finite_scaler")
        else:
            gates["unapproved_gate"] = True
        kwargs = {key: value for key, value in base.__dict__.items() if key not in {"fit", "artifact_hash", "model_gates"}}
        with pytest.raises(ValueError, match="gate fields"):
            ThreeDayK4ModelArtifact.from_fit(base.fit, model_gates=gates, **kwargs)
