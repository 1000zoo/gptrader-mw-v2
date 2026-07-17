from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
from types import MappingProxyType
from types import SimpleNamespace
import zipfile

import numpy as np
import pytest

from src.domain.regime.cluster_diagnostic import ClusterDiagnosticFit
from src.domain.regime.three_day_chart_features import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
)
from src.application.services.three_day_chart_feature_extractor import extract_three_day_chart_feature_vector
from src.infrastructure.exchange.binance.research_data.three_day_feature_history import candles_from_kline_rows
from scripts.chart_regime_strategy_mapping import _three_day_vector_hash as publisher_vector_hash
from src.infrastructure.regime.frozen_k4_diagnostic_source import (
    _FrozenK4SourceProfile,
    _PRODUCTION_PROFILE,
    _PRODUCTION_ATTEMPT_HASH,
    _PRODUCTION_FILE_SHA256,
    _PRODUCTION_FILE_BYTES,
    _read_bounded_file,
    _resolve_contained_archive,
    _restore_primary_fit,
    _three_day_vector_hash,
    _validate_attempt,
    _load_frozen_k4_diagnostic_inputs,
    load_frozen_k4_diagnostic_source,
)
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import archive_url


MODEL = Path("docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json")


@dataclass(frozen=True)
class MiniFixture:
    model: Path
    raw_root: Path
    archive: Path
    profile: _FrozenK4SourceProfile


@pytest.fixture()
def mini(tmp_path: Path) -> MiniFixture:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    fit_start = start + timedelta(days=3)
    end = start + timedelta(days=4)
    profile = _FrozenK4SourceProfile.testing(
        raw_start_at=start,
        fit_start_at=fit_start,
        fit_end_at=end,
        expected_anchor_count=1,
    )
    url = archive_url("klines", "BTCUSDT", "2024-01", "monthly")
    archive_path = tmp_path / "raw" / "BTCUSDT" / Path(url).name
    archive_path.parent.mkdir(parents=True)
    rows = []
    for index in range(4 * 24 * 60):
        opened = start + timedelta(minutes=index)
        millis = int(opened.timestamp() * 1000)
        price = 40_000 + index / 100
        rows.append(
            f"{millis},{price},{price + 1},{price - 1},{price + .5},1,{millis + 59999},1,1,.5,.5,0"
        )
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTCUSDT-1m-2024-01.csv", "\n".join(rows) + "\n")
    raw = archive_path.read_bytes()
    payload = _payload()
    payload["fit_interval"] = {
        "start_at": fit_start.isoformat(), "end_at": end.isoformat()
    }
    payload["fit_input_anchor_count"] = 1
    payload["first_usable_anchor_at"] = fit_start.isoformat()
    payload["last_usable_anchor_at"] = fit_start.isoformat()
    payload["source_provenance"] = [{
        "period": "2024-01", "url": url,
        "member_identity": "BTCUSDT-1m-2024-01.csv", "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "expected_sha256": hashlib.sha256(raw).hexdigest(), "checksum_verified": True,
        "source": "klines", "symbol": "BTCUSDT", "timeframe": "1m",
        "granularity": "monthly", "requested_start_at": start.isoformat().replace("+00:00", "Z"),
        "requested_end_at": end.isoformat().replace("+00:00", "Z"),
    }]
    payload["source_provenance_hash"] = _hash(payload["source_provenance"])
    candles = candles_from_kline_rows(
        (row.split(",") for row in rows), symbol="BTCUSDT", start=start, end=end
    )
    vector = extract_three_day_chart_feature_vector(candles[:4320], fit_start)
    payload["fit_input_vector_hash"] = publisher_vector_hash((vector,))
    model = _write_payload(tmp_path, payload)
    return MiniFixture(model, tmp_path / "raw", archive_path, profile)


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


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def _thaw(value):
    if isinstance(value, MappingProxyType):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _rebind_archive(payload: dict[str, object], archive: Path) -> None:
    raw = archive.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    payload["source_provenance"][0]["bytes"] = len(raw)
    payload["source_provenance"][0]["sha256"] = digest
    payload["source_provenance"][0]["expected_sha256"] = digest
    payload["source_provenance_hash"] = _hash(payload["source_provenance"])


def _load_private(model: Path, raw_root: Path, profile: _FrozenK4SourceProfile):
    raw = model.read_bytes()
    payload = json.loads(raw)
    return _load_frozen_k4_diagnostic_inputs(
        model, raw_root, profile,
        trusted_file_sha256=hashlib.sha256(raw).hexdigest(),
        trusted_file_bytes=len(raw),
        trusted_attempt_hash=payload["attempt_hash"],
    )


