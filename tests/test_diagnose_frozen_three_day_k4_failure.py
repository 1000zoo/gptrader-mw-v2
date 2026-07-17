from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from scripts.diagnose_frozen_three_day_k4_failure import (
    DEFAULT_RAW_KLINE_ROOT,
    EXPECTED_CENTROID_TEXT,
    EXPECTED_OOD_TEXT,
    MANIFEST,
    MISMATCH_FILES,
    SUCCESS_FILES,
    PublicationError,
    _directory_bytes,
    _parse_args,
    _publish_atomically,
    _reject_public_expected_override,
    publish_frozen_k4_failure_diagnosis,
)
from src.application.services.frozen_k4_failure_decomposition import (
    CauseClassification,
    ClusterSummaryRow,
    ComponentDistanceRow,
    FeatureContributionRow,
    LocationDistanceRow,
    OODComponentRow,
    OODSampleContributionRow,
    OffsetSubsampleRow,
)
from src.domain.regime.frozen_k4_failure_diagnostics import (
    DiagnosisStatus,
    MetricReproduction,
    SensitivityRow,
)


@dataclass(frozen=True)
class _Identity:
    source: str = "unit"
    split_at: str = "2023-04-01T00:00:00Z"


def _source() -> SimpleNamespace:
    return SimpleNamespace(
        identity=_Identity(),
        dependency_metadata={"runtime": "unit"},
        primary_fit=SimpleNamespace(),
        vectors=(),
    )


def _success_replay() -> SimpleNamespace:
    return SimpleNamespace(
        status=DiagnosisStatus.reproduced(
            MetricReproduction.compare(2.3526219570607076, 2.3526219570607076),
            MetricReproduction.compare(0.04631322364411944, 0.04631322364411944),
            76,
            1641,
        ),
        dependency_metadata={"runtime": "unit"},
        metric_ieee_float_bits={"centroid": ("4002d22b75eb6b05", "4002d22b75eb6b05")},
        half_replays=(),
    )


def _mismatch_replay() -> SimpleNamespace:
    return SimpleNamespace(
        status=DiagnosisStatus.causal_mismatch_unavailable(
            "input-data-mismatch",
            "a" * 64,
        ),
        dependency_metadata={"runtime": "unit"},
        metric_ieee_float_bits={},
        half_replays=(),
    )


def _decomposition() -> SimpleNamespace:
    return SimpleNamespace(
        cluster_summaries=(
            ClusterSummaryRow(
                "A",
                0,
                2,
                "a" * 24,
                "b" * 24,
                100,
                7,
                2.3526219570607076,
                ("volatility", "trend"),
            ),
        ),
        feature_contributions=(
            FeatureContributionRow("A", 0, 2, "volatility", 4.0, 0.8),
            FeatureContributionRow("A", 0, 2, "trend", 1.0, 0.2),
        ),
        component_distances=(
            ComponentDistanceRow("A", 0, 2, "euclidean", 2.3526219570607076),
            ComponentDistanceRow("A", 0, 2, "symmetric_kl", 3.5),
        ),
        location_distances=(
            LocationDistanceRow("A", 0, 2, "mean", 2.3),
            LocationDistanceRow("A", 0, 2, "coordinate_median", 2.1),
            LocationDistanceRow("A", 0, 2, "medoid", 2.0),
        ),
        exclusion_sensitivity=(
            SensitivityRow("A", "a" * 24, "exclude_farthest_1", 1, 1.8),
        ),
        ood_by_component=(
            OODComponentRow(0, "a" * 24, 100, 7, 0.07),
        ),
        ood_samples=(
            OODSampleContributionRow(
                "2021-01-01T00:00:00Z",
                0,
                "a" * 24,
                12.5,
                9.0,
                MappingProxyType({"volatility": 9.0, "trend": 3.5}),
            ),
        ),
        cause_classification=CauseClassification(
            ("specific-feature-drift", "component-ood-concentration"),
            {"largest_ood_rate": 0.07},
        ),
        offset_subsamples=(
            OffsetSubsampleRow(3, 0, 10, MappingProxyType({0: 5, 1: 5})),
            OffsetSubsampleRow(7, 0, 4, MappingProxyType({0: 2, 1: 2})),
        ),
    )


