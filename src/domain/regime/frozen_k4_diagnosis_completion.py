"""Immutable contract for publishing the frozen K4 diagnosis completion."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


DIAGNOSTIC_SCHEMA_VERSION = "frozen-k4-diagnosis-completion-v1"
COMPLETION_SCOPE = "frozen-k4-diagnosis-completion"
COMPONENT_ZERO_ANALYSIS_SCOPE = "primary-component-0-ood-exceedances"
SINGLE_FEATURE_THRESHOLD = 0.50
VOLATILITY_FAMILY_THRESHOLD = 0.70
RECURRENT_TOP1_THRESHOLD = 0.50

COMPLETION_IMPLEMENTATION_FILES = (
    "scripts/complete_frozen_three_day_k4_diagnosis.py",
    "src/application/services/frozen_k4_diagnosis_completion.py",
    "src/domain/regime/frozen_k4_diagnosis_completion.py",
)

COMPLETION_ARTIFACT_FILENAMES = frozenset(
    {
        "frozen_k4_diagnosis_completion.json",
        "frozen_k4_component_0_ood_feature_summary.csv",
        "frozen_k4_component_0_ood_family_summary.csv",
        "frozen_k4_offset_empirical_diagnostics.csv",
        "frozen_k4_offset_feature_contributions.csv",
        "frozen_k4_diagnosis_completion.md",
    }
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_THRESHOLDS = {
    "recurrent_feature_top1_ratio": RECURRENT_TOP1_THRESHOLD,
    "single_feature_contribution_ratio": SINGLE_FEATURE_THRESHOLD,
    "volatility_family_contribution_ratio": VOLATILITY_FAMILY_THRESHOLD,
}


def _canonical_sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical SHA-256")
    return value


def _canonical_basename(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "/" in value
        or "\\" in value
        or value in (".", "..")
    ):
        raise ValueError("artifact file names must be canonical basenames")
    return value


def _aggregate_implementation_hash(hashes: Mapping[str, str]) -> str:
    encoded = json.dumps(
        dict(sorted(hashes.items())),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FrozenK4DiagnosisCompletionManifest:
    run_id: str
    parent_run_id: str
    parent_manifest_sha256: str
    input_identity_sha256: str
    registry_schema_version: str
    registry_sha256: str
    implementation_file_sha256: Mapping[str, str]
    implementation_sha256: str
    completion_scope: str
    replay_parent_match_verified: bool
    thresholds: Mapping[str, float]
    file_sha256: Mapping[str, str]
    file_bytes: Mapping[str, int]
    diagnostic_schema_version: str = DIAGNOSTIC_SCHEMA_VERSION
    status: str = "completed"
    diagnostic_only: bool = True
    primary_replacement_allowed: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "run_id",
            "parent_run_id",
            "parent_manifest_sha256",
            "input_identity_sha256",
            "registry_sha256",
        ):
            _canonical_sha256(getattr(self, field_name), field_name)

        if (
            not isinstance(self.registry_schema_version, str)
            or not self.registry_schema_version
            or self.registry_schema_version != self.registry_schema_version.strip()
        ):
            raise ValueError("registry_schema_version must be a canonical non-empty string")

        implementation_hashes = self._validate_implementation_hashes()
        _canonical_sha256(self.implementation_sha256, "implementation_sha256")
        if self.implementation_sha256 != _aggregate_implementation_hash(
            implementation_hashes
        ):
            raise ValueError("implementation_sha256 does not match implementation files")

        if self.diagnostic_schema_version != DIAGNOSTIC_SCHEMA_VERSION:
            raise ValueError("diagnostic schema is unsupported")
        if self.completion_scope != COMPLETION_SCOPE:
            raise ValueError("completion scope must identify the top-level completion")
        if self.status != "completed":
            raise ValueError("manifest status must be completed")
        if self.replay_parent_match_verified is not True:
            raise ValueError("parent replay match must be verified")
        if self.diagnostic_only is not True:
            raise ValueError("completion manifest must be diagnostic-only")
        if self.primary_replacement_allowed is not False:
            raise ValueError("completion manifest cannot replace the primary model")

        thresholds = self._validate_thresholds()
        file_hashes = self._validate_file_hashes()
        file_bytes = self._validate_file_bytes()
        if set(file_hashes) != set(file_bytes):
            raise ValueError("artifact filename sets must be identical")

        object.__setattr__(
            self,
            "implementation_file_sha256",
            MappingProxyType(dict(sorted(implementation_hashes.items()))),
        )
        object.__setattr__(
            self, "thresholds", MappingProxyType(dict(sorted(thresholds.items())))
        )
        object.__setattr__(
            self, "file_sha256", MappingProxyType(dict(sorted(file_hashes.items())))
        )
        object.__setattr__(
            self, "file_bytes", MappingProxyType(dict(sorted(file_bytes.items())))
        )

    def _validate_implementation_hashes(self) -> dict[str, str]:
        if not isinstance(self.implementation_file_sha256, Mapping):
            raise ValueError("implementation file hashes must be a mapping")
        copied: dict[str, str] = {}
        for path, value in self.implementation_file_sha256.items():
            if (
                not isinstance(path, str)
                or not path
                or path != path.strip()
                or "\\" in path
                or path.startswith("/")
                or any(part in ("", ".", "..") for part in path.split("/"))
            ):
                raise ValueError("implementation file paths must be canonical")
            copied[path] = _canonical_sha256(
                value, f"implementation file hash [{path}]"
            )
        if set(copied) != set(COMPLETION_IMPLEMENTATION_FILES):
            raise ValueError("implementation file set must exactly match the contract")
        return copied

    def _validate_thresholds(self) -> dict[str, float]:
        if not isinstance(self.thresholds, Mapping):
            raise ValueError("thresholds must be a mapping")
        copied = dict(self.thresholds)
        if set(copied) != set(_THRESHOLDS):
            raise ValueError("threshold keys must exactly match the contract")
        for name, expected in _THRESHOLDS.items():
            value = copied[name]
            if type(value) is not float or value != expected:
                raise ValueError(f"threshold {name} must equal {expected}")
        return copied

    def _validate_file_hashes(self) -> dict[str, str]:
        if not isinstance(self.file_sha256, Mapping):
            raise ValueError("artifact file hashes must be a mapping")
        copied = {
            _canonical_basename(name): _canonical_sha256(
                value, f"file_sha256[{name}]"
            )
            for name, value in self.file_sha256.items()
        }
        if set(copied) != COMPLETION_ARTIFACT_FILENAMES:
            raise ValueError("artifact filename set must exactly match the contract")
        return copied

    def _validate_file_bytes(self) -> dict[str, int]:
        if not isinstance(self.file_bytes, Mapping):
            raise ValueError("artifact byte counts must be a mapping")
        copied: dict[str, int] = {}
        for name, value in self.file_bytes.items():
            canonical_name = _canonical_basename(name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("artifact byte counts must be positive integers")
            copied[canonical_name] = value
        if set(copied) != COMPLETION_ARTIFACT_FILENAMES:
            raise ValueError("artifact filename set must exactly match the contract")
        return copied

    def canonical_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "parent_manifest_sha256": self.parent_manifest_sha256,
            "input_identity_sha256": self.input_identity_sha256,
            "registry_schema_version": self.registry_schema_version,
            "registry_sha256": self.registry_sha256,
            "implementation_file_sha256": dict(self.implementation_file_sha256),
            "implementation_sha256": self.implementation_sha256,
            "completion_scope": self.completion_scope,
            "replay_parent_match_verified": self.replay_parent_match_verified,
            "thresholds": dict(self.thresholds),
            "file_sha256": dict(self.file_sha256),
            "file_bytes": dict(self.file_bytes),
            "diagnostic_schema_version": self.diagnostic_schema_version,
            "status": self.status,
            "diagnostic_only": self.diagnostic_only,
            "primary_replacement_allowed": self.primary_replacement_allowed,
        }


__all__ = [
    "COMPLETION_ARTIFACT_FILENAMES",
    "COMPLETION_IMPLEMENTATION_FILES",
    "COMPLETION_SCOPE",
    "COMPONENT_ZERO_ANALYSIS_SCOPE",
    "DIAGNOSTIC_SCHEMA_VERSION",
    "RECURRENT_TOP1_THRESHOLD",
    "SINGLE_FEATURE_THRESHOLD",
    "VOLATILITY_FAMILY_THRESHOLD",
    "FrozenK4DiagnosisCompletionManifest",
]