def test_published_attempt_matches_exact_1641_anchor_production_profile() -> None:
    payload = _validate_attempt(_payload(), _PRODUCTION_PROFILE)
    fit = _restore_primary_fit(payload)
    assert payload["fit_input_anchor_count"] == 1_641
    assert payload["first_usable_anchor_at"] == "2021-01-01T00:00:00+00:00"
    assert payload["last_usable_anchor_at"] == "2025-06-29T00:00:00+00:00"
    assert isinstance(fit, ClusterDiagnosticFit)
    assert fit.feature_names == tuple(payload["feature_names"])


def test_public_loader_has_no_profile_bypass_and_always_selects_production(monkeypatch) -> None:
    import src.infrastructure.regime.frozen_k4_diagnostic_source as module

    assert tuple(inspect.signature(load_frozen_k4_diagnostic_source).parameters) == (
        "attempt_path", "raw_root"
    )
    selected = []
    def stop(_attempt, _root, profile, **trusted):
        selected.append((profile, trusted))
        raise RuntimeError("selected")
    monkeypatch.setattr(module, "_load_frozen_k4_diagnostic_inputs", stop)
    with pytest.raises(RuntimeError, match="selected"):
        load_frozen_k4_diagnostic_source(MODEL, Path("unused"))
    assert selected == [(_PRODUCTION_PROFILE, {
        "trusted_file_sha256": _PRODUCTION_FILE_SHA256,
        "trusted_file_bytes": _PRODUCTION_FILE_BYTES,
        "trusted_attempt_hash": _PRODUCTION_ATTEMPT_HASH,
    })]
    with pytest.raises(TypeError):
        load_frozen_k4_diagnostic_source(MODEL, Path("unused"), _source_profile=_PRODUCTION_PROFILE)


def test_public_boundary_pins_exact_published_attempt_and_raw_file(tmp_path: Path) -> None:
    assert _PRODUCTION_ATTEMPT_HASH == "83e25e21a2bccb5cf14572da000718deae7f3e068c45b2898a26e78cef67101f"
    assert _PRODUCTION_FILE_SHA256 == "e19ff1b2ec685f60b05d9aa98d088ea3883b62f0a394cf9fbdc2b84264ec23a5"
    assert _PRODUCTION_FILE_BYTES == 39_409
    payload = _payload()
    payload["model_gates"]["maximum_matched_centroid_distance"] = 3.0
    payload["model_gates"]["maximum_matched_centroid_distance_passed"] = False
    path = _write_payload(tmp_path, payload)
    with pytest.raises(ValueError, match="trusted|published|file SHA"):
        load_frozen_k4_diagnostic_source(path, tmp_path / "raw")


def test_actual_published_model_bytes_and_decoded_attempt_match_pins() -> None:
    raw = MODEL.read_bytes()
    assert len(raw) == _PRODUCTION_FILE_BYTES
    assert hashlib.sha256(raw).hexdigest() == _PRODUCTION_FILE_SHA256
    assert json.loads(raw)["attempt_hash"] == _PRODUCTION_ATTEMPT_HASH


@pytest.mark.parametrize("mode", ("oversized", "truncated"))
def test_bounded_reader_rejects_wrong_stat_size_before_bulk_read(tmp_path, monkeypatch, mode) -> None:
    path = tmp_path / "untrusted.bin"
    if mode == "oversized":
        with path.open("wb") as stream:
            stream.seek(10_000_000)
            stream.write(b"x")
        expected = 10
    else:
        path.write_bytes(b"tiny")
        expected = 100
    monkeypatch.setattr(os, "read", lambda *_a, **_k: pytest.fail("bulk read attempted"))
    with pytest.raises(ValueError, match="size|bytes"):
        _read_bounded_file(path, expected_bytes=expected)


def test_bounded_reader_rejects_fstat_identity_change(tmp_path, monkeypatch) -> None:
    path = tmp_path / "stable.bin"
    path.write_bytes(b"stable")
    actual_fstat = os.fstat
    calls = 0
    def changing_fstat(fd):
        nonlocal calls
        result = actual_fstat(fd)
        calls += 1
        if calls == 2:
            return SimpleNamespace(
                st_dev=result.st_dev, st_ino=result.st_ino, st_size=result.st_size,
                st_mtime_ns=result.st_mtime_ns + 1,
            )
        return result
    monkeypatch.setattr(os, "fstat", changing_fstat)
    with pytest.raises(ValueError, match="identity changed"):
        _read_bounded_file(path, expected_bytes=6)


