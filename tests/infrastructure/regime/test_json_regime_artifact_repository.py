from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os

import pytest

from src.domain.regime.chart_features import CHART_FEATURE_SCHEMA_VERSION
from src.domain.regime.mapping import (
    MAPPING_METRIC_NAMES,
    STRATEGY_MAPPING_ARTIFACT_VERSION,
    BootstrapConfig,
    CandidateMappingAssessment,
    MappingThresholds,
    StrategyMappingArtifact,
    StrategyMappingEntry,
)
from src.domain.regime.model import (
    REGIME_MODEL_ARTIFACT_VERSION,
    RegimeModelArtifact,
    RegimeModelConfig,
    component_fingerprint,
)
from src.infrastructure.regime.json_regime_artifact_repository import (
    JsonRegimeArtifactRepository,
    model_artifact_hash,
    model_fingerprint_hash,
)


UTC = timezone.utc


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _model(covariance_type: str | None = None) -> RegimeModelArtifact:
    model_type = "kmeans" if covariance_type is None else "gmm"
    config = RegimeModelConfig(model_type, 3, covariance_type=covariance_type)
    names = ("return_4h", "rv_1d")
    raw = []
    for index in range(3):
        mean = (float(index), float(index + 1))
        if covariance_type is None:
            covariance = ()
            weight = None
        elif covariance_type == "diag":
            covariance = (0.25 + index, 0.5 + index)
            weight = (0.2, 0.3, 0.5)[index]
        else:
            covariance = (1.0, 0.0, 0.0, 1.0)
            weight = (0.2, 0.3, 0.5)[index]
        fingerprint = component_fingerprint(
            model_type=model_type,
            feature_schema_version=CHART_FEATURE_SCHEMA_VERSION,
            feature_names=names,
            mean=mean,
            covariance=covariance,
            weight=weight,
        )
        raw.append((fingerprint, mean, covariance, 1 / 3 if weight is None else weight))
    ordered = sorted(raw)
    return RegimeModelArtifact(
        artifact_version=REGIME_MODEL_ARTIFACT_VERSION,
        symbol="BTCUSDT",
        feature_schema_version=CHART_FEATURE_SCHEMA_VERSION,
        config=config,
        feature_names=names,
        lower_bounds=(-5.0, -4.0),
        upper_bounds=(5.0, 6.0),
        medians=(0.0, 1.0),
        scales=(1.5, 2.5),
        weights=tuple(row[3] for row in ordered),
        means=tuple(row[1] for row in ordered),
        covariances=() if covariance_type is None else tuple(row[2] for row in ordered),
        fingerprints=tuple(row[0] for row in ordered),
        training_start_at=datetime(2025, 1, 6, tzinfo=UTC),
        training_end_at=datetime(2025, 12, 29, tzinfo=UTC),
        distance_thresholds=(2.0, 2.5, 3.0) if covariance_type is None else (),
    )


def _metrics(mean: Decimal = Decimal("0"), *, infinity: bool = False) -> dict[str, Decimal]:
    values = {name: Decimal("0") for name in MAPPING_METRIC_NAMES}
    values["mean_weekly_return"] = mean
    values["median_weekly_return"] = mean
    values["profit_factor"] = Decimal("Infinity") if infinity else Decimal("0")
    return values


