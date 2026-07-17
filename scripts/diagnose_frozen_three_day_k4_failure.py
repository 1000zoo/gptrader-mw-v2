"""Publish the frozen BTCUSDT three-day K4 failure diagnosis.

This script is a diagnostic-only renderer.  It replays the already frozen K4
failure and writes deterministic evidence files; it cannot redefine the frozen
expected failure metrics from the public CLI.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, is_dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import mkdtemp
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.application.services.frozen_k4_failure_decomposition import (  # noqa: E402
    decompose_frozen_k4_failure,
)
from src.application.services.frozen_k4_failure_replay import (  # noqa: E402
    EXPECTED_MAXIMUM_DISTANCE_EXCEEDANCE_RATE,
    EXPECTED_MAXIMUM_MATCHED_CENTROID_DISTANCE,
    replay_frozen_k4_failures,
)
from src.domain.regime.frozen_k4_failure_diagnostics import (  # noqa: E402
    FrozenK4DiagnosisManifest,
)
from src.infrastructure.regime.frozen_k4_diagnostic_source import (  # noqa: E402
    load_frozen_k4_diagnostic_source,
)


DEFAULT_MODEL_ATTEMPT = (
    REPO_ROOT
    / "docs"
    / "backtests"
    / "chart-regime-strategy-mapping-btcusdt-3d-k4-daily-model.json"
)
DEFAULT_RAW_KLINE_ROOT = (
    REPO_ROOT / ".research-data" / "binance-usdm" / "raw" / "klines"
)
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "docs" / "backtests" / "frozen_k4_failure_diagnosis"
SUCCESS_FILES = (
    "frozen_k4_failure_reproduction.json",
    "frozen_k4_cluster_diagnostics.csv",
    "frozen_k4_feature_contributions.csv",
    "frozen_k4_ood_samples.csv",
    "frozen_k4_distance_comparison.csv",
    "frozen_k4_failure_diagnosis.md",
)
MISMATCH_FILES = (
    "frozen_k4_failure_reproduction.json",
    "frozen_k4_failure_diagnosis.md",
)
MANIFEST = "manifest.json"
THREAD_ENV_KEYS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
EXPECTED_CENTROID_TEXT = "2.3526219570607076"
EXPECTED_OOD_TEXT = "0.04631322364411944"


class PublicationError(RuntimeError):
    """Raised when deterministic publication cannot be completed."""


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    _reject_public_expected_override(args.expected_centroid_distance, EXPECTED_CENTROID_TEXT)
    _reject_public_expected_override(args.expected_ood_rate, EXPECTED_OOD_TEXT)
    publish_frozen_k4_failure_diagnosis(
        model_attempt=args.model_attempt,
        raw_kline_root=args.raw_kline_root,
        output_root=args.output_root,
    )
    return 0


def publish_frozen_k4_failure_diagnosis(
    *,
    model_attempt: Path,
    raw_kline_root: Path,
    output_root: Path,
    source_loader: Callable[[Path, Path], object] = load_frozen_k4_diagnostic_source,
    replay_runner: Callable[[object], object] = replay_frozen_k4_failures,
    decomposition_runner: Callable[[object, object, tuple[object, ...]], object] = (
        decompose_frozen_k4_failure
    ),
    replace_directory: Callable[[Path, Path], None] = os.replace,
) -> Path:
    source = source_loader(Path(model_attempt), Path(raw_kline_root))
    replay = replay_runner(source)
    decomposition = None
    if replay.status.status == "reproduced":
        decomposition = decomposition_runner(
            replay,
            source.primary_fit,
            tuple(source.vectors),
        )
    artifacts = _render_artifacts(source, replay, decomposition)
    manifest_payload, run_id = _manifest_for_artifacts(source, replay, artifacts)
    artifacts[MANIFEST] = _canonical_json_bytes(manifest_payload)
    final_dir = Path(output_root) / run_id
    _publish_atomically(Path(output_root), final_dir, artifacts, replace_directory)
    return final_dir


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-attempt", type=Path, default=DEFAULT_MODEL_ATTEMPT)
    parser.add_argument("--raw-kline-root", type=Path, default=DEFAULT_RAW_KLINE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        "--expected-centroid-distance",
        default=EXPECTED_CENTROID_TEXT,
        help="Frozen expected value; public CLI cannot override it.",
    )
    parser.add_argument(
        "--expected-ood-rate",
        default=EXPECTED_OOD_TEXT,
        help="Frozen expected value; public CLI cannot override it.",
    )
    return parser.parse_args(argv)


def _reject_public_expected_override(value: object, expected_text: str) -> None:
    if str(value) != expected_text:
        raise SystemExit("public CLI cannot redefine frozen expected metric values")


def _render_artifacts(
    source: object,
    replay: object,
    decomposition: object | None,
) -> dict[str, bytes]:
    reproduction = _reproduction_payload(source, replay)
    artifacts = {
        "frozen_k4_failure_reproduction.json": _canonical_json_bytes(reproduction),
        "frozen_k4_failure_diagnosis.md": _markdown_bytes(replay, decomposition),
    }
    if replay.status.status == "reproduced":
        if decomposition is None:
            raise PublicationError("reproduced diagnosis requires decomposition")
        artifacts.update(
            {
                "frozen_k4_cluster_diagnostics.csv": _csv_bytes(
                    (
                        "half_label",
                        "primary_component_index",
                        "half_component_index",
                        "primary_component_fingerprint",
                        "half_component_fingerprint",
                        "sample_count",
                        "exceedance_count",
                        "euclidean_distance",
                        "top_drift_features",
                        "diagnostic_only",
                    ),
                    _cluster_rows(decomposition),
                ),
                "frozen_k4_feature_contributions.csv": _csv_bytes(
                    (
                        "half_label",
                        "primary_component_index",
                        "half_component_index",
                        "feature_name",
                        "squared_distance",
                        "contribution_ratio",
                    ),
                    _feature_rows(decomposition),
                ),
                "frozen_k4_ood_samples.csv": _csv_bytes(
                    (
                        "anchor_at",
                        "component_index",
                        "component_fingerprint",
                        "squared_mahalanobis",
                        "threshold",
                        "top_feature_contributions",
                    ),
                    _ood_rows(decomposition),
                ),
                "frozen_k4_distance_comparison.csv": _csv_bytes(
                    (
                        "half_label",
                        "primary_component_index",
                        "half_component_index",
                        "metric",
                        "distance",
                    ),
                    _distance_rows(decomposition),
                ),
            }
        )
    return dict(sorted(artifacts.items()))


def _reproduction_payload(source: object, replay: object) -> dict[str, object]:
    return {
        "schema_version": "frozen-k4-failure-reproduction-v1",
        "diagnostic_only": True,
        "primary_replacement_allowed": False,
        "input_identity": _payload(source.identity),
        "input_identity_sha256": _hash(_payload(source.identity)),
        "status": _payload(replay.status),
        "dependency_metadata": _payload(replay.dependency_metadata),
        "single_thread_environment": {
            key: os.environ.get(key) for key in THREAD_ENV_KEYS
        },
        "metric_ieee_float_bits": _payload(replay.metric_ieee_float_bits),
        "half_replays": [
            {
                "receipt": _payload(half.receipt),
                "matched_pairs": [_payload(pair) for pair in half.matched_pairs],
                "pair_euclidean_distances": list(half.pair_euclidean_distances),
                "component_weights": list(half.component_weights),
                "diagnostic_only": half.diagnostic_only,
                "primary_replacement_allowed": half.primary_replacement_allowed,
            }
            for half in replay.half_replays
        ],
        "ood_exceedance_count": replay.status.ood_exceedance_numerator,
        "ood_sample_count": replay.status.ood_denominator,
    }


def _manifest_for_artifacts(
    source: object,
    replay: object,
    artifacts: Mapping[str, bytes],
) -> tuple[dict[str, object], str]:
    input_identity_sha256 = _hash(_payload(source.identity))
    status = (
        "reproduced"
        if replay.status.status == "reproduced"
        else "reproduction_mismatch"
    )
    file_sha256 = {name: _sha256_bytes(data) for name, data in sorted(artifacts.items())}
    run_id = _hash(
        {
            "input_identity_sha256": input_identity_sha256,
            "status": _payload(replay.status),
        }
    )
    manifest = FrozenK4DiagnosisManifest(
        run_id=run_id,
        input_identity_sha256=input_identity_sha256,
        status=status,
        file_sha256=file_sha256,
    )
    return manifest.canonical_payload(), run_id



def _cluster_rows(decomposition: object) -> list[dict[str, object]]:
    return [
        {
            "half_label": row.half_label,
            "primary_component_index": row.primary_component_index,
            "half_component_index": row.half_component_index,
            "primary_component_fingerprint": row.primary_component_fingerprint,
            "half_component_fingerprint": row.half_component_fingerprint,
            "sample_count": row.sample_count,
            "exceedance_count": row.exceedance_count,
            "euclidean_distance": row.euclidean_distance,
            "top_drift_features": "|".join(row.top_drift_features),
            "diagnostic_only": row.diagnostic_only,
        }
        for row in sorted(
            decomposition.cluster_summaries,
            key=lambda item: (
                item.half_label,
                item.primary_component_index,
                item.half_component_index,
            ),
        )
    ]


def _feature_rows(decomposition: object) -> list[dict[str, object]]:
    return [
        _row_payload(row)
        for row in sorted(
            decomposition.feature_contributions,
            key=lambda item: (
                item.half_label,
                item.primary_component_index,
                item.half_component_index,
                -item.squared_distance,
                item.feature_name,
            ),
        )
    ]


def _ood_rows(decomposition: object) -> list[dict[str, object]]:
    return [
        {
            "anchor_at": row.anchor_at,
            "component_index": row.component_index,
            "component_fingerprint": row.component_fingerprint,
            "squared_mahalanobis": row.squared_mahalanobis,
            "threshold": row.threshold,
            "top_feature_contributions": _compact_mapping(row.feature_contributions),
        }
        for row in sorted(
            decomposition.ood_samples,
            key=lambda item: (item.anchor_at, item.component_index),
        )
    ]


def _distance_rows(decomposition: object) -> list[dict[str, object]]:
    return [
        _row_payload(row)
        for row in sorted(
            decomposition.component_distances,
            key=lambda item: (
                item.half_label,
                item.primary_component_index,
                item.half_component_index,
                item.metric,
            ),
        )
    ]


def _csv_bytes(headers: Sequence[str], rows: Iterable[Mapping[str, object]]) -> bytes:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(headers), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({header: _csv_value(row.get(header, "")) for header in headers})
    return buffer.getvalue().encode("utf-8")


def _csv_value(value: object) -> object:
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _compact_mapping(value: Mapping[str, float]) -> str:
    return "|".join(
        f"{key}={_float(float(item))}"
        for key, item in sorted(value.items(), key=lambda pair: (-float(pair[1]), pair[0]))[:5]
    )


def _row_payload(row: object) -> dict[str, object]:
    payload = _payload(row)
    if not isinstance(payload, dict):
        raise TypeError("row payload must be a mapping")
    return payload


def _payload(value: object) -> object:
    if hasattr(value, "canonical_payload"):
        return _payload(value.canonical_payload())
    if is_dataclass(value):
        return _payload(asdict(value))
    if isinstance(value, MappingProxyType):
        return _payload(dict(value))
    if isinstance(value, Mapping):
        return {str(key): _payload(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple):
        return [_payload(item) for item in value]
    if isinstance(value, list):
        return [_payload(item) for item in value]
    return value


def _float(value: float) -> str:
    return format(float(value), ".17g")


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            _payload(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _hash(value: object) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _publish_atomically(
    output_root: Path,
    final_dir: Path,
    artifacts: Mapping[str, bytes],
    replace_directory: Callable[[Path, Path], None],
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    expected_names = set(artifacts)
    if final_dir.exists():
        if _directory_bytes(final_dir) == dict(artifacts):
            return
        raise PublicationError(f"existing run directory differs: {final_dir}")
    temp_dir = Path(
        mkdtemp(prefix=f".{final_dir.name}.tmp-", dir=str(output_root))
    )
    try:
        for name in sorted(artifacts):
            path = temp_dir / name
            _write_fsynced(path, artifacts[name])
        if set(path.name for path in temp_dir.iterdir()) != expected_names:
            raise PublicationError("temporary artifact set does not match expected schema")
        _fsync_directory(temp_dir)
        replace_directory(temp_dir, final_dir)
        _fsync_directory(output_root)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if final_dir.exists() and _directory_bytes(final_dir) != dict(artifacts):
            raise PublicationError("partial final run directory detected")
        raise


def _write_fsynced(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _directory_bytes(path: Path) -> dict[str, bytes]:
    if not path.is_dir():
        return {}
    return {
        child.name: child.read_bytes()
        for child in sorted(path.iterdir(), key=lambda item: item.name)
        if child.is_file()
    }


def _markdown_bytes(replay: object, decomposition: object | None) -> bytes:
    status = replay.status.status
    top_pair = None
    if decomposition is not None and decomposition.cluster_summaries:
        top_pair = max(
            decomposition.cluster_summaries,
            key=lambda row: row.euclidean_distance,
        )
    answers = [
        ("1. Were the two frozen failure values reproduced?", _answer_reproduced(replay)),
        (
            "2. Which matched cluster pair produced 2.3526?",
            "Replay stopped before pair decomposition."
            if top_pair is None
            else (
                f"{top_pair.half_label} half, primary "
                f"{top_pair.primary_component_index} -> half "
                f"{top_pair.half_component_index}."
            ),
        ),
        (
            "3. Which features contributed most of the distance?",
            _top_features_answer(decomposition),
        ),
        (
            "4. Does the shift persist beyond the mean?",
            _location_answer(decomposition, top_pair),
        ),
        (
            "5. How much does distance fall after removing tail samples?",
            _tail_answer(decomposition, top_pair),
        ),
        (
            "6. Which clusters and features dominate the 4.631% OOD rate?",
            _ood_answer(decomposition),
        ),
        (
            "7. Do centroid drift and OOD failure hit the same cluster/features?",
            _centroid_ood_alignment_answer(decomposition, top_pair),
        ),
        (
            "8. Do covariance-aware component distances show the same anomaly?",
            _component_distance_answer(decomposition, top_pair),
        ),
        (
            "9. Does the conclusion hold for 3-day and 7-day subsamples?",
            _offset_answer(decomposition),
        ),
        ("10. How is the failure cause classified?", _cause_answer(decomposition)),
    ]
    lines = [
        "# Frozen K4 Failure Diagnosis",
        "",
        "This report is diagnostic-only and cannot replace the frozen primary model.",
        "",
        f"- Replay status: `{status}`",
        "",
    ]
    for question, answer in answers:
        lines.extend((f"## {question}", "", answer, ""))
    return ("\n".join(lines).rstrip() + "\n").encode("utf-8")


def _answer_reproduced(replay: object) -> str:
    if replay.status.status != "reproduced":
        return f"No. Replay stopped at `{replay.status.mismatch_classification}`."
    return "Yes. The centroid distance and OOD exceedance rate reproduced within tolerance."


def _top_features_answer(decomposition: object | None) -> str:
    if decomposition is None or not decomposition.feature_contributions:
        return "Replay failure prevented feature contribution decomposition."
    best_by_feature: dict[str, float] = {}
    for row in decomposition.feature_contributions:
        best_by_feature[row.feature_name] = max(
            best_by_feature.get(row.feature_name, 0.0),
            float(row.squared_distance),
        )
    rows = sorted(best_by_feature.items(), key=lambda item: (-item[1], item[0]))[:5]
    return ", ".join(f"{name}={_float(value)}" for name, value in rows)


def _location_answer(decomposition: object | None, top_pair: object | None) -> str:
    if decomposition is None or top_pair is None:
        return "Replay failure prevented robust location comparison."
    rows = [
        row for row in decomposition.location_distances
        if row.half_label == top_pair.half_label
        and row.primary_component_index == top_pair.primary_component_index
        and row.half_component_index == top_pair.half_component_index
    ]
    if not rows:
        return "No location rows were available for the largest drift pair."
    return "; ".join(
        f"{row.statistic}={_float(row.centroid_distance)}"
        for row in sorted(rows, key=lambda item: item.statistic)
    )


def _tail_answer(decomposition: object | None, top_pair: object | None) -> str:
    if decomposition is None or top_pair is None:
        return "Replay failure prevented tail sensitivity comparison."
    rows = [
        row for row in decomposition.exclusion_sensitivity
        if row.half_label == top_pair.half_label
        and row.component_fingerprint == top_pair.primary_component_fingerprint
    ]
    if not rows:
        return "No exclusion sensitivity rows were available for the largest drift pair."
    return "; ".join(
        f"{row.statistic}={_float(row.centroid_distance)}"
        for row in sorted(rows, key=lambda item: item.statistic)
    )


def _ood_answer(decomposition: object | None) -> str:
    if decomposition is None or not decomposition.ood_by_component:
        return "Replay failure prevented OOD component decomposition."
    row = max(decomposition.ood_by_component, key=lambda item: item.exceedance_count)
    return (
        f"component {row.component_index} has {row.exceedance_count}/"
        f"{row.sample_count} exceedances."
    )


def _centroid_ood_alignment_answer(
    decomposition: object | None, top_pair: object | None
) -> str:
    if decomposition is None or top_pair is None or not decomposition.ood_by_component:
        return "Replay failure prevented centroid/OOD alignment comparison."
    ood = max(decomposition.ood_by_component, key=lambda item: item.exceedance_count)
    same_cluster = int(ood.component_index) == int(top_pair.primary_component_index)
    return (
        f"largest centroid drift primary component={top_pair.primary_component_index}; "
        f"largest OOD component={ood.component_index}; same_cluster={str(same_cluster).lower()}."
    )


def _component_distance_answer(decomposition: object | None, top_pair: object | None) -> str:
    if decomposition is None or top_pair is None:
        return "Replay failure prevented covariance-aware distance comparison."
    rows = [
        row for row in decomposition.component_distances
        if row.half_label == top_pair.half_label
        and row.primary_component_index == top_pair.primary_component_index
        and row.half_component_index == top_pair.half_component_index
    ]
    if not rows:
        return "No component distance rows were available for the largest drift pair."
    return "; ".join(
        f"{row.metric}={_float(row.distance)}"
        for row in sorted(rows, key=lambda item: item.metric)
    )


def _offset_answer(decomposition: object | None) -> str:
    if decomposition is None or not decomposition.offset_subsamples:
        return "Replay failure prevented offset subsample comparison."
    rows = sorted(
        decomposition.offset_subsamples,
        key=lambda row: (row.spacing_days, row.offset),
    )
    return "; ".join(
        f"{row.spacing_days}d/{row.offset}:n={row.sample_count}"
        for row in rows
    )


def _cause_answer(decomposition: object | None) -> str:
    if decomposition is None:
        return "Classified as a reproduction error."
    causes = decomposition.cause_classification.causes
    return ", ".join(causes) if causes else "No decisive cause signal."


if __name__ == "__main__":
    raise SystemExit(main())