def test_real_miniature_archive_loads_4320_window_in_float64_registry_order(mini) -> None:
    source = _load_private(mini.model, mini.raw_root, mini.profile)
    assert len(source.vectors) == 1
    assert (source.vectors[0].anchor_at - source.vectors[0].window_start_at) == timedelta(minutes=4320)
    assert tuple(source.vectors[0].values) == tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
    assert np.asarray(tuple(source.vectors[0].values.values())).dtype == np.float64
    assert _three_day_vector_hash(source.vectors) == source.attempt_payload["fit_input_vector_hash"]
    assert source.identity_hashes["feature_vectors_sha256"] == source.attempt_payload["fit_input_vector_hash"]
    assert _three_day_vector_hash(source.vectors) == publisher_vector_hash(source.vectors)


def test_dependency_metadata_is_complete_immutable_and_identity_bound(mini) -> None:
    source = _load_private(mini.model, mini.raw_root, mini.profile)
    metadata = source.dependency_metadata
    assert isinstance(metadata, MappingProxyType)
    assert set(metadata) == {"python", "packages", "numeric_libraries", "platform", "thread_environment"}
    assert set(metadata["python"]) == {"version", "implementation"}
    assert set(metadata["packages"]) == {"numpy", "scipy", "scikit-learn"}
    assert set(metadata["numeric_libraries"]) == {"blas", "lapack"}
    assert set(metadata["platform"]) == {"architecture", "machine", "processor"}
    assert set(metadata["thread_environment"]) == {
        "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"
    }
    assert all(value == "<absent>" or isinstance(value, str) for value in metadata["thread_environment"].values())
    assert source.identity_hashes["dependency_metadata_sha256"] == _hash(_thaw(metadata))
    with pytest.raises(TypeError):
        metadata["python"]["version"] = "changed"


def test_scaler_and_anchor_manifest_hash_semantics_are_exact(mini) -> None:
    source = _load_private(mini.model, mini.raw_root, mini.profile)
    fit = source.primary_fit
    expected_scaler = {
        "feature_names": list(fit.feature_names),
        "scaler": {"medians": list(fit.medians), "scales": list(fit.scales)},
        "clipping": {"lower_bounds": list(fit.lower_bounds), "upper_bounds": list(fit.upper_bounds)},
    }
    assert source.identity_hashes["scaler_sha256"] == _hash(expected_scaler)
    rows = []
    for vector in source.vectors:
        individual = _hash({
            "schema_version": vector.schema_version,
            "symbol": vector.symbol,
            "anchor_at": vector.anchor_at.isoformat(),
            "window_start_at": vector.window_start_at.isoformat(),
            "values": list(vector.values.items()),
        })
        rows.append({
            "anchor_at": vector.anchor_at.isoformat(),
            "window_start_at": vector.window_start_at.isoformat(),
            "vector_sha256": individual,
        })
    assert source.identity_hashes["source_anchor_manifest_sha256"] == _hash(rows)
    rows[0]["window_start_at"] = source.vectors[0].anchor_at.isoformat()
    assert source.identity_hashes["source_anchor_manifest_sha256"] != _hash(rows)
    rows[0]["window_start_at"] = source.vectors[0].window_start_at.isoformat()
    rows[0]["vector_sha256"] = "f" * 64
    assert source.identity_hashes["source_anchor_manifest_sha256"] != _hash(rows)


def test_rehashed_attempt_cannot_bypass_vector_binding(mini, tmp_path: Path) -> None:
    payload = json.loads(mini.model.read_bytes())
    payload["fit_input_vector_hash"] = "f" * 64
    model = _write_payload(tmp_path, payload)
    with pytest.raises(ValueError, match="vector hash"):
        _load_private(model, mini.raw_root, mini.profile)


@pytest.mark.parametrize("field", ("value", "timestamp", "order"))
def test_publisher_vector_hash_binds_values_timestamps_and_order(mini, field: str) -> None:
    source = _load_private(mini.model, mini.raw_root, mini.profile)
    vector = source.vectors[0]
    payload = {
        "symbol": vector.symbol,
        "anchor_at": vector.anchor_at.isoformat(),
        "window_start_at": vector.window_start_at.isoformat(),
        "values": list(vector.values.items()),
    }
    if field == "value":
        payload["values"][0] = (payload["values"][0][0], payload["values"][0][1] + 1)
    elif field == "timestamp":
        payload["anchor_at"] = (vector.anchor_at + timedelta(days=1)).isoformat()
    else:
        payload["values"][0], payload["values"][1] = payload["values"][1], payload["values"][0]
    assert _hash({
        "schema_version": vector.schema_version,
        "registry_names": [spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1],
        "vectors": [payload],
    }) != source.attempt_payload["fit_input_vector_hash"]