def _mapping(model: RegimeModelArtifact) -> StrategyMappingArtifact:
    candidate_hashes = {"alpha": _sha("alpha"), "beta": _sha("beta")}
    universe_hash = _canonical_hash({"candidate_ids": tuple(sorted(candidate_hashes))})
    definition_hash = _canonical_hash({"candidate_hashes": dict(sorted(candidate_hashes.items()))})
    starts = tuple(datetime(2026, 1, 5, tzinfo=UTC) + timedelta(days=7 * i) for i in range(8))
    zero_reasons = (
        "minimum_weekly_episodes",
        "minimum_distinct_months",
        "minimum_trade_count",
        "insufficient_consecutive_blocks",
        "non_positive_corrected_lower_bound",
        "cash_dominance",
    )
    entries: dict[str, StrategyMappingEntry] = {}
    assessments: dict[str, dict[str, CandidateMappingAssessment]] = {}
    for cluster_index, cluster in enumerate(model.fingerprints):
        cluster_assessments: dict[str, CandidateMappingAssessment] = {}
        for candidate_id, candidate_hash in candidate_hashes.items():
            eligible = cluster_index == 0 and candidate_id == "alpha"
            cluster_assessments[candidate_id] = CandidateMappingAssessment(
                cluster_fingerprint=cluster,
                candidate_id=candidate_id,
                candidate_hash=candidate_hash,
                weekly_episode_count=8 if eligible else 0,
                distinct_month_count=3 if eligible else 0,
                closed_trade_count=32 if eligible else 0,
                effective_episode_starts=starts if eligible else (),
                observed_mean=Decimal("0.02") if eligible else Decimal("0"),
                corrected_lower_bound=Decimal("0.01") if eligible else Decimal("0"),
                has_sufficient_consecutive_blocks=eligible,
                eligible=eligible,
                metrics=_metrics(Decimal("0.02"), infinity=True) if eligible else _metrics(),
                rejection_reasons=() if eligible else zero_reasons,
            )
        assessments[cluster] = cluster_assessments
        if cluster_index == 0:
            winner = cluster_assessments["alpha"]
            entries[cluster] = StrategyMappingEntry(
                cluster_fingerprint=cluster,
                strategy_profile_id="alpha",
                decision="strategy",
                weekly_episode_count=winner.weekly_episode_count,
                distinct_month_count=winner.distinct_month_count,
                closed_trade_count=winner.closed_trade_count,
                corrected_lower_bound=winner.corrected_lower_bound,
                metrics=winner.metrics,
            )
        else:
            entries[cluster] = StrategyMappingEntry(
                cluster_fingerprint=cluster,
                strategy_profile_id=None,
                decision="cash",
                weekly_episode_count=0,
                distinct_month_count=0,
                closed_trade_count=0,
                corrected_lower_bound=Decimal("0"),
                metrics=_metrics(),
                rejection_reasons=zero_reasons,
            )
    return StrategyMappingArtifact(
        artifact_version=STRATEGY_MAPPING_ARTIFACT_VERSION,
        regime_model_artifact_hash=model_artifact_hash(model),
        regime_model_fingerprint_hash=model_fingerprint_hash(model),
        candidate_definition_hash=definition_hash,
        candidate_universe_hash=universe_hash,
        candidate_hashes=candidate_hashes,
        data_provenance_hash=_sha("btc-ohlcv"),
        common_initial_equity=Decimal("10000.00"),
        cluster_fingerprints=model.fingerprints,
        entries=entries,
        candidate_assessments=assessments,
        thresholds=MappingThresholds(),
        bootstrap=BootstrapConfig(resamples=123),
    )


@pytest.mark.parametrize("covariance_type", [None, "diag", "tied"])
def test_model_round_trip_is_canonical_and_deterministic(tmp_path, covariance_type) -> None:
    model = _model(covariance_type)
    repo = JsonRegimeArtifactRepository(tmp_path)
    repo.save_model(model)
    first = (tmp_path / "model.json").read_bytes()
    repo.save_model(model)

    assert (tmp_path / "model.json").read_bytes() == first
    assert first.endswith(b"\n")
    assert repo.load_model(
        expected_symbol="BTCUSDT",
        expected_schema=CHART_FEATURE_SCHEMA_VERSION,
        expected_artifact_hash=model_artifact_hash(model),
        expected_fingerprint_hash=model_fingerprint_hash(model),
    ) == model


def test_mapping_round_trip_preserves_strategy_cash_zero_evidence_and_infinity(tmp_path) -> None:
    model = _model()
    mapping = _mapping(model)
    repo = JsonRegimeArtifactRepository(tmp_path)
    repo.save_model(model)
    repo.save_mapping(mapping)
    first = (tmp_path / "mapping.json").read_bytes()
    repo.save_mapping(mapping)

    assert (tmp_path / "mapping.json").read_bytes() == first
    loaded = repo.load_mapping(
        expected_candidate_definition_hash=mapping.candidate_definition_hash,
        expected_candidate_universe_hash=mapping.candidate_universe_hash,
        expected_data_provenance_hash=mapping.data_provenance_hash,
        expected_model_artifact_hash=mapping.regime_model_artifact_hash,
        expected_model_fingerprint_hash=mapping.regime_model_fingerprint_hash,
    )
    assert loaded == mapping
    assert loaded.common_initial_equity == Decimal("10000.00")
    assert loaded.entries[model.fingerprints[1]].decision == "cash"
    assert loaded.candidate_assessments[model.fingerprints[1]]["alpha"].effective_episode_starts == ()
    assert loaded.candidate_assessments[model.fingerprints[0]]["alpha"].metrics["profit_factor"] == Decimal("Infinity")


def test_load_rejects_compatibility_mismatches_with_clear_messages(tmp_path) -> None:
    model = _model()
    mapping = _mapping(model)
    repo = JsonRegimeArtifactRepository(tmp_path)
    repo.save_model(model)
    repo.save_mapping(mapping)
    checks = (
        ({"expected_candidate_definition_hash": "wrong"}, "candidate definition hash"),
        ({"expected_candidate_universe_hash": "wrong"}, "candidate universe hash"),
        ({"expected_data_provenance_hash": "wrong"}, "data provenance hash"),
        ({"expected_model_artifact_hash": "wrong"}, "model artifact hash"),
        ({"expected_model_fingerprint_hash": "wrong"}, "model fingerprint hash"),
    )
    for kwargs, message in checks:
        with pytest.raises(ValueError, match=message):
            repo.load_mapping(**kwargs)
    with pytest.raises(ValueError, match="symbol"):
        repo.load_model(expected_symbol="ETHUSDT", expected_schema=CHART_FEATURE_SCHEMA_VERSION)
    with pytest.raises(ValueError, match="schema"):
        repo.load_model(expected_symbol="BTCUSDT", expected_schema="old")


