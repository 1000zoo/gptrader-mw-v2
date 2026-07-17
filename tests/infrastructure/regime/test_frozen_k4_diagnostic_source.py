from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import MappingProxyType
import urllib.request
import zipfile

import numpy as np
import pytest

from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.frozen_k4_failure_diagnostics import FrozenK4InputIdentity
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
)
from src.infrastructure.regime.frozen_k4_diagnostic_source import (
    FrozenK4DiagnosticSource,
    load_frozen_k4_diagnostic_source,
)


MODEL = Path("docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json")
RAW_ROOT = Path(".research-data/binance-usdm/raw/klines")


def _payload() -> dict[str, object]:
    return json.loads(MODEL.read_bytes())


def _write_payload(tmp_path: Path, payload: dict[str, object]) -> Path:
    payload = deepcopy(payload)
    payload.pop("attempt_hash", None)
    import hashlib

    encoded = json.dumps(
        payload, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode()
    payload["attempt_hash"] = hashlib.sha256(encoded).hexdigest()
    path = tmp_path / "attempt.json"
    path.write_text(
        json.dumps(payload, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return path


@pytest.fixture(scope="module")
def source() -> FrozenK4DiagnosticSource:
    return load_frozen_k4_diagnostic_source(MODEL, RAW_ROOT)


def test_loads_exact_frozen_primary_and_1641_float64_ordered_vectors(source) -> None:
    assert isinstance(source.primary_fit, ClusterDiagnosticFit)
    assert isinstance(source.identity, FrozenK4InputIdentity)
    assert len(source.vectors) == 1_641
    assert source.vectors[0].anchor_at.isoformat() == "2021-01-01T00:00:00+00:00"
    assert source.vectors[-1].anchor_at.isoformat() == "2025-06-29T00:00:00+00:00"
    assert all(
        (vector.anchor_at - vector.window_start_at).total_seconds() == 4_320 * 60
        for vector in source.vectors
    )
    registry_names = tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    assert source.primary_fit.feature_names == tuple(source.attempt_payload["feature_names"])
    assert tuple(source.vectors[0].values) == registry_names
    assert np.asarray(tuple(source.vectors[0].values.values())).dtype == np.float64


def test_owns_a_detached_deeply_immutable_attempt_payload(source) -> None:
    assert isinstance(source.attempt_payload, MappingProxyType)
    assert isinstance(source.attempt_payload["model_parameters"], MappingProxyType)
    disk_payload = _payload()
    disk_payload["model_parameters"]["weights"][0] = 0
    assert source.attempt_payload["model_parameters"]["weights"][0] != 0
    with pytest.raises(TypeError):
        source.attempt_payload["status"] = "changed"


def test_missing_local_archive_never_fetches(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("network"))
    with pytest.raises(FileNotFoundError):
        load_frozen_k4_diagnostic_source(MODEL, tmp_path)


@pytest.mark.parametrize("mode", ("mutated", "extra_member", "path_traversal"))
def test_rejects_archive_content_or_member_set(tmp_path: Path, mode: str) -> None:
    row = _payload()["source_provenance"][0]
    source_archive = RAW_ROOT / "BTCUSDT" / Path(row["url"]).name
    destination = tmp_path / "BTCUSDT" / source_archive.name
    destination.parent.mkdir()
    shutil.copyfile(source_archive, destination)
    if mode == "mutated":
        raw = bytearray(destination.read_bytes())
        raw[-1] ^= 1
        destination.write_bytes(raw)
    else:
        with zipfile.ZipFile(destination, "a") as archive:
            archive.writestr("extra.csv" if mode == "extra_member" else "../escape.csv", "x")
    with pytest.raises(ValueError, match="sha256|bytes|member|ZIP|archive"):
        load_frozen_k4_diagnostic_source(MODEL, tmp_path)


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda p: p["source_provenance"][0].__setitem__("url", "https://example/BAD.zip"), "basename|provenance"),
        (lambda p: p.__setitem__("last_usable_anchor_at", "2025-06-30T00:00:00+00:00"), "anchor"),
        (lambda p: p.__setitem__("Mapping", {}), "Mapping"),
        (lambda p: p.__setitem__("Validation", {}), "Validation"),
        (lambda p: p.__setitem__("Evidence", {}), "Evidence"),
        (lambda p: p.__setitem__("candidate", {}), "candidate"),
        (lambda p: p.__setitem__("Test", {}), "Test"),
    ],
)
def test_rejects_non_cluster_development_or_changed_provenance(
    tmp_path: Path, mutation, message: str
) -> None:
    payload = _payload()
    mutation(payload)
    path = _write_payload(tmp_path, payload)
    with pytest.raises(ValueError, match=message):
        load_frozen_k4_diagnostic_source(path, tmp_path / "raw")