def test_owns_a_detached_deeply_immutable_attempt_payload(mini) -> None:
    source = _load_private(mini.model, mini.raw_root, mini.profile)
    assert isinstance(source.attempt_payload, MappingProxyType)
    assert isinstance(source.attempt_payload["model_parameters"], MappingProxyType)
    disk_payload = _payload()
    disk_payload["model_parameters"]["weights"][0] = 0
    assert source.attempt_payload["model_parameters"]["weights"][0] != 0
    with pytest.raises(TypeError):
        source.attempt_payload["status"] = "changed"


def test_missing_local_archive_never_fetches(monkeypatch, tmp_path: Path) -> None:
    import src.infrastructure.exchange.binance.research_data.historical_feature_loader as loader_module
    monkeypatch.setattr(loader_module, "urlopen", lambda *_a, **_k: pytest.fail("network"))
    with pytest.raises(FileNotFoundError):
        load_frozen_k4_diagnostic_source(MODEL, tmp_path)


def test_resolved_archive_escape_is_rejected_deterministically(tmp_path: Path) -> None:
    root = tmp_path / "raw"
    root.mkdir()
    with pytest.raises(ValueError, match="escape|root"):
        _resolve_contained_archive(root, root / ".." / "outside.zip")


def test_archive_file_identity_change_is_rejected_on_windows_without_symlink(mini, monkeypatch) -> None:
    import src.infrastructure.regime.frozen_k4_diagnostic_source as module
    actual_fstat = os.fstat
    calls = 0
    def changing_fstat(descriptor):
        nonlocal calls
        result = actual_fstat(descriptor)
        calls += 1
        if calls == 2:
            return SimpleNamespace(
                st_dev=result.st_dev, st_ino=result.st_ino, st_size=result.st_size,
                st_mtime_ns=result.st_mtime_ns + 1,
            )
        return result
    monkeypatch.setattr(os, "fstat", changing_fstat)
    row = json.loads(mini.model.read_bytes())["source_provenance"][0]
    with pytest.raises(ValueError, match="identity changed"):
        module._read_verified_archive(
            mini.archive, expected_bytes=row["bytes"], expected_sha256=row["sha256"]
        )


def test_archive_replacement_after_verified_read_does_not_change_consumed_snapshot(
    mini, monkeypatch,
) -> None:
    import src.infrastructure.regime.frozen_k4_diagnostic_source as module
    original = module._read_verified_archive
    def replace_after_read(path, **trusted):
        verified = original(path, **trusted)
        path.write_bytes(b"replacement-not-a-zip")
        return verified
    monkeypatch.setattr(module, "_read_verified_archive", replace_after_read)
    source = _load_private(mini.model, mini.raw_root, mini.profile)
    assert len(source.vectors) == 1
    assert source.identity_hashes["feature_vectors_sha256"] == source.attempt_payload["fit_input_vector_hash"]


def test_private_snapshots_unlink_after_rows_and_tempdir_cleans_on_success(mini, monkeypatch) -> None:
    import src.infrastructure.regime.frozen_k4_diagnostic_source as module
    actual_iter_rows = module._LocalProvenanceDownloader.iter_rows
    snapshots = []
    def tracked_rows(self, path):
        snapshots.append(Path(path))
        yield from actual_iter_rows(self, path)
        assert not Path(path).exists()
    monkeypatch.setattr(module._LocalProvenanceDownloader, "iter_rows", tracked_rows)
    source = _load_private(mini.model, mini.raw_root, mini.profile)
    assert len(source.vectors) == 1
    assert snapshots and all(not path.exists() for path in snapshots)


def test_private_snapshot_tempdir_cleans_on_vector_hash_error(mini, tmp_path, monkeypatch) -> None:
    import src.infrastructure.regime.frozen_k4_diagnostic_source as module
    actual_temporary_directory = module.tempfile.TemporaryDirectory
    directories = []
    def tracked_directory(*args, **kwargs):
        result = actual_temporary_directory(*args, **kwargs)
        directories.append(Path(result.name))
        return result
    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", tracked_directory)
    payload = json.loads(mini.model.read_bytes())
    payload["fit_input_vector_hash"] = "f" * 64
    model = _write_payload(tmp_path, payload)
    with pytest.raises(ValueError, match="vector hash"):
        _load_private(model, mini.raw_root, mini.profile)
    assert directories and all(not path.exists() for path in directories)


