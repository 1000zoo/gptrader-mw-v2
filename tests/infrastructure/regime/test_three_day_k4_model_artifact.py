from datetime import datetime, timezone
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
    return ThreeDayK4ModelArtifact.from_fit(
        _fit(),
        training_start_at=datetime(2021, 1, 1, tzinfo=UTC),
        training_end_at=datetime(2025, 6, 30, tzinfo=UTC),
        first_usable_anchor_at=datetime(2021, 1, 1, tzinfo=UTC),
        last_usable_anchor_at=datetime(2025, 6, 29, tzinfo=UTC),
        usable_anchor_count=1641,
        source_provenance=(
            {
                "period": "2021-01",
                "url": "https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2021-01.zip",
                "member_identity": "BTCUSDT-1m-2021-01.zip",
                "bytes": 123,
                "sha256": "a" * 64,
            },
        ),
        feature_history_hash="b" * 64,
        fit_input_vector_hash="c" * 64,
        code_provenance_hash="d" * 64,
        stability_gates={
            "converged": True,
            "iterations": 7,
            "lower_bound": -1.25,
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
            "all_components_represented": True,
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
    assert actual.fingerprint == expected.fingerprint
    assert actual.dominant_probability == pytest.approx(expected.dominant_probability, abs=1e-15)
    assert actual.second_probability == pytest.approx(expected.second_probability, abs=1e-15)


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