def test_tampering_duplicate_keys_constants_truncation_and_version_are_rejected(tmp_path) -> None:
    repo = JsonRegimeArtifactRepository(tmp_path)
    repo.save_model(_model())
    path = tmp_path / "model.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["symbol"] = "ETHUSDT"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact hash"):
        repo.load_model(expected_symbol="BTCUSDT", expected_schema=CHART_FEATURE_SCHEMA_VERSION)

    path.write_text('{"format":"x","format":"y"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        repo.load_model(expected_symbol="BTCUSDT", expected_schema=CHART_FEATURE_SCHEMA_VERSION)
    path.write_text('{"format":NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="constant"):
        repo.load_model(expected_symbol="BTCUSDT", expected_schema=CHART_FEATURE_SCHEMA_VERSION)
    path.write_text('{"format":', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        repo.load_model(expected_symbol="BTCUSDT", expected_schema=CHART_FEATURE_SCHEMA_VERSION)

    repo.save_model(_model())
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["version"] = 99
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        repo.load_model(expected_symbol="BTCUSDT", expected_schema=CHART_FEATURE_SCHEMA_VERSION)


def test_linked_model_is_required_and_incompatible_mapping_is_rejected(tmp_path) -> None:
    model = _model()
    mapping = _mapping(model)
    repo = JsonRegimeArtifactRepository(tmp_path)
    with pytest.raises(ValueError, match="standalone.*expected model"):
        repo.save_mapping(mapping)

    other = _model("diag")
    repo.save_model(other)
    with pytest.raises(ValueError, match="model artifact hash"):
        repo.save_mapping(mapping)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"expected_model_artifact_hash": "wrong"}, "model artifact hash"),
        ({"expected_model_fingerprint_hash": "wrong"}, "model fingerprint hash"),
    ],
)
def test_save_checks_explicit_model_expectations_before_replacing_mapping(
    tmp_path, kwargs, message
) -> None:
    model = _model()
    mapping = _mapping(model)
    repo = JsonRegimeArtifactRepository(tmp_path)
    repo.save_model(model)
    repo.save_mapping(mapping)
    before = (tmp_path / "mapping.json").read_bytes()

    with pytest.raises(ValueError, match=message):
        repo.save_mapping(mapping, **kwargs)

    assert (tmp_path / "mapping.json").read_bytes() == before


def test_load_rejects_mapping_clusters_not_present_in_linked_model(tmp_path) -> None:
    model = _model()
    mapping = _mapping(model)
    repo = JsonRegimeArtifactRepository(tmp_path)
    repo.save_model(model)
    repo.save_mapping(mapping)
    path = tmp_path / "mapping.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    renamed = {old: f"x-{old}" for old in payload["cluster_fingerprints"]}
    payload["cluster_fingerprints"] = [renamed[old] for old in payload["cluster_fingerprints"]]
    payload["entries"] = {
        renamed[old]: {**entry, "cluster_fingerprint": renamed[old]}
        for old, entry in payload["entries"].items()
    }
    payload["candidate_assessments"] = {
        renamed[old]: {
            candidate: {**assessment, "cluster_fingerprint": renamed[old]}
            for candidate, assessment in items.items()
        }
        for old, items in payload["candidate_assessments"].items()
    }
    envelope["artifact_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="cluster fingerprint"):
        repo.load_mapping()


def test_domain_validation_runs_after_validly_rehashed_forgery(tmp_path) -> None:
    model = _model("tied")
    repo = JsonRegimeArtifactRepository(tmp_path)
    repo.save_model(model)
    path = tmp_path / "model.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["covariances"][1][0] = 2.0
    envelope["artifact_hash"] = hashlib.sha256(
        json.dumps(envelope["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ValueError, match="shared covariance"):
        repo.load_model(expected_symbol="BTCUSDT", expected_schema=CHART_FEATURE_SCHEMA_VERSION)


def test_mapping_domain_validation_runs_after_validly_rehashed_forgery(tmp_path) -> None:
    model = _model()
    mapping = _mapping(model)
    repo = JsonRegimeArtifactRepository(tmp_path)
    repo.save_model(model)
    repo.save_mapping(mapping)
    path = tmp_path / "mapping.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    cluster = model.fingerprints[0]
    envelope["payload"]["candidate_assessments"][cluster]["alpha"]["eligible"] = False
    envelope["artifact_hash"] = hashlib.sha256(
        json.dumps(envelope["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="eligibility"):
        repo.load_mapping()


def test_atomic_replace_failure_keeps_previous_target_and_cleans_temp(tmp_path, monkeypatch) -> None:
    repo = JsonRegimeArtifactRepository(tmp_path)
    repo.save_model(_model())
    before = (tmp_path / "model.json").read_bytes()

    def fail_replace(source, target):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        repo.save_model(_model("diag"))
    assert (tmp_path / "model.json").read_bytes() == before
    assert list(tmp_path.glob(".model.json.*.tmp")) == []
