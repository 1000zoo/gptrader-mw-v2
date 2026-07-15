from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.model import RegimeModelArtifact
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
)
from src.infrastructure.regime.historical_replay_source import (
    HistoricalReplaySource,
    load_historical_replay_source,
)


REPORT = Path("docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json")
SOURCE_SHA256 = "2e656b11b89baf412d1f6af3217c8900165d45c14531c28f64795695baaa8f4c"
SELECTED = ("gmm-diag-k4", "gmm-diag-k8")


def _payload() -> dict[str, object]:
    return json.loads(REPORT.read_bytes())


def _candidate(payload: dict[str, object], identity: str) -> dict[str, object]:
    return next(
        candidate
        for candidate in payload["candidate_configs"]
        if candidate["identity"] == identity
    )


def _write_payload(tmp_path: Path, payload: dict[str, object]) -> tuple[Path, str]:
    raw = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    path = tmp_path / "source.json"
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_loads_only_fixed_k4_and_k8_diagnostic_fits() -> None:
    source = load_historical_replay_source(REPORT, expected_sha256=SOURCE_SHA256)

    assert isinstance(source, HistoricalReplaySource)
    assert source.report_sha256 == SOURCE_SHA256
    assert tuple(source.fits) == SELECTED
    assert source.training_start_at == datetime(2024, 7, 1, tzinfo=timezone.utc)
    assert source.training_end_at == datetime(2026, 7, 1, tzinfo=timezone.utc)
    assert source.registry == THREE_DAY_CHART_FEATURE_REGISTRY_V1
    assert all(isinstance(fit, ClusterDiagnosticFit) for fit in source.fits.values())
    assert all(not isinstance(fit, RegimeModelArtifact) for fit in source.fits.values())
    assert all(
        fit.config.model_type == "gmm" and fit.config.covariance_type == "diag"
        for fit in source.fits.values()
    )
    assert tuple(source.training_counts) == SELECTED
    assert sum(source.training_counts["gmm-diag-k4"].values()) == 727
    assert sum(source.training_counts["gmm-diag-k8"].values()) == 727
    assert tuple(source.training_counts["gmm-diag-k4"]) == source.fits[
        "gmm-diag-k4"
    ].fingerprints


def test_source_owns_deeply_immutable_copies() -> None:
    source = load_historical_replay_source(REPORT, expected_sha256=SOURCE_SHA256)

    assert isinstance(source.fits, MappingProxyType)
    assert isinstance(source.training_counts, MappingProxyType)
    assert all(isinstance(counts, MappingProxyType) for counts in source.training_counts.values())
    with pytest.raises(TypeError):
        source.fits["other"] = source.fits["gmm-diag-k4"]
    with pytest.raises(TypeError):
        source.training_counts["gmm-diag-k4"]["other"] = 1


