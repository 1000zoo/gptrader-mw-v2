"""Bind a frozen K4 diagnosis completion to its immutable parent evidence.

Task 5 intentionally stops at validation and deterministic identity creation.
Artifact rendering and publication orchestration are added by the next task.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
from types import MappingProxyType
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.domain.regime.frozen_k4_diagnosis_completion import (  # noqa: E402
    COMPLETION_IMPLEMENTATION_FILES,
    COMPLETION_SCOPE,
    DIAGNOSTIC_SCHEMA_VERSION,
    RECURRENT_TOP1_THRESHOLD,
    SINGLE_FEATURE_THRESHOLD,
    VOLATILITY_FAMILY_THRESHOLD,
)
from src.domain.regime.frozen_k4_failure_diagnostics import (  # noqa: E402
    FrozenK4DiagnosisManifest,
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
    "CompletionImplementationReceipt",
    "DEFAULT_OUTPUT_ROOT",
    "DEFAULT_PARENT_RUN",
    "MANIFEST",
    "ParentProvenance",
    "ParentReplayReceipt",
    "PublicationError",
    "_completion_identity_payload",
    "_completion_implementation_receipt",
    "_completion_run_id",
    "_directory_bytes",
    "_load_parent_provenance",
    "_parse_args",
]
