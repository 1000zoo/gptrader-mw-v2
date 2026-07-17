"""Bind a frozen K4 diagnosis completion to its immutable parent evidence.

Task 5 intentionally stops at validation and deterministic identity creation.
Artifact rendering and publication orchestration are added by the next task.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import shutil
import sys
from tempfile import mkdtemp
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.domain.regime.frozen_k4_diagnosis_completion import (  # noqa: E402
    COMPLETION_ARTIFACT_FILENAMES,
    COMPLETION_IMPLEMENTATION_FILES,
    COMPLETION_SCOPE,
    DIAGNOSTIC_SCHEMA_VERSION,
    RECURRENT_TOP1_THRESHOLD,
    SINGLE_FEATURE_THRESHOLD,
    VOLATILITY_FAMILY_THRESHOLD,
    FrozenK4DiagnosisCompletionManifest,
)
from src.domain.regime.frozen_k4_failure_diagnostics import (  # noqa: E402
    FrozenK4DiagnosisManifest,
)
from src.application.services.frozen_k4_diagnosis_completion import (  # noqa: E402
    complete_frozen_k4_diagnosis,
)
from src.application.services.frozen_k4_failure_decomposition import (  # noqa: E402
    decompose_frozen_k4_failure,
)
from src.application.services.frozen_k4_failure_replay import (  # noqa: E402
    replay_frozen_k4_failures,
)
from src.infrastructure.regime.frozen_k4_diagnostic_source import (  # noqa: E402
    load_frozen_k4_diagnostic_source,
)


DEFAULT_PARENT_RUN = (
    REPO_ROOT
    / "docs"
    / "backtests"
    / "frozen_k4_failure_diagnosis"
    / "d89032317b12af7bc18d3a6c14ed1cb2ee47f0f5de6425a530296f3c518b55af"
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
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "docs" / "backtests" / "frozen_k4_diagnosis_completion"
MANIFEST = "manifest.json"
PARENT_REPRODUCTION = "frozen_k4_failure_reproduction.json"

_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_REPRODUCTION_BYTES = 4 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IEEE_BITS = re.compile(r"[0-9a-f]{16}")
_EXPECTED_TEMPORAL = 2.3526219570607076
_EXPECTED_OOD = 0.04631322364411944
_EXPECTED_OOD_NUMERATOR = 76
_EXPECTED_OOD_DENOMINATOR = 1641
_METRIC_BITS_KEYS = frozenset(
    {"maximum_distance_exceedance_rate", "maximum_matched_centroid_distance"}
)
_STATUS_KEYS = frozenset(
    {
        "causal_evidence_sha256",
        "decomposition_allowed",
        "diagnostic_only",
        "mismatch_classification",
        "ood_denominator",
        "ood_exceedance_numerator",
        "primary_model_ood_reproduction",
        "status",
        "temporal_half_refit_stability_reproduction",
    }
)
_METRIC_KEYS = frozenset(
    {
        "absolute_error",
        "exact_bit_match",
        "expected_value",
        "numeric_tolerance_match",
        "relative_error",
        "reproduced_value",
    }
)


class PublicationError(RuntimeError):
    """Raised when immutable completion provenance cannot be established."""


@dataclass(frozen=True)
class ParentReplayReceipt:
    status: str
    temporal_expected_value: float
    temporal_reproduced_value: float
    ood_expected_value: float
    ood_reproduced_value: float
    ood_numerator: int
    ood_denominator: int
    metric_ieee_float_bits: Mapping[str, tuple[str, str]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "metric_ieee_float_bits",
            MappingProxyType(dict(sorted(self.metric_ieee_float_bits.items()))),
        )


@dataclass(frozen=True)
class ParentProvenance:
    parent_dir: Path
    run_id: str
    manifest_sha256: str
    input_identity_sha256: str
    directory_snapshot: Mapping[str, bytes]
    replay: ParentReplayReceipt

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "directory_snapshot",
            MappingProxyType(dict(sorted(self.directory_snapshot.items()))),
        )


@dataclass(frozen=True)
class CompletionImplementationReceipt:
    file_sha256: Mapping[str, str]
    implementation_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "file_sha256",
            MappingProxyType(dict(sorted(self.file_sha256.items()))),
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    child = publish_frozen_k4_diagnosis_completion(
        parent_run=args.parent_run,
        model_attempt=args.model_attempt,
        raw_kline_root=args.raw_kline_root,
        output_root=args.output_root,
    )
    print(child)
    return 0


def publish_frozen_k4_diagnosis_completion(
    *,
    parent_run: Path,
    model_attempt: Path,
    raw_kline_root: Path,
    output_root: Path,
    source_loader: Callable[[Path, Path], object] = load_frozen_k4_diagnostic_source,
    replay_runner: Callable[[object], object] = replay_frozen_k4_failures,
    decomposition_runner: Callable[[object, object, tuple[object, ...]], object] = decompose_frozen_k4_failure,
    completion_runner: Callable[[object, object, tuple[object, ...], object], object] = complete_frozen_k4_diagnosis,
    replace_directory: Callable[[Path, Path], None] = os.replace,
) -> Path:
    """Publish one deterministic child while keeping the parent byte-identical."""
    parent = _load_parent_provenance(Path(parent_run))
    output_root = Path(output_root)
    if _is_within(output_root, parent.parent_dir):
        raise PublicationError("completion output root cannot be inside parent run")
    source = _call_preserving_parent(
        parent, source_loader, Path(model_attempt), Path(raw_kline_root)
    )
    identity_payload = _call_preserving_parent(
        parent, source.identity.canonical_payload
    )
    input_identity_sha256 = _canonical_hash(identity_payload)
    if input_identity_sha256 != parent.input_identity_sha256:
        raise PublicationError("new source input identity differs from parent")
    replay = _call_preserving_parent(parent, replay_runner, source)
    replay_validation = _validate_replay_matches_parent(parent, replay)
    decomposition = _call_preserving_parent(
        parent, decomposition_runner, replay, source.primary_fit, tuple(source.vectors)
    )
    completion = _call_preserving_parent(
        parent,
        completion_runner,
        replay, source.primary_fit, tuple(source.vectors), decomposition
    )
    implementation = _completion_implementation_receipt(REPO_ROOT)
    component = completion.component_zero_ood
    identity = _completion_identity_payload(
        parent,
        input_identity_sha256=input_identity_sha256,
        registry_schema_version=component.registry_schema_version,
        registry_sha256=component.registry_sha256,
        implementation_sha256=implementation.implementation_sha256,
        output_root=output_root,
    )
    run_id = _completion_run_id(identity, parent.run_id)
    fitted = _parent_fitted_parameter_summary(parent)
    artifacts = _render_completion_artifacts(
        completion,
        parent=parent,
        implementation=implementation,
        replay_validation=replay_validation,
        fitted_parameter_summary=fitted,
    )
    file_hashes = {name: _sha256_bytes(data) for name, data in artifacts.items()}
    file_bytes = {name: len(data) for name, data in artifacts.items()}
    manifest = FrozenK4DiagnosisCompletionManifest(
        run_id=run_id,
        parent_run_id=parent.run_id,
        parent_manifest_sha256=parent.manifest_sha256,
        input_identity_sha256=input_identity_sha256,
        registry_schema_version=component.registry_schema_version,
        registry_sha256=component.registry_sha256,
        implementation_file_sha256=implementation.file_sha256,
        implementation_sha256=implementation.implementation_sha256,
        completion_scope=COMPLETION_SCOPE,
        replay_parent_match_verified=True,
        thresholds=identity["thresholds"],
        file_sha256=file_hashes,
        file_bytes=file_bytes,
    )
    published = dict(artifacts)
    published[MANIFEST] = _canonical_json_bytes(manifest.canonical_payload())
    final_dir = output_root / run_id
    _call_preserving_parent(
        parent,
        _publish_atomically,
        output_root,
        final_dir,
        published,
        replace_directory,
    )
    if _directory_bytes(parent.parent_dir) != dict(parent.directory_snapshot):
        raise PublicationError("immutable parent changed during child publication")
    return final_dir


def _call_preserving_parent(
    parent: ParentProvenance, function: Callable[..., object], *args: object
) -> object:
    try:
        return function(*args)
    finally:
        if _directory_bytes(parent.parent_dir) != dict(parent.directory_snapshot):
            raise PublicationError("immutable parent changed during completion operation")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-run", type=Path, default=DEFAULT_PARENT_RUN)
    parser.add_argument("--model-attempt", type=Path, default=DEFAULT_MODEL_ATTEMPT)
    parser.add_argument("--raw-kline-root", type=Path, default=DEFAULT_RAW_KLINE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser.parse_args(argv)


def _load_parent_provenance(parent_dir: Path) -> ParentProvenance:
    parent_dir = Path(parent_dir)
    try:
        if not parent_dir.is_dir() or _is_link_or_reparse(parent_dir):
            raise PublicationError("parent run must be a real directory")
        entries = tuple(parent_dir.iterdir())
        if any(_is_link_or_reparse(entry) or not entry.is_file() for entry in entries):
            raise PublicationError("parent run may contain only regular files")

        manifest_bytes = _bounded_read(parent_dir / MANIFEST, _MAX_MANIFEST_BYTES)
        manifest_payload = _load_canonical_json(manifest_bytes, MANIFEST)
        if not isinstance(manifest_payload, dict):
            raise PublicationError("parent manifest must be an object")
        try:
            manifest = FrozenK4DiagnosisManifest(**manifest_payload)
        except (TypeError, ValueError) as error:
            raise PublicationError("parent manifest contract is invalid") from error
        if _canonical_json_bytes(manifest.canonical_payload()) != manifest_bytes:
            raise PublicationError("parent manifest payload must be complete and exact")

        if manifest.run_id != parent_dir.name:
            raise PublicationError("parent run ID does not match directory name")
        if manifest.status != "reproduced":
            raise PublicationError("parent diagnosis must be reproduced")
        expected_names = set(manifest.file_sha256) | {MANIFEST}
        if {entry.name for entry in entries} != expected_names:
            raise PublicationError("parent run file set is not exact")

        snapshot = _directory_bytes(parent_dir)
        for name, expected_hash in manifest.file_sha256.items():
            if _sha256_bytes(snapshot[name]) != expected_hash:
                raise PublicationError(f"parent artifact hash mismatch: {name}")

        reproduction = _load_canonical_json(
            _bounded_bytes(snapshot[PARENT_REPRODUCTION], _MAX_REPRODUCTION_BYTES),
            PARENT_REPRODUCTION,
        )
        if not isinstance(reproduction, dict):
            raise PublicationError("parent reproduction must be an object")
        input_identity = reproduction.get("input_identity")
        if not isinstance(input_identity, dict):
            raise PublicationError("parent input identity must be an object")
        reconstructed_identity_hash = _canonical_hash(input_identity)
        if reproduction.get("input_identity_sha256") != reconstructed_identity_hash:
            raise PublicationError("reproduction input identity hash is invalid")
        if manifest.input_identity_sha256 != reconstructed_identity_hash:
            raise PublicationError("manifest input identity hash is invalid")

        replay = _parent_replay_receipt(reproduction)
        return ParentProvenance(
            parent_dir=parent_dir,
            run_id=manifest.run_id,
            manifest_sha256=_sha256_bytes(manifest_bytes),
            input_identity_sha256=manifest.input_identity_sha256,
            directory_snapshot=snapshot,
            replay=replay,
        )
    except PublicationError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise PublicationError("parent run validation failed") from error


def _parent_replay_receipt(reproduction: Mapping[str, object]) -> ParentReplayReceipt:
    if reproduction.get("schema_version") != "frozen-k4-failure-reproduction-v1":
        raise PublicationError("parent reproduction schema is unsupported")
    status = reproduction.get("status")
    if not isinstance(status, dict) or set(status) != _STATUS_KEYS:
        raise PublicationError("parent reproduction status fields are not exact")
    if (
        status["status"] != "reproduced"
        or status["decomposition_allowed"] is not True
        or status["diagnostic_only"] is not True
        or status["mismatch_classification"] is not None
        or status["causal_evidence_sha256"] is not None
    ):
        raise PublicationError("parent reproduction status is invalid")

    numerator = _exact_int(status["ood_exceedance_numerator"], "OOD numerator")
    denominator = _exact_int(status["ood_denominator"], "OOD denominator")
    if (numerator, denominator) != (
        _EXPECTED_OOD_NUMERATOR,
        _EXPECTED_OOD_DENOMINATOR,
    ):
        raise PublicationError("parent OOD accounting differs from frozen failure")
    if (
        _exact_int(reproduction.get("ood_exceedance_count"), "OOD count") != numerator
        or _exact_int(reproduction.get("ood_sample_count"), "OOD sample count")
        != denominator
    ):
        raise PublicationError("parent OOD accounting is internally inconsistent")

    temporal = _metric_receipt(
        status["temporal_half_refit_stability_reproduction"],
        _EXPECTED_TEMPORAL,
        "temporal metric",
    )
    ood = _metric_receipt(
        status["primary_model_ood_reproduction"],
        _EXPECTED_OOD,
        "OOD metric",
    )
    if not math.isclose(ood[1], numerator / denominator, rel_tol=1e-12, abs_tol=1e-12):
        raise PublicationError("parent OOD rate does not match its accounting")

    bits_value = reproduction.get("metric_ieee_float_bits")
    if not isinstance(bits_value, dict) or set(bits_value) != _METRIC_BITS_KEYS:
        raise PublicationError("parent metric IEEE receipt fields are not exact")
    bits: dict[str, tuple[str, str]] = {}
    expected_values = {
        "maximum_distance_exceedance_rate": ood,
        "maximum_matched_centroid_distance": temporal,
    }
    for name, values in bits_value.items():
        if not isinstance(values, list) or len(values) != 2:
            raise PublicationError("parent IEEE receipt must contain two values")
        pair = tuple(values)
        if any(not isinstance(value, str) or not _IEEE_BITS.fullmatch(value) for value in pair):
            raise PublicationError("parent IEEE receipt is not canonical")
        expected_pair = tuple(_float_bits(value) for value in expected_values[name])
        if pair != expected_pair:
            raise PublicationError("parent IEEE receipt does not match metric values")
        bits[name] = pair  # type: ignore[assignment]

    return ParentReplayReceipt(
        status="reproduced",
        temporal_expected_value=temporal[0],
        temporal_reproduced_value=temporal[1],
        ood_expected_value=ood[0],
        ood_reproduced_value=ood[1],
        ood_numerator=numerator,
        ood_denominator=denominator,
        metric_ieee_float_bits=bits,
    )


def _metric_receipt(value: object, frozen_value: float, name: str) -> tuple[float, float]:
    if not isinstance(value, dict) or set(value) != _METRIC_KEYS:
        raise PublicationError(f"{name} fields are not exact")
    expected = _exact_float(value["expected_value"], f"{name} expected")
    reproduced = _exact_float(value["reproduced_value"], f"{name} reproduced")
    if (
        _float_bits(expected) != _float_bits(frozen_value)
        or _float_bits(reproduced) != _float_bits(frozen_value)
        or value["exact_bit_match"] is not True
        or value["numeric_tolerance_match"] is not True
        or _float_bits(
            _exact_float(value["absolute_error"], f"{name} absolute error")
        )
        != _float_bits(0.0)
        or _float_bits(
            _exact_float(value["relative_error"], f"{name} relative error")
        )
        != _float_bits(0.0)
    ):
        raise PublicationError(f"{name} does not reproduce the frozen value")
    return expected, reproduced


def _completion_implementation_receipt(
    repo_root: Path,
) -> CompletionImplementationReceipt:
    repo_root = Path(repo_root)
    if not repo_root.is_absolute() or repo_root != Path(os.path.abspath(repo_root)):
        raise PublicationError("repository root must be an absolute canonical path")
    if not repo_root.is_dir() or _is_link_or_reparse(repo_root):
        raise PublicationError("repository root must be a real directory")
    hashes: dict[str, str] = {}
    root_resolved = repo_root.resolve(strict=True)
    for relative in COMPLETION_IMPLEMENTATION_FILES:
        if (
            "\\" in relative
            or relative.startswith("/")
            or any(part in ("", ".", "..") for part in relative.split("/"))
        ):
            raise PublicationError("implementation path contract is noncanonical")
        path = repo_root.joinpath(*relative.split("/"))
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root_resolved)
        except (OSError, ValueError) as error:
            raise PublicationError("implementation file escapes repository") from error
        if resolved != path or not path.is_file() or _is_link_or_reparse(path):
            raise PublicationError("implementation file must be a canonical regular file")
        hashes[relative] = _sha256_bytes(path.read_bytes())
    if tuple(sorted(hashes)) != tuple(sorted(COMPLETION_IMPLEMENTATION_FILES)):
        raise PublicationError("implementation file set is incomplete")
    encoded = json.dumps(
        dict(sorted(hashes.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return CompletionImplementationReceipt(hashes, _sha256_bytes(encoded))


def _completion_identity_payload(
    parent: ParentProvenance,
    *,
    input_identity_sha256: str,
    registry_schema_version: str,
    registry_sha256: str,
    implementation_sha256: str,
    output_root: Path | None = None,
) -> dict[str, object]:
    for name, value in (
        ("input_identity_sha256", input_identity_sha256),
        ("registry_sha256", registry_sha256),
        ("implementation_sha256", implementation_sha256),
    ):
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise PublicationError(f"{name} must be a canonical SHA-256")
    if input_identity_sha256 != parent.input_identity_sha256:
        raise PublicationError("child source identity differs from immutable parent")
    if (
        not isinstance(registry_schema_version, str)
        or not registry_schema_version
        or registry_schema_version != registry_schema_version.strip()
    ):
        raise PublicationError("registry schema version must be canonical")
    if output_root is not None and _is_within(Path(output_root), parent.parent_dir):
        raise PublicationError("completion output root cannot be inside parent run")
    return {
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "parent_run_id": parent.run_id,
        "parent_manifest_sha256": parent.manifest_sha256,
        "input_identity_sha256": input_identity_sha256,
        "registry_schema_version": registry_schema_version,
        "registry_sha256": registry_sha256,
        "implementation_sha256": implementation_sha256,
        "completion_scope": COMPLETION_SCOPE,
        "replay_parent_match_verified": True,
        "thresholds": {
            "single_feature_contribution_ratio": SINGLE_FEATURE_THRESHOLD,
            "volatility_family_contribution_ratio": VOLATILITY_FAMILY_THRESHOLD,
            "recurrent_feature_top1_ratio": RECURRENT_TOP1_THRESHOLD,
        },
    }


def _completion_run_id(payload: Mapping[str, object], parent_run_id: str) -> str:
    run_id = _canonical_hash(payload)
    if run_id == parent_run_id:
        raise PublicationError("completion identity collides with parent run")
    return run_id


def _validate_replay_matches_parent(
    parent: ParentProvenance | object, replay: object
) -> dict[str, object]:
    """Compare the newly reproduced failure receipt bit-for-bit before analysis."""
    expected = parent.replay
    status = replay.status
    temporal = status.temporal_half_refit_stability_reproduction
    ood = status.primary_model_ood_reproduction
    if temporal is None or ood is None:
        raise PublicationError("new replay omitted failed metric receipts")
    replay_bits_object = getattr(replay, "metric_ieee_float_bits", None)
    if not isinstance(replay_bits_object, Mapping):
        raise PublicationError("new replay omitted IEEE receipt mapping")
    new_values = {
        "status": status.status,
        "temporal_expected_value": temporal.expected_value,
        "temporal_reproduced_value": temporal.reproduced_value,
        "ood_expected_value": ood.expected_value,
        "ood_reproduced_value": ood.reproduced_value,
        "ood_numerator": status.ood_exceedance_numerator,
        "ood_denominator": status.ood_denominator,
        "metric_ieee_float_bits": dict(replay_bits_object),
    }
    if any(
        type(new_values[name]) is not float
        or not math.isfinite(new_values[name])  # type: ignore[arg-type]
        for name in (
            "temporal_expected_value",
            "temporal_reproduced_value",
            "ood_expected_value",
            "ood_reproduced_value",
        )
    ):
        raise PublicationError("new replay metric receipt is not finite binary64")
    if any(
        type(new_values[name]) is not int
        for name in ("ood_numerator", "ood_denominator")
    ):
        raise PublicationError("new replay OOD accounting is not exact integer data")
    raw_bits = new_values["metric_ieee_float_bits"]
    if (
        not isinstance(raw_bits, dict)
        or set(raw_bits) != _METRIC_BITS_KEYS
        or any(
            not isinstance(pair, (tuple, list))
            or len(pair) != 2
            or any(not isinstance(value, str) or not _IEEE_BITS.fullmatch(value) for value in pair)
            for pair in raw_bits.values()
        )
    ):
        raise PublicationError("new replay IEEE receipt mapping is not exact")
    parent_values = _replay_receipt_payload(expected)
    expected_bits = {
        "maximum_distance_exceedance_rate": (
            _float_bits(new_values["ood_expected_value"]),
            _float_bits(new_values["ood_reproduced_value"]),
        ),
        "maximum_matched_centroid_distance": (
            _float_bits(new_values["temporal_expected_value"]),
            _float_bits(new_values["temporal_reproduced_value"]),
        ),
    }
    replay_bits = {key: tuple(value) for key, value in raw_bits.items()}
    comparisons = (
        new_values["status"] == parent_values["status"],
        new_values["ood_numerator"] == parent_values["ood_numerator"],
        new_values["ood_denominator"] == parent_values["ood_denominator"],
        all(
            _float_bits(new_values[name]) == _float_bits(parent_values[name])
            for name in (
                "temporal_expected_value",
                "temporal_reproduced_value",
                "ood_expected_value",
                "ood_reproduced_value",
            )
        ),
        replay_bits == expected_bits,
        replay_bits
        == {key: tuple(value) for key, value in expected.metric_ieee_float_bits.items()},
    )
    if not all(comparisons):
        raise PublicationError("new replay differs from immutable parent failure receipt")
    return {
        "parent_receipt": parent_values,
        "new_replay_receipt": {
            **{key: value for key, value in new_values.items() if key != "metric_ieee_float_bits"},
            "metric_ieee_float_bits": {key: list(value) for key, value in sorted(replay_bits.items())},
        },
        "match_verified": True,
    }


def _replay_receipt_payload(receipt: object) -> dict[str, object]:
    return {
        "status": receipt.status,
        "temporal_expected_value": receipt.temporal_expected_value,
        "temporal_reproduced_value": receipt.temporal_reproduced_value,
        "ood_expected_value": receipt.ood_expected_value,
        "ood_reproduced_value": receipt.ood_reproduced_value,
        "ood_numerator": receipt.ood_numerator,
        "ood_denominator": receipt.ood_denominator,
        "metric_ieee_float_bits": {
            key: list(value)
            for key, value in sorted(receipt.metric_ieee_float_bits.items())
        },
    }


def _parent_fitted_parameter_summary(parent: ParentProvenance) -> dict[str, object]:
    """Read the already-published fitted maximum without recomputing it."""
    from io import StringIO

    try:
        clusters = list(
            csv.DictReader(
                StringIO(
                    parent.directory_snapshot[
                        "frozen_k4_cluster_diagnostics.csv"
                    ].decode("utf-8")
                )
            )
        )
        if not clusters:
            raise PublicationError("parent fitted diagnostics are empty")
        maximum = min(
            clusters,
            key=lambda row: (
                -float(row["euclidean_distance"]),
                row["half_label"],
                int(row["primary_component_index"]),
                int(row["half_component_index"]),
            ),
        )
        distance = float(maximum["euclidean_distance"])
        if _float_bits(distance) != _float_bits(parent.replay.temporal_reproduced_value):
            raise PublicationError("parent fitted maximum differs from failure receipt")
        top_features = tuple(filter(None, maximum["top_drift_features"].split("|")))
        return {
            "metric_name": "fitted_parameter_centroid_distance",
            "half_label": maximum["half_label"],
            "primary_component_index": int(maximum["primary_component_index"]),
            "half_component_index": int(maximum["half_component_index"]),
            "primary_component_fingerprint": maximum[
                "primary_component_fingerprint"
            ],
            "half_component_fingerprint": maximum["half_component_fingerprint"],
            "distance": distance,
            "top_five_drift_features": top_features,
        }
    except PublicationError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
        raise PublicationError("parent fitted diagnostics are malformed") from error


_FEATURE_HEADERS = (
    "analysis_scope", "primary_component_index", "primary_component_fingerprint",
    "feature_name", "registry_family", "registry_schema_version", "registry_sha256",
    "contribution_sum", "contribution_ratio", "contribution_mean", "contribution_median",
    "top1_count", "top1_ratio", "top5_count", "top5_ratio", "rank",
)
_FAMILY_HEADERS = (
    "analysis_scope", "primary_component_index", "primary_component_fingerprint",
    "family_name", "family_feature_names", "registry_schema_version", "registry_sha256",
    "contribution_sum", "contribution_ratio", "concentration_threshold",
    "concentration_rule_applies", "concentration_result",
)
_DIAGNOSTIC_HEADERS = (
    "record_type", "sample_scope", "spacing_days", "offset", "offset_origin_anchor",
    "half_label", "primary_component_index", "primary_component_fingerprint",
    "half_component_index", "half_component_fingerprint", "sample_count", "sample_share",
    "centroid_status", "metric_name", "empirical_centroid", "distance", "ood_numerator",
    "ood_denominator", "ood_rate", "distance_source", "threshold_source",
    "maximum_drift_half_label", "maximum_drift_primary_component_index",
    "maximum_drift_primary_component_fingerprint", "maximum_drift_half_component_index",
    "maximum_drift_half_component_fingerprint", "maximum_ood_primary_component_index",
    "maximum_ood_primary_component_fingerprint", "top_five_drift_features",
    "drift_component_matches_full_sample", "ood_component_matches_full_sample",
    "ordered_top5_matches_full_sample", "top5_set_matches_full_sample",
)
_EMPIRICAL_FEATURE_HEADERS = (
    "sample_scope", "spacing_days", "offset", "half_label", "primary_component_index",
    "primary_component_fingerprint", "half_component_index", "half_component_fingerprint",
    "feature_name", "registry_family", "rank", "squared_distance", "contribution_ratio",
    "is_top_five",
)


def _ood_feature_rows(completion: object) -> list[dict[str, object]]:
    return [_plain(row) for row in completion.component_zero_ood.feature_rows]


def _ood_family_rows(completion: object) -> list[dict[str, object]]:
    rows = []
    for row in completion.component_zero_ood.family_rows:
        payload = _plain(row)
        payload["family_feature_names"] = ";".join(row.family_feature_names)
        rows.append(payload)
    return rows


def _empirical_diagnostic_rows(completion: object) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    scopes = (completion.full_sample_empirical, *completion.offset_empirical)
    for scope in scopes:
        for row in scope.centroid_rows:
            payload = _plain(row)
            payload["record_type"] = "centroid"
            payload["empirical_centroid"] = ";".join(_float(value) for value in row.empirical_centroid) if row.empirical_centroid is not None else None
            rows.append(payload)
    for row in (*completion.full_sample_ood, *completion.offset_ood):
        payload = _plain(row)
        payload.update({"record_type": "ood", "ood_numerator": row.numerator, "ood_denominator": row.denominator, "ood_rate": row.rate})
        rows.append(payload)
    for row in completion.offset_conclusions:
        payload = _plain(row)
        payload["record_type"] = "conclusion"
        payload["sample_scope"] = "offset_subsample"
        payload["top_five_drift_features"] = ";".join(row.top_five_drift_features)
        rows.append(payload)
    return rows


def _empirical_feature_rows(completion: object) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for scope in (completion.full_sample_empirical, *completion.offset_empirical):
        for row in scope.feature_rows:
            payload = _plain(row)
            payload["is_top_five"] = row.rank <= 5
            rows.append(payload)
    return rows


def _render_completion_artifacts(
    completion: object,
    *,
    parent: object,
    implementation: CompletionImplementationReceipt | object,
    replay_validation: Mapping[str, object],
    fitted_parameter_summary: Mapping[str, object],
) -> dict[str, bytes]:
    if completion.completion_scope != COMPLETION_SCOPE:
        raise PublicationError("completion object has the wrong top-level scope")
    component = completion.component_zero_ood
    payload = {
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "completion_scope": COMPLETION_SCOPE,
        "implementation_file_sha256": dict(implementation.file_sha256),
        "implementation_sha256": implementation.implementation_sha256,
        "replay_parent_match_verified": True,
        "replay_parent_validation": dict(replay_validation),
        "parent_provenance": {
            "parent_run_id": parent.run_id,
            "parent_manifest_sha256": parent.manifest_sha256,
            "input_identity_sha256": parent.input_identity_sha256,
        },
        "registry_provenance": {
            "registry_schema_version": component.registry_schema_version,
            "registry_sha256": component.registry_sha256,
        },
        "fixed_thresholds": {
            "single_feature_contribution_ratio": SINGLE_FEATURE_THRESHOLD,
            "volatility_family_contribution_ratio": VOLATILITY_FAMILY_THRESHOLD,
            "recurrent_feature_top1_ratio": RECURRENT_TOP1_THRESHOLD,
        },
        "component_zero_ood": _plain(component),
        "fitted_parameter_reference": dict(fitted_parameter_summary),
        "full_sample_empirical": _plain(completion.full_sample_empirical),
        "full_sample_ood": _plain(completion.full_sample_ood),
        "offset_empirical": _plain(completion.offset_empirical),
        "offset_ood": _plain(completion.offset_ood),
        "offset_consistency": _plain(completion.offset_conclusions),
        "fixed_sample_receipts": _plain(completion.sample_receipts),
        "diagnostic_only": True,
        "primary_replacement_allowed": False,
    }
    artifacts = {
        "frozen_k4_component_0_ood_feature_summary.csv": _csv_bytes(_FEATURE_HEADERS, _ood_feature_rows(completion)),
        "frozen_k4_component_0_ood_family_summary.csv": _csv_bytes(_FAMILY_HEADERS, _ood_family_rows(completion)),
        "frozen_k4_offset_empirical_diagnostics.csv": _csv_bytes(_DIAGNOSTIC_HEADERS, _empirical_diagnostic_rows(completion)),
        "frozen_k4_offset_feature_contributions.csv": _csv_bytes(_EMPIRICAL_FEATURE_HEADERS, _empirical_feature_rows(completion)),
        "frozen_k4_diagnosis_completion.json": _canonical_json_bytes(payload),
        "frozen_k4_diagnosis_completion.md": _completion_markdown(completion, fitted_parameter_summary),
    }
    if set(artifacts) != COMPLETION_ARTIFACT_FILENAMES:
        raise PublicationError("completion artifact set differs from frozen contract")
    return artifacts


def _completion_markdown(completion: object, fitted: Mapping[str, object]) -> bytes:
    component = completion.component_zero_ood
    lines = [
        "# Frozen K4 Diagnosis Completion", "",
        "This diagnostic-only report completes the frozen K4 cause diagnosis.", "",
        "## Component 0 OOD (24/409)", "",
        f"- Top five features: {', '.join(component.top_five_features)}",
    ]
    for row in component.family_rows:
        lines.append(f"- family {row.family_name}: contribution_ratio={_float(row.contribution_ratio)}")
    lines.extend([
        f"- single_feature_concentration={_bool(component.single_feature_concentration)}",
        f"- volatility_family_concentration={_bool(component.volatility_family_concentration)}",
        f"- recurrent_feature_dominance={_bool(component.recurrent_feature_dominance)}", "",
        "## Distinct distance metrics", "",
        f"- fitted_parameter_centroid_distance={_float(float(fitted['distance']))}",
        f"- full_sample_empirical_centroid_distance={_float(completion.full_sample_empirical.maximum_drift_distance)}",
        "- offset_empirical_centroid_distance is reported for every 3-day and 7-day offset.", "",
        "## Offset consistency", "",
    ])
    flags = (
        ("drift component", "drift_component_matches_full_sample"),
        ("OOD component", "ood_component_matches_full_sample"),
        ("ordered top five", "ordered_top5_matches_full_sample"),
        ("top-five set", "top5_set_matches_full_sample"),
    )
    for spacing in (3, 7):
        rows = [row for row in completion.offset_conclusions if row.spacing_days == spacing]
        for label, field in flags:
            count = sum(bool(getattr(row, field)) for row in rows)
            classification = "universal" if count == len(rows) else ("subset-only" if count == 0 else "mixed")
            lines.append(f"- {spacing}-day {label}: {count}/{len(rows)} ({classification})")
    lines.extend(["", "No model gate was re-evaluated and no strategy mapping was performed."])
    return ("\n".join(lines) + "\n").encode("utf-8")


def _directory_bytes(path: Path) -> dict[str, bytes]:
    path = Path(path)
    if not path.is_dir() or _is_link_or_reparse(path):
        raise PublicationError("snapshot target must be a real directory")
    try:
        entries = tuple(sorted(path.iterdir(), key=lambda child: child.name))
        if any(_is_link_or_reparse(entry) or not entry.is_file() for entry in entries):
            raise PublicationError("snapshot directory may contain only regular files")
        return {entry.name: entry.read_bytes() for entry in entries}
    except PublicationError:
        raise
    except OSError as error:
        raise PublicationError("directory snapshot could not be read") from error


def _plain(value: object) -> object:
    if hasattr(value, "canonical_payload"):
        return _plain(value.canonical_payload())
    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _plain(item)
            for key, item in sorted(vars(value).items())
            if not key.startswith("_")
        }
    return value


def _float(value: float) -> str:
    if not math.isfinite(float(value)):
        raise PublicationError("non-finite float cannot be rendered")
    return format(float(value), ".17g")


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _csv_bytes(headers: Sequence[str], rows: Iterable[Mapping[str, object]]) -> bytes:
    from io import StringIO

    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(headers), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        rendered: dict[str, object] = {}
        for name in headers:
            value = row.get(name)
            if value is None:
                rendered[name] = ""
            elif isinstance(value, bool):
                rendered[name] = _bool(value)
            elif isinstance(value, float):
                rendered[name] = _float(value)
            else:
                rendered[name] = value
        writer.writerow(rendered)
    return buffer.getvalue().encode("utf-8")


def _publish_atomically(
    output_root: Path,
    final_dir: Path,
    artifacts: Mapping[str, bytes],
    replace_directory: Callable[[Path, Path], None],
) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    if _is_link_or_reparse(output_root) or not output_root.is_dir():
        raise PublicationError("output root must be a real directory")
    if final_dir.exists():
        if _directory_bytes(final_dir) == dict(artifacts):
            return
        raise PublicationError(f"existing deterministic child differs: {final_dir}")
    temp_dir = Path(mkdtemp(prefix=f".{final_dir.name}.tmp-", dir=output_root))
    try:
        for name in sorted(artifacts):
            if Path(name).name != name:
                raise PublicationError("artifact name must be canonical")
            path = temp_dir / name
            with path.open("xb") as handle:
                handle.write(artifacts[name])
                handle.flush()
                os.fsync(handle.fileno())
        if _directory_bytes(temp_dir) != dict(artifacts):
            raise PublicationError("temporary completion tree differs before publication")
        replace_directory(temp_dir, final_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if final_dir.exists():
            if _directory_bytes(final_dir) != dict(artifacts):
                raise PublicationError("partial final completion run detected")
            shutil.rmtree(final_dir)
        raise


def _bounded_read(path: Path, maximum: int) -> bytes:
    if not path.is_file() or _is_link_or_reparse(path):
        raise PublicationError(f"required regular file is missing: {path.name}")
    return _bounded_bytes(path.read_bytes(), maximum)


def _bounded_bytes(data: bytes, maximum: int) -> bytes:
    if len(data) == 0 or len(data) > maximum:
        raise PublicationError("JSON artifact has an invalid byte size")
    return data


def _load_canonical_json(data: bytes, name: str) -> object:
    def reject_duplicate(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise PublicationError(f"duplicate JSON key in {name}")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate,
            parse_constant=lambda token: (_ for _ in ()).throw(
                PublicationError(f"non-finite JSON value in {name}: {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationError(f"invalid JSON in {name}") from error
    if _canonical_json_bytes(value) != data:
        raise PublicationError(f"noncanonical JSON bytes in {name}")
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PublicationError("value is not canonical JSON") from error


def _canonical_hash(value: object) -> str:
    return _sha256_bytes(_canonical_json_bytes(value))


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _exact_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PublicationError(f"{name} must be an integer")
    return value


def _exact_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, float) or not math.isfinite(value):
        raise PublicationError(f"{name} must be a finite float")
    return value


def _float_bits(value: float) -> str:
    return struct.pack(">d", value).hex()


def _is_link_or_reparse(path: Path) -> bool:
    try:
        information = path.lstat()
    except OSError:
        return False
    attributes = getattr(information, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(information.st_mode) or bool(attributes & reparse)


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(parent.resolve(strict=True))
    except (OSError, ValueError):
        return False
    return True


__all__ = [
    "COMPLETION_ARTIFACT_FILENAMES",
    "CompletionImplementationReceipt",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_PARENT_RUN",
    "MANIFEST",
    "ParentProvenance",
    "ParentReplayReceipt",
    "PublicationError",
    "_empirical_diagnostic_rows",
    "_empirical_feature_rows",
    "_render_completion_artifacts",
    "_validate_replay_matches_parent",
    "_completion_identity_payload",
    "_completion_implementation_receipt",
    "_completion_run_id",
    "_directory_bytes",
    "_load_parent_provenance",
    "_parse_args",
    "main",
    "publish_frozen_k4_diagnosis_completion",
]


if __name__ == "__main__":
    raise SystemExit(main())