def test_rejects_source_report_hash_mismatch(tmp_path: Path) -> None:
    raw = bytearray(REPORT.read_bytes())
    raw[-2] = ord(" ")
    path = tmp_path / "source.json"
    path.write_bytes(raw)

    with pytest.raises(ValueError, match="hash mismatch"):
        load_historical_replay_source(path, expected_sha256=SOURCE_SHA256)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda p: p.__setitem__("kind", "other"), "kind"),
        (lambda p: p.__setitem__("version", "other"), "version"),
        (lambda p: p.__setitem__("symbol", "ETHUSDT"), "symbol"),
        (
            lambda p: p["interval"].__setitem__("start_inclusive", "2024-07-02T00:00:00Z"),
            "interval",
        ),
        (
            lambda p: p["interval"].__setitem__("end_exclusive", "2026-06-30T00:00:00Z"),
            "interval",
        ),
        (lambda p: p.__setitem__("sample_count", 726), "sample count"),
        (lambda p: p.__setitem__("strategy_outcomes_read", True), "outcome flags"),
        (lambda p: p.__setitem__("strategy_outcomes_evaluated", True), "outcome flags"),
        (lambda p: p.__setitem__("production_model_selected", True), "outcome flags"),
        (lambda p: p.__setitem__("outcome_evaluation", "evaluated"), "outcome flags"),
        (lambda p: p.__setitem__("ranking_purpose", "production"), "outcome flags"),
        (
            lambda p: p["feature_schema"].__setitem__("version", "other"),
            "feature schema",
        ),
        (
            lambda p: p["feature_schema"]["registry"][0].__setitem__("formula", "tampered"),
            "registry",
        ),
        (
            lambda p: p["feature_schema"]["retained_by_candidate"]["gmm-diag-k4"].__setitem__(
                0, "return_7d"
            ),
            "retained feature names",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k4")["fit"]["retained_feature_names"].__setitem__(
                0, "return_7d"
            ),
            "retained feature names",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k4")["model"].__setitem__("cluster_count", 5),
            "identity",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k4")["model"].__setitem__(
                "random_seed", 20260715
            ),
            "model config",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k8")["model"].__setitem__(
                "regularization", 2e-6
            ),
            "model config",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k4")["fit"]["means"][0].__setitem__(
                0, _candidate(p, "gmm-diag-k4")["fit"]["means"][0][0] + 0.01
            ),
            "fingerprint",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k4")["fit"]["covariances"][0].__setitem__(
                0, _candidate(p, "gmm-diag-k4")["fit"]["covariances"][0][0] + 0.01
            ),
            "fingerprint",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k4")["fit"]["weights"].__setitem__(
                0, _candidate(p, "gmm-diag-k4")["fit"]["weights"][0] + 0.01
            ),
            "weights",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k4")["fit"]["fingerprints"].__setitem__(
                0, "0" * 24
            ),
            "fingerprint",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k4").__setitem__("status", "rejected"),
            "status",
        ),
        (
            lambda p: _candidate(p, "gmm-diag-k4").__setitem__("rejections", ["technical"]),
            "technical rejection",
        ),
    ],
    ids=[
        "kind",
        "version",
        "symbol",
        "interval-start",
        "interval-end",
        "sample-count",
        "outcomes-read",
        "outcomes-evaluated",
        "production-selected",
        "outcome-evaluation",
        "ranking-purpose",
        "schema-version",
        "registry-field",
        "schema-retained-name",
        "fit-retained-name",
        "config-identity",
        "config-random-seed",
        "config-regularization",
        "mean",
        "covariance",
        "weight",
        "fingerprint",
        "candidate-status",
        "technical-rejection",
    ],
)
def test_rejects_tampered_source_contract(
    tmp_path: Path, mutation, message: str
) -> None:
    payload = deepcopy(_payload())
    mutation(payload)
    path, digest = _write_payload(tmp_path, payload)

    with pytest.raises(ValueError, match=message):
        load_historical_replay_source(path, expected_sha256=digest)


@pytest.mark.parametrize("mode", ["missing", "duplicate"])
def test_requires_selected_candidates_exactly_once(tmp_path: Path, mode: str) -> None:
    payload = deepcopy(_payload())
    candidates = payload["candidate_configs"]
    selected = _candidate(payload, "gmm-diag-k4")
    if mode == "missing":
        candidates.remove(selected)
    else:
        candidates.append(deepcopy(selected))
    path, digest = _write_payload(tmp_path, payload)

    with pytest.raises(ValueError, match="candidate registry"):
        load_historical_replay_source(path, expected_sha256=digest)


def test_rejects_training_count_key_or_total_tampering(tmp_path: Path) -> None:
    payload = deepcopy(_payload())
    counts = _candidate(payload, "gmm-diag-k8")["metrics"]["counts"]
    fingerprint = next(iter(counts))
    counts[fingerprint] -= 1
    path, digest = _write_payload(tmp_path, payload)

    with pytest.raises(ValueError, match="training counts"):
        load_historical_replay_source(path, expected_sha256=digest)


@pytest.mark.parametrize(
    ("field", "value"),
    [("scale_invariant", 1), ("aggregation_minutes", 15.0)],
)
def test_rejects_registry_json_type_confusion(
    tmp_path: Path, field: str, value: object
) -> None:
    payload = deepcopy(_payload())
    payload["feature_schema"]["registry"][0][field] = value
    path, digest = _write_payload(tmp_path, payload)

    with pytest.raises(ValueError, match="registry"):
        load_historical_replay_source(path, expected_sha256=digest)
