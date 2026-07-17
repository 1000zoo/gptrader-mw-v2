from __future__ import annotations

from dataclasses import dataclass
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
    OODComponentRow,
    OODSampleContributionRow,
)
from src.domain.regime.frozen_k4_failure_diagnostics import (
    DiagnosisStatus,
    MetricReproduction,
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