def _publish(tmp_path: Path, replay: SimpleNamespace) -> Path:
    return publish_frozen_k4_failure_diagnosis(
        model_attempt=tmp_path / "attempt.json",
        raw_kline_root=tmp_path / "raw",
        output_root=tmp_path / "out",
        source_loader=lambda _attempt, _raw: _source(),
        replay_runner=lambda _source_arg: replay,
        decomposition_runner=lambda _replay, _fit, _vectors: _decomposition(),
    )


def test_success_publication_writes_deterministic_artifacts_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")

    first = _publish(tmp_path, _success_replay())
    second = _publish(tmp_path, _success_replay())

    assert first == second
    assert sorted(path.name for path in first.iterdir()) == sorted((*SUCCESS_FILES, MANIFEST))
    assert _directory_bytes(first) == _directory_bytes(second)

    manifest = json.loads((first / MANIFEST).read_text(encoding="utf-8"))
    assert manifest["run_id"] == first.name
    assert sorted(manifest["file_sha256"]) == sorted(SUCCESS_FILES)

    reproduction = json.loads(
        (first / "frozen_k4_failure_reproduction.json").read_text(encoding="utf-8")
    )
    assert reproduction["single_thread_environment"] == {
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
    }
    assert reproduction["diagnostic_only"] is True

    cluster_header = (first / "frozen_k4_cluster_diagnostics.csv").read_text(
        encoding="utf-8"
    ).splitlines()[0]
    assert cluster_header == (
        "half_label,primary_component_index,half_component_index,"
        "primary_component_fingerprint,half_component_fingerprint,sample_count,"
        "exceedance_count,euclidean_distance,top_drift_features,diagnostic_only"
    )
    feature_lines = (first / "frozen_k4_feature_contributions.csv").read_text(
        encoding="utf-8"
    ).splitlines()
    assert feature_lines[1].startswith("A,0,2,volatility,4")

    markdown = (first / "frozen_k4_failure_diagnosis.md").read_text(encoding="utf-8")
    for question in (
        "1. Were the two frozen failure values reproduced?",
        "2. Which matched cluster pair produced 2.3526?",
        "3. Which features contributed most of the distance?",
        "4. Does the shift persist beyond the mean?",
        "5. How much does distance fall after removing tail samples?",
        "6. Which clusters and features dominate the 4.631% OOD rate?",
        "7. Do centroid drift and OOD failure hit the same cluster/features?",
        "8. Do covariance-aware component distances show the same anomaly?",
        "9. Does the conclusion hold for 3-day and 7-day subsamples?",
        "10. How is the failure cause classified?",
    ):
        assert f"## {question}" in markdown


def test_mismatch_publication_writes_only_terminal_artifacts(tmp_path: Path) -> None:
    final_dir = _publish(tmp_path, _mismatch_replay())

    assert sorted(path.name for path in final_dir.iterdir()) == sorted(
        (*MISMATCH_FILES, MANIFEST)
    )
    manifest = json.loads((final_dir / MANIFEST).read_text(encoding="utf-8"))
    assert sorted(manifest["file_sha256"]) == sorted(MISMATCH_FILES)


def test_public_cli_rejects_expected_metric_overrides() -> None:
    args = _parse_args([])
    assert DEFAULT_RAW_KLINE_ROOT.as_posix().endswith(
        ".research-data/binance-usdm/raw/klines"
    )
    _reject_public_expected_override(args.expected_centroid_distance, EXPECTED_CENTROID_TEXT)
    _reject_public_expected_override(args.expected_ood_rate, EXPECTED_OOD_TEXT)

    with pytest.raises(SystemExit, match="cannot redefine"):
        _reject_public_expected_override("2.0", EXPECTED_CENTROID_TEXT)