def test_miniature_archive_cannot_escape_raw_root_via_symlink(mini, tmp_path: Path) -> None:
    outside = tmp_path / "outside.zip"
    shutil.copyfile(mini.archive, outside)
    mini.archive.unlink()
    try:
        mini.archive.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"platform cannot create file symlink: {exc}")
    with pytest.raises(ValueError, match="root|escape|symlink"):
        _load_private(mini.model, mini.raw_root, mini.profile)


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda p: p["model_gates"].__setitem__("Evidence", {}), "model gates"),
        (lambda p: p["model_gates"].pop("passed"), "model gates"),
        (lambda p: p["model_gates"].__setitem__("component_count", "4"), "model gates"),
        (lambda p: p["model_gates"].__setitem__("iterations", p["model_gates"]["iterations"] + 1), "relationship"),
        (lambda p: p["model_parameters"]["weights"].__setitem__(0, "0.2"), "numeric|weights"),
        (lambda p: p["feature_names"].reverse(), "feature names"),
        (lambda p: p.__setitem__("failed_gate_names", ["maximum_low_confidence_rate"]), "failed gate"),
    ],
)
def test_rejects_adversarial_nested_attempt_schema(mini, tmp_path, mutation, message) -> None:
    payload = json.loads(mini.model.read_bytes())
    mutation(payload)
    model = _write_payload(tmp_path, payload)
    with pytest.raises(ValueError, match=message):
        _load_private(model, mini.raw_root, mini.profile)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda g: g.update(maximum_distance_exceedance_rate_threshold=1.0),
        lambda g: g.update(maximum_low_confidence_rate_threshold=0.01),
        lambda g: g.update(finite_model_parameters=False),
        lambda g: g.update(finite_scaler=False),
        lambda g: g.update(covariance_floor_threshold=1e-5),
        lambda g: g.update(feature_registry_version_expected="other"),
        lambda g: g.update(feature_registry_exact=False),
        lambda g: g.update(convergence_required=False),
        lambda g: g.update(weight_sum_expected=0.9),
        lambda g: g.update(weight_sum_tolerance=1e-4),
        lambda g: g.update(gmm_probability_threshold=0.5),
        lambda g: g.update(feature_family_cap_maximum_count=6),
        lambda g: g.update(distance_threshold=g["distance_threshold"] + 1.0),
        lambda g: g.update(nondegenerate_confidence=False),
    ],
)
def test_rejects_rehashed_contradictory_publisher_gate_groups(mini, tmp_path, mutation) -> None:
    payload = json.loads(mini.model.read_bytes())
    mutation(payload["model_gates"])
    # Keep the published failed-name list stale to prove gates are independently recomputed.
    model = _write_payload(tmp_path, payload)
    with pytest.raises(ValueError, match="gate|threshold|relationship|registry|finite"):
        _load_private(model, mini.raw_root, mini.profile)


@pytest.mark.parametrize("mode", ("mutated", "extra_member", "path_traversal"))
def test_rejects_archive_content_or_member_set(mini, tmp_path: Path, mode: str) -> None:
    destination = mini.archive
    if mode == "mutated":
        raw = bytearray(destination.read_bytes())
        raw[-1] ^= 1
        destination.write_bytes(raw)
    else:
        with zipfile.ZipFile(destination, "a") as archive:
            archive.writestr("extra.csv" if mode == "extra_member" else "../escape.csv", "x")
        payload = json.loads(mini.model.read_bytes())
        _rebind_archive(payload, destination)
        mini = MiniFixture(_write_payload(tmp_path, payload), mini.raw_root, destination, mini.profile)
    with pytest.raises(ValueError, match="sha256|bytes|member|ZIP|archive"):
        _load_private(mini.model, mini.raw_root, mini.profile)


def test_rejects_one_minute_continuity_gap_after_archive_receipt_is_rebound(mini, tmp_path) -> None:
    with zipfile.ZipFile(mini.archive) as archive:
        member = archive.namelist()[0]
        rows = archive.read(member).decode().splitlines()
    rows.pop(100)
    with zipfile.ZipFile(mini.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, "\n".join(rows) + "\n")
    payload = json.loads(mini.model.read_bytes())
    _rebind_archive(payload, mini.archive)
    model = _write_payload(tmp_path, payload)
    with pytest.raises(ValueError, match="continuity"):
        _load_private(model, mini.raw_root, mini.profile)


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
        _load_private(path, tmp_path / "raw", _PRODUCTION_PROFILE)