def test_atomic_publish_leaves_no_final_directory_on_rename_failure(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    final_dir = output_root / ("a" * 64)

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("rename failed")

    with pytest.raises(OSError, match="rename failed"):
        _publish_atomically(output_root, final_dir, {"a.txt": b"a"}, fail_replace)

    assert not final_dir.exists()
    assert not list(output_root.glob(".*.tmp-*"))


def test_existing_directory_must_be_byte_identical(tmp_path: Path) -> None:
    output_root = tmp_path / "out"
    final_dir = output_root / ("b" * 64)
    final_dir.mkdir(parents=True)
    (final_dir / "a.txt").write_bytes(b"a")

    _publish_atomically(output_root, final_dir, {"a.txt": b"a"}, lambda s, t: None)

    with pytest.raises(PublicationError, match="differs"):
        _publish_atomically(output_root, final_dir, {"a.txt": b"changed"}, lambda s, t: None)


def test_publication_preserves_failed_model_registry_bytes_and_avoids_forbidden_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = tmp_path / "failed-model-registry.json"
    registry.write_bytes(b'{"registry":"must remain byte-identical"}\n')
    before = registry.read_bytes()
    before_hash = hashlib.sha256(before).hexdigest()
    forbidden_roots = tuple(
        tmp_path / name
        for name in ("Mapping", "Validation", "Evidence", "candidate", "Test")
    )
    for root in forbidden_roots:
        root.mkdir()
        (root / "sentinel.txt").write_text("must not be read", encoding="utf-8")

    original_open = Path.open
    original_read_bytes = Path.read_bytes

    def is_forbidden(path: Path) -> bool:
        resolved = path.resolve()
        return any(
            resolved == root.resolve() or root.resolve() in resolved.parents
            for root in forbidden_roots
        )

    def guarded_open(self: Path, *args, **kwargs):
        if is_forbidden(self):
            raise AssertionError(f"forbidden diagnostic path was opened: {self}")
        return original_open(self, *args, **kwargs)

    def guarded_read_bytes(self: Path) -> bytes:
        if is_forbidden(self):
            raise AssertionError(f"forbidden diagnostic path was read: {self}")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    final_dir = publish_frozen_k4_failure_diagnosis(
        model_attempt=registry,
        raw_kline_root=tmp_path,
        output_root=tmp_path / "out",
        source_loader=lambda attempt, raw: _source(),
        replay_runner=lambda source: _success_replay(),
        decomposition_runner=lambda replay, fit, vectors: _decomposition(),
    )

    assert final_dir.is_dir()
    assert registry.read_bytes() == before
    assert hashlib.sha256(registry.read_bytes()).hexdigest() == before_hash


def test_publication_is_byte_identical_across_single_threaded_runs_with_same_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.setenv("MKL_NUM_THREADS", "1")
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "1")

    first = publish_frozen_k4_failure_diagnosis(
        model_attempt=tmp_path / "attempt.json",
        raw_kline_root=tmp_path / "raw",
        output_root=tmp_path / "out-a",
        source_loader=lambda attempt, raw: _source(),
        replay_runner=lambda source: _success_replay(),
        decomposition_runner=lambda replay, fit, vectors: _decomposition(),
    )
    second = publish_frozen_k4_failure_diagnosis(
        model_attempt=tmp_path / "attempt.json",
        raw_kline_root=tmp_path / "raw",
        output_root=tmp_path / "out-b",
        source_loader=lambda attempt, raw: _source(),
        replay_runner=lambda source: _success_replay(),
        decomposition_runner=lambda replay, fit, vectors: _decomposition(),
    )

    assert first.name == second.name
    assert _directory_bytes(first) == _directory_bytes(second)


def test_dependency_metadata_change_fails_closed_without_replacing_metric(
    tmp_path: Path,
) -> None:
    first_source = _source()
    second_source = SimpleNamespace(
        identity=first_source.identity,
        dependency_metadata={"runtime": "changed"},
        primary_fit=SimpleNamespace(),
        vectors=(),
    )

    first = publish_frozen_k4_failure_diagnosis(
        model_attempt=tmp_path / "attempt.json",
        raw_kline_root=tmp_path / "raw",
        output_root=tmp_path / "out",
        source_loader=lambda attempt, raw: first_source,
        replay_runner=lambda source: _success_replay(),
        decomposition_runner=lambda replay, fit, vectors: _decomposition(),
    )
    with pytest.raises(PublicationError, match="differs"):
        publish_frozen_k4_failure_diagnosis(
            model_attempt=tmp_path / "attempt.json",
            raw_kline_root=tmp_path / "raw",
            output_root=tmp_path / "out",
            source_loader=lambda attempt, raw: second_source,
            replay_runner=lambda source: SimpleNamespace(
                **{
                    **_success_replay().__dict__,
                    "dependency_metadata": second_source.dependency_metadata,
                }
            ),
            decomposition_runner=lambda replay, fit, vectors: _decomposition(),
        )

    first_reproduction = json.loads(
        (first / "frozen_k4_failure_reproduction.json").read_text(encoding="utf-8")
    )

    assert first_reproduction["dependency_metadata"] == {"runtime": "unit"}
