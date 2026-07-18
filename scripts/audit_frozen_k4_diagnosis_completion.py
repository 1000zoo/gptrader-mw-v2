"""Independently audit one published frozen-K4 diagnosis completion."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.domain.regime.three_day_chart_features import (  # noqa: E402
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
)
from src.infrastructure.regime.frozen_k4_diagnostic_source import (  # noqa: E402
    load_frozen_k4_diagnostic_source,
)


MANIFEST = "manifest.json"
PARENT_REPRODUCTION = "frozen_k4_failure_reproduction.json"
COMPLETION_JSON = "frozen_k4_diagnosis_completion.json"
FEATURE_CSV = "frozen_k4_component_0_ood_feature_summary.csv"
FAMILY_CSV = "frozen_k4_component_0_ood_family_summary.csv"
DIAGNOSTIC_CSV = "frozen_k4_offset_empirical_diagnostics.csv"
EMPIRICAL_FEATURE_CSV = "frozen_k4_offset_feature_contributions.csv"
REPORT = "frozen_k4_diagnosis_completion.md"
ARTIFACTS = frozenset(
    {COMPLETION_JSON, FEATURE_CSV, FAMILY_CSV, DIAGNOSTIC_CSV,
     EMPIRICAL_FEATURE_CSV, REPORT}
)
IMPLEMENTATION_FILES = (
    "scripts/complete_frozen_three_day_k4_diagnosis.py",
    "src/application/services/frozen_k4_diagnosis_completion.py",
    "src/domain/regime/frozen_k4_diagnosis_completion.py",
)
SCHEMA = "frozen-k4-diagnosis-completion-v1"
SCOPE = "frozen-k4-diagnosis-completion"
COMPONENT_SCOPE = "primary-component-0-ood-exceedances"
THRESHOLDS = {
    "single_feature_contribution_ratio": 0.5,
    "volatility_family_contribution_ratio": 0.7,
    "recurrent_feature_top1_ratio": 0.5,
}
_SHA = re.compile(r"[0-9a-f]{64}")
_FINGERPRINT = re.compile(r"[0-9a-f]{24,64}")
_REL_TOL = 1e-12
_ABS_TOL = 1e-12
_EXPECTED_TEMPORAL = 2.3526219570607076
_EXPECTED_OOD_RATE = 0.04631322364411944


class AuditError(RuntimeError):
    """Raised when evidence does not independently reconcile."""


def _fail(message: str) -> None:
    raise AuditError(message)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AuditError("value is not canonical JSON") from error


def _canonical_hash(value: object) -> str:
    return _sha256(_canonical_bytes(value))


def _document_bytes(value: object) -> bytes:
    return _canonical_bytes(value) + b"\n"


def _document_hash(value: object) -> str:
    return _sha256(_document_bytes(value))


def _reject_constant(_: str) -> object:
    raise ValueError("non-finite JSON constant")


def _load_canonical_json(path: Path) -> object:
    try:
        data = Path(path).read_bytes()
        value = json.loads(data.decode("utf-8"), parse_constant=_reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise AuditError(f"{Path(path).name} is invalid JSON") from error
    if _document_bytes(value) != data:
        raise AuditError(f"{Path(path).name} is not canonical JSON")
    return value


def _canonical_basename(value: object) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or value in (".", "..") or "/" in value or "\\" in value):
        raise AuditError("artifact name must be a canonical basename")
    return value


def _is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as error:
        raise AuditError("path metadata cannot be read") from error
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _directory(path: Path, expected: set[str] | frozenset[str] | None = None) -> dict[str, bytes]:
    path = Path(path)
    if not path.is_dir() or _is_link_or_reparse(path):
        _fail("audit run must be a real directory")
    rows: dict[str, bytes] = {}
    for child in sorted(path.iterdir(), key=lambda item: item.name):
        _canonical_basename(child.name)
        if _is_link_or_reparse(child) or not child.is_file():
            _fail("audit directory may contain only regular files")
        rows[child.name] = child.read_bytes()
    if expected is not None and set(rows) != set(expected):
        _fail("audit directory has unexpected artifact membership")
    return rows


def _float_bits(value: float) -> str:
    return struct.pack(">d", float(value)).hex()


def _close(left: object, right: object, label: str) -> None:
    try:
        left_number = float(left)  # CSV values are canonical numeric strings.
        right_number = float(right)
    except (TypeError, ValueError) as error:
        raise AuditError(f"{label} is not numeric") from error
    if (isinstance(left, bool) or isinstance(right, bool)
            or not math.isfinite(left_number) or not math.isfinite(right_number)
            or not math.isclose(left_number, right_number, rel_tol=_REL_TOL,
                                abs_tol=_ABS_TOL)):
        _fail(f"{label} does not numerically reconcile: {left!r} != {right!r}")


def _exact(left: object, right: object, label: str) -> None:
    if left != right:
        _fail(f"{label} does not exactly reconcile")


def _require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        _fail(f"{label} is not a canonical SHA-256")
    return value


def _read_manifest(run: Path, files: Mapping[str, bytes], *, child: bool) -> dict[str, object]:
    raw = files.get(MANIFEST)
    if raw is None:
        _fail("manifest is missing")
    try:
        payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except Exception as error:
        raise AuditError("manifest is invalid JSON") from error
    if not isinstance(payload, dict) or _document_bytes(payload) != raw:
        _fail("manifest must be an exact canonical object")
    parent_fields = {
        "run_id", "input_identity_sha256", "file_sha256", "status",
        "diagnostic_only", "primary_replacement_allowed",
    }
    child_fields = {
        "run_id", "parent_run_id", "parent_manifest_sha256",
        "input_identity_sha256", "registry_schema_version", "registry_sha256",
        "implementation_file_sha256", "implementation_sha256",
        "completion_scope", "replay_parent_match_verified", "thresholds",
        "file_sha256", "file_bytes", "diagnostic_schema_version", "status",
        "diagnostic_only", "primary_replacement_allowed",
    }
    if set(payload) != (child_fields if child else parent_fields):
        _fail("manifest field membership is not exact")
    _require_hash(payload.get("run_id"), "run ID")
    if payload["run_id"] != Path(run).name:
        _fail("manifest run ID differs from directory name")
    hashes = payload.get("file_sha256")
    counts = payload.get("file_bytes") if child else None
    if not isinstance(hashes, dict):
        _fail("manifest file hashes are missing")
    expected = ARTIFACTS if child else set(files) - {MANIFEST}
    if set(hashes) != set(expected):
        _fail("manifest artifact membership is not exact")
    if child and (not isinstance(counts, dict) or set(counts) != set(expected)):
        _fail("child manifest byte membership is not exact")
    for name, expected_hash in hashes.items():
        _canonical_basename(name)
        _require_hash(expected_hash, f"artifact hash {name}")
        if name not in files or _sha256(files[name]) != expected_hash:
            _fail(f"artifact hash mismatch: {name}")
        if child and (type(counts[name]) is not int or counts[name] != len(files[name])):
            _fail(f"artifact byte count mismatch: {name}")
    _exact(payload.get("status"), "completed" if child else "reproduced", "manifest status")
    _exact(payload.get("diagnostic_only"), True, "manifest diagnostic-only policy")
    _exact(payload.get("primary_replacement_allowed"), False, "manifest replacement policy")
    _require_hash(payload.get("input_identity_sha256"), "manifest input identity")
    return payload


def _implementation_receipt() -> tuple[dict[str, str], str]:
    hashes: dict[str, str] = {}
    root = REPO_ROOT.resolve(strict=True)
    for relative in IMPLEMENTATION_FILES:
        path = REPO_ROOT.joinpath(*relative.split("/"))
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as error:
            raise AuditError(f"producer implementation path invalid: {relative}") from error
        if resolved != path or _is_link_or_reparse(path) or not path.is_file():
            _fail(f"producer implementation path invalid: {relative}")
        hashes[relative] = _sha256(path.read_bytes())
    return hashes, _canonical_hash(dict(sorted(hashes.items())))


def _registry_hash(feature_names: Sequence[str]) -> str:
    registry = [
        {"name": row.name, "family": row.family,
         "aggregation_minutes": row.aggregation_minutes,
         "lookback_minutes": row.lookback_minutes, "formula": row.formula}
        for row in THREE_DAY_CHART_FEATURE_REGISTRY_V1
    ]
    return _canonical_hash({
        "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        "retained_feature_names": list(feature_names), "registry": registry,
    })


def _parse_csv(data: bytes, expected_headers: tuple[str, ...], label: str) -> list[dict[str, str]]:
    try:
        text = data.decode("utf-8")
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if tuple(reader.fieldnames or ()) != expected_headers:
            _fail(f"{label} headers differ from contract")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as error:
        raise AuditError(f"{label} is malformed") from error
    if any(None in row for row in rows):
        _fail(f"{label} contains surplus columns")
    return rows


def _f(value: object, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise AuditError(f"{label} is not numeric") from error
    if not math.isfinite(result):
        _fail(f"{label} is not finite")
    return result


def _i(value: object, label: str) -> int:
    if isinstance(value, bool):
        _fail(f"{label} is not an integer")
    try:
        result = int(str(value))
    except (TypeError, ValueError) as error:
        raise AuditError(f"{label} is not an integer") from error
    if str(result) != str(value):
        _fail(f"{label} is not a canonical integer")
    return result


def _b(value: object, label: str) -> bool:
    if type(value) is bool:
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    _fail(f"{label} is not a canonical boolean")


def _transform(primary: object, vectors: Sequence[object]) -> list[list[float]]:
    names = tuple(primary.feature_names)
    output = []
    for vector in vectors:
        row = []
        for index, name in enumerate(names):
            value = float(vector.values[name])
            value = min(max(value, primary.lower_bounds[index]), primary.upper_bounds[index])
            row.append((value - primary.medians[index]) / primary.scales[index])
        output.append(row)
    return output


def _primary_assignment(primary: object, row: Sequence[float]) -> int:
    scores = []
    for component, (mean, covariance, weight) in enumerate(
        zip(primary.means, primary.covariances, primary.weights)
    ):
        variance = [float(value) for value in covariance]
        if any(not math.isfinite(value) or value <= 0 for value in variance):
            _fail("stored primary covariance must be finite and positive")
        score = math.log(float(weight)) - 0.5 * (
            len(row) * math.log(2 * math.pi)
            + math.fsum(math.log(value) for value in variance)
            + math.fsum((value - center) ** 2 / var
                        for value, center, var in zip(row, mean, variance))
        )
        scores.append((score, -component))
    return max(range(len(scores)), key=lambda index: scores[index])


def _anchor(vector: object) -> str:
    return vector.anchor_at.isoformat().replace("+00:00", "Z")


def _parent_half_graph(parent_reproduction: Mapping[str, object], primary: object) -> dict[tuple[str, int], tuple[int, str, str]]:
    halves = parent_reproduction.get("half_replays")
    if not isinstance(halves, list) or len(halves) != 2:
        _fail("parent must publish exactly two half replays")
    graph: dict[tuple[str, int], tuple[int, str, str]] = {}
    for expected_label, expected_count, half in zip(("A", "B"), (820, 821), halves):
        if not isinstance(half, dict) or not isinstance(half.get("receipt"), dict):
            _fail("parent half replay receipt is malformed")
        receipt = half["receipt"]
        _exact(receipt.get("half_label"), expected_label, "parent half label")
        _exact(receipt.get("anchor_count"), expected_count, "parent half count")
        pairs = half.get("matched_pairs")
        if not isinstance(pairs, list) or len(pairs) != 4:
            _fail("parent matched-pair graph must be K4")
        primary_indices: set[int] = set()
        half_indices: set[int] = set()
        for pair in pairs:
            if not isinstance(pair, dict):
                _fail("parent matched-pair row is malformed")
            _exact(pair.get("half_label"), expected_label, "parent matched-pair half")
            half_index = pair.get("half_component_index")
            primary_index = pair.get("primary_component_index")
            if (type(half_index) is not int or type(primary_index) is not int
                    or not 0 <= half_index < 4 or not 0 <= primary_index < 4):
                _fail("parent matched-pair indices are invalid")
            half_fp = pair.get("half_component_fingerprint")
            primary_fp = pair.get("primary_component_fingerprint")
            if not isinstance(half_fp, str) or _FINGERPRINT.fullmatch(half_fp) is None:
                _fail("parent matched-pair half fingerprint is invalid")
            _exact(primary_fp, primary.fingerprints[primary_index],
                   "parent matched-pair primary fingerprint")
            graph[(expected_label, half_index)] = (primary_index, str(primary_fp), half_fp)
            primary_indices.add(primary_index)
            half_indices.add(half_index)
        if primary_indices != set(range(4)) or half_indices != set(range(4)):
            _fail("parent matched-pair graph is not one-to-one K4")
    return graph


def _verify_receipts(payload: Mapping[str, object], source: object,
                     parent_reproduction: Mapping[str, object]) -> tuple[list[dict[str, object]], list[list[float]]]:
    receipts = payload.get("fixed_sample_receipts")
    if not isinstance(receipts, list) or len(receipts) != 1641:
        _fail("fixed sample receipt ledger must contain 1,641 rows")
    vectors = tuple(source.vectors)
    if len(vectors) != len(receipts):
        _fail("source vector count differs from sample ledger")
    scaled = _transform(source.primary_fit, vectors)
    parent_graph = _parent_half_graph(parent_reproduction, source.primary_fit)
    half_counts = {"A": 0, "B": 0}
    receipt_fields = {
        "global_index", "anchor_at", "half_label", "half_component_index",
        "half_component_fingerprint", "matched_primary_component_index",
        "matched_primary_component_fingerprint", "primary_component_index",
        "primary_component_fingerprint", "squared_mahalanobis", "ood_threshold",
        "ood_exceeds", "assignment_source",
    }
    for index, (receipt, vector, row) in enumerate(zip(receipts, vectors, scaled)):
        if not isinstance(receipt, dict) or set(receipt) != receipt_fields:
            _fail("fixed sample receipt fields must be exact")
        _exact(receipt.get("global_index"), index, "sample global index")
        _exact(receipt.get("anchor_at"), _anchor(vector), "sample anchor")
        half = receipt.get("half_label")
        if half not in half_counts:
            _fail("sample half label is invalid")
        half_counts[str(half)] += 1
        _exact(half, "A" if index < 820 else "B", "sample half boundary")
        half_component = receipt.get("half_component_index")
        if type(half_component) is not int or not 0 <= half_component < 4:
            _fail("receipt half component index is invalid")
        assigned = _primary_assignment(source.primary_fit, row)
        _exact(receipt.get("primary_component_index"), assigned, "primary assignment")
        _exact(receipt.get("primary_component_fingerprint"),
               source.primary_fit.fingerprints[assigned], "primary fingerprint")
        for key in ("half_component_fingerprint", "matched_primary_component_fingerprint"):
            if not isinstance(receipt.get(key), str) or _FINGERPRINT.fullmatch(str(receipt[key])) is None:
                _fail(f"receipt {key} is invalid")
        matched = _i(receipt.get("matched_primary_component_index"), "matched component")
        _exact(receipt.get("matched_primary_component_fingerprint"),
               source.primary_fit.fingerprints[matched], "matched primary fingerprint")
        _exact(
            (matched, receipt.get("matched_primary_component_fingerprint"),
             receipt.get("half_component_fingerprint")),
            parent_graph[(str(half), int(half_component))],
            "sample receipt parent matched-pair identity",
        )
        mean = source.primary_fit.means[assigned]
        covariance = source.primary_fit.covariances[assigned]
        squared = math.fsum((value - center) ** 2 / max(float(var), 1e-6)
                            for value, center, var in zip(row, mean, covariance))
        threshold = float(source.primary_fit.distance_thresholds[assigned])
        _close(receipt.get("squared_mahalanobis"), squared, "sample Mahalanobis distance")
        _close(receipt.get("ood_threshold"), threshold, "sample OOD threshold")
        _exact(receipt.get("ood_exceeds"), squared > threshold, "strict OOD flag")
        _exact(receipt.get("assignment_source"),
               "frozen_reproduced_assignments_and_ood_rows", "receipt provenance")
    _exact(half_counts, {"A": 820, "B": 821}, "half sample counts")
    return receipts, scaled


def _verify_component_zero(payload: Mapping[str, object], source: object,
                           receipts: Sequence[Mapping[str, object]],
                           scaled: Sequence[Sequence[float]], files: Mapping[str, bytes]) -> tuple[bool, bool, bool]:
    component = payload.get("component_zero_ood")
    if not isinstance(component, dict):
        _fail("Component 0 analysis is missing")
    _exact(component.get("analysis_scope"), COMPONENT_SCOPE, "Component 0 scope")
    _exact(component.get("primary_component_index"), 0, "Component 0 index")
    _exact(component.get("primary_component_fingerprint"), source.primary_fit.fingerprints[0],
           "Component 0 fingerprint")
    assigned = [index for index, row in enumerate(receipts)
                if row["primary_component_index"] == 0]
    ood = [index for index in assigned if receipts[index]["ood_exceeds"]]
    _exact((len(assigned), len(ood)), (409, 24), "Component 0 OOD population")
    _exact(component.get("assigned_sample_count"), 409, "Component 0 denominator")
    _exact(component.get("ood_sample_count"), 24, "Component 0 numerator")
    names = tuple(source.primary_fit.feature_names)
    positions = {name: index for index, name in enumerate(names)}
    registry = {row.name: row for row in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
    registry_hash = _registry_hash(names)
    _exact(component.get("registry_schema_version"), THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
           "registry schema")
    _exact(component.get("registry_sha256"), registry_hash, "registry hash")
    per_sample = []
    for index in ood:
        values = [
            (scaled[index][feature] - source.primary_fit.means[0][feature]) ** 2
            / max(float(source.primary_fit.covariances[0][feature]), 1e-6)
            for feature in range(len(names))
        ]
        _close(math.fsum(values), receipts[index]["squared_mahalanobis"],
               "Component 0 contribution sum")
        per_sample.append(values)
    totals = [math.fsum(row[index] for row in per_sample) for index in range(len(names))]
    grand = math.fsum(totals)
    orders = [sorted(range(len(names)), key=lambda index: (-row[index], index))
              for row in per_sample]
    ranking = sorted(range(len(names)), key=lambda index: (-totals[index], index))
    expected_features = []
    for rank, index in enumerate(ranking, 1):
        values = sorted(row[index] for row in per_sample)
        median = (values[11] + values[12]) / 2
        top1 = sum(order[0] == index for order in orders)
        top5 = sum(index in order[:5] for order in orders)
        expected_features.append({
            "analysis_scope": COMPONENT_SCOPE, "primary_component_index": 0,
            "primary_component_fingerprint": source.primary_fit.fingerprints[0],
            "feature_name": names[index], "registry_family": registry[names[index]].family,
            "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
            "registry_sha256": registry_hash, "contribution_sum": totals[index],
            "contribution_ratio": totals[index] / grand,
            "contribution_mean": totals[index] / 24, "contribution_median": median,
            "top1_count": top1, "top1_ratio": top1 / 24,
            "top5_count": top5, "top5_ratio": top5 / 24, "rank": rank,
        })
    _compare_objects(component.get("feature_rows"), expected_features, "feature summaries")
    feature_headers = tuple(expected_features[0])
    feature_rows = _parse_csv(files[FEATURE_CSV], feature_headers, FEATURE_CSV)
    _compare_csv(feature_rows, expected_features, "feature CSV")
    family_order = []
    for name in names:
        family = registry[name].family
        if family not in family_order:
            family_order.append(family)
    expected_families = []
    for family in family_order:
        family_names = tuple(name for name in names if registry[name].family == family)
        total = math.fsum(totals[positions[name]] for name in family_names)
        ratio = total / grand
        applies = family == "volatility"
        expected_families.append({
            "analysis_scope": COMPONENT_SCOPE, "primary_component_index": 0,
            "primary_component_fingerprint": source.primary_fit.fingerprints[0],
            "family_name": family, "family_feature_names": list(family_names),
            "registry_schema_version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
            "registry_sha256": registry_hash, "contribution_sum": total,
            "contribution_ratio": ratio, "concentration_threshold": 0.7,
            "concentration_rule_applies": applies,
            "concentration_result": applies and ratio >= 0.7,
        })
    _compare_objects(component.get("family_rows"), expected_families, "family summaries")
    family_headers = tuple(expected_families[0])
    family_csv = _parse_csv(files[FAMILY_CSV], family_headers, FAMILY_CSV)
    csv_families = [{**row, "family_feature_names": row["family_feature_names"].split(";")}
                    for row in family_csv]
    _compare_csv(csv_families, expected_families, "family CSV")
    top = tuple(names[index] for index in ranking[:5])
    _exact(tuple(component.get("top_five_features", ())), top, "Component 0 top five")
    flags = (totals[ranking[0]] / grand >= 0.5,
             next(row["contribution_ratio"] for row in expected_families
                  if row["family_name"] == "volatility") >= 0.7,
             max(row["top1_ratio"] for row in expected_features) >= 0.5)
    for key, expected in zip(("single_feature_concentration",
                              "volatility_family_concentration",
                              "recurrent_feature_dominance"), flags):
        _exact(component.get(key), expected, key)
    return flags


def _compare_objects(actual: object, expected: Sequence[Mapping[str, object]], label: str) -> None:
    if not isinstance(actual, list) or len(actual) != len(expected):
        _fail(f"{label} row count differs")
    for left, right in zip(actual, expected):
        if not isinstance(left, dict) or set(left) != set(right):
            _fail(f"{label} fields differ")
        for key, value in right.items():
            if type(value) is float:
                _close(left[key], value, f"{label}.{key}")
            else:
                _exact(left[key], value, f"{label}.{key}")


def _compare_csv(actual: Sequence[Mapping[str, object]], expected: Sequence[Mapping[str, object]], label: str) -> None:
    if len(actual) != len(expected):
        _fail(f"{label} row count differs")
    for row, target in zip(actual, expected):
        for key, value in target.items():
            current = row[key]
            if type(value) is bool:
                _exact(_b(current, f"{label}.{key}"), value, f"{label}.{key}")
            elif type(value) is int:
                _exact(_i(current, f"{label}.{key}"), value, f"{label}.{key}")
            elif type(value) is float:
                _close(_f(current, f"{label}.{key}"), value, f"{label}.{key}")
            elif isinstance(value, list):
                _exact(current, value, f"{label}.{key}")
            else:
                _exact(current, str(value), f"{label}.{key}")


def _scope_key(scope: Mapping[str, object]) -> tuple[str, int | None, int | None]:
    return str(scope["sample_scope"]), scope.get("spacing_days"), scope.get("offset")


def _selected(key: tuple[str, int | None, int | None], count: int) -> list[int]:
    _, spacing, offset = key
    return list(range(count)) if spacing is None else [i for i in range(count) if i % spacing == offset]


def _max_ood(rows: Sequence[Mapping[str, object]]) -> Mapping[str, object]:
    represented = [row for row in rows if row["denominator"] > 0]
    return min(represented, key=lambda row: (-float(row["rate"]), -int(row["numerator"]),
                                             -int(row["denominator"]), int(row["primary_component_index"])))


def _verify_empirical(payload: Mapping[str, object], source: object,
                      receipts: Sequence[Mapping[str, object]], scaled: Sequence[Sequence[float]],
                      files: Mapping[str, bytes]) -> None:
    full = payload.get("full_sample_empirical")
    offsets = payload.get("offset_empirical")
    conclusions = payload.get("offset_consistency")
    if not isinstance(full, dict) or not isinstance(offsets, list) or not isinstance(conclusions, list):
        _fail("empirical completion sections are missing")
    scopes = [full, *offsets]
    expected_keys = [("full_sample", None, None)] + [
        ("offset_subsample", spacing, offset)
        for spacing in (3, 7) for offset in range(spacing)
    ]
    _exact([_scope_key(row) for row in scopes], expected_keys, "empirical scope ordering")
    origin = receipts[0]["anchor_at"]
    names = tuple(source.primary_fit.feature_names)
    family = {row.name: row.family for row in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
    all_expected_features: list[dict[str, object]] = []
    all_expected_centroids: list[dict[str, object]] = []
    pairs: dict[tuple[str, int], tuple[int, str, str]] = {}
    for receipt in receipts:
        identity = (str(receipt["half_label"]), int(receipt["half_component_index"]))
        value = (int(receipt["matched_primary_component_index"]),
                 str(receipt["matched_primary_component_fingerprint"]),
                 str(receipt["half_component_fingerprint"]))
        if identity in pairs and pairs[identity] != value:
            _fail("receipt half-to-primary match is inconsistent")
        pairs[identity] = value
    if len(pairs) != 8:
        _fail("receipt match graph must contain two K4 halves")
    for half in ("A", "B"):
        half_pairs = [(half_component, value[0]) for (label, half_component), value in pairs.items()
                      if label == half]
        if ({row[0] for row in half_pairs} != set(range(4))
                or {row[1] for row in half_pairs} != set(range(4))):
            _fail("receipt match graph must be a one-to-one K4 map in each half")
    scope_results: dict[tuple[str, int | None, int | None], dict[str, object]] = {}
    for scope, key in zip(scopes, expected_keys):
        selected = _selected(key, len(receipts))
        _exact(scope.get("selected_sample_count"), len(selected), "scope selected count")
        expected_centroids = []
        expected_features = []
        ordered_pairs = sorted(
            pairs.items(), key=lambda item: (item[0][0], item[1][0], item[0][1])
        )
        for (half, half_component), pair_identity in ordered_pairs:
            primary_component, primary_fp, half_fp = pair_identity
            indices = [index for index in selected
                       if receipts[index]["half_label"] == half
                       and receipts[index]["half_component_index"] == half_component]
            half_total = sum(receipts[index]["half_label"] == half for index in selected)
            base = {
                "sample_scope": key[0], "spacing_days": key[1], "offset": key[2],
                "offset_origin_anchor": origin, "half_label": half,
                "primary_component_index": primary_component,
                "half_component_index": half_component,
                "primary_component_fingerprint": primary_fp,
                "half_component_fingerprint": half_fp,
                "sample_count": len(indices),
                "sample_share": len(indices) / half_total if half_total else 0.0,
                "assignment_source": "frozen_reproduced_half_assignment",
                "refit_performed": False, "rematch_performed": False,
                "diagnostic_only": True,
            }
            if not indices:
                expected_centroids.append({**base, "centroid_status": "insufficient_sample",
                    "metric_name": "full_sample_empirical_centroid_distance" if key[1] is None else "offset_empirical_centroid_distance",
                    "empirical_centroid": None, "distance": None})
                continue
            centroid = [math.fsum(scaled[index][feature] for index in indices) / len(indices)
                        for feature in range(len(names))]
            squares = [(value - source.primary_fit.means[primary_component][feature]) ** 2
                       for feature, value in enumerate(centroid)]
            distance = math.sqrt(math.fsum(squares))
            expected_centroids.append({**base, "centroid_status": "computed",
                "metric_name": "full_sample_empirical_centroid_distance" if key[1] is None else "offset_empirical_centroid_distance",
                "empirical_centroid": centroid, "distance": distance})
            order = sorted(range(len(names)), key=lambda feature_index: (-squares[feature_index], feature_index))
            for rank, feature_index in enumerate(order, 1):
                expected_features.append({
                    "sample_scope": key[0], "spacing_days": key[1], "offset": key[2],
                    "half_label": half, "primary_component_index": primary_component,
                    "half_component_index": half_component,
                    "primary_component_fingerprint": primary_fp,
                    "half_component_fingerprint": half_fp, "feature_name": names[feature_index],
                    "registry_family": family[names[feature_index]], "rank": rank,
                    "squared_distance": squares[feature_index],
                    "contribution_ratio": squares[feature_index] / math.fsum(squares) if distance else 0.0,
                })
        _compare_objects(scope.get("centroid_rows"), expected_centroids, "empirical centroids")
        _compare_objects(scope.get("feature_rows"), expected_features, "empirical features")
        valid = [row for row in expected_centroids if row["distance"] is not None]
        maximum = min(valid, key=lambda row: (-float(row["distance"]), str(row["half_label"]),
                                              int(row["primary_component_index"]), int(row["half_component_index"])))
        maximum_features = [row for row in expected_features
                            if row["half_label"] == maximum["half_label"]
                            and row["half_component_index"] == maximum["half_component_index"]]
        top5 = tuple(str(row["feature_name"]) for row in maximum_features[:5])
        for field in ("maximum_drift_half_label", "maximum_drift_primary_component_index",
                      "maximum_drift_half_component_index", "maximum_drift_primary_component_fingerprint",
                      "maximum_drift_half_component_fingerprint"):
            source_field = field.removeprefix("maximum_drift_")
            _exact(scope.get(field), maximum[source_field], f"scope {field}")
        _close(scope.get("maximum_drift_distance"), maximum["distance"], "scope maximum distance")
        _exact(tuple(scope.get("top_five_drift_features", ())), top5, "scope top five")
        scope_results[key] = {"maximum": maximum, "top5": top5}
        all_expected_centroids.extend(expected_centroids)
        all_expected_features.extend(expected_features)
    _verify_ood_and_conclusions(payload, receipts, source, scope_results, conclusions)
    _verify_empirical_csvs(files, all_expected_centroids, all_expected_features, payload)


def _verify_ood_and_conclusions(payload: Mapping[str, object], receipts: Sequence[Mapping[str, object]],
                                source: object, results: Mapping[tuple[str, int | None, int | None], Mapping[str, object]],
                                conclusions: Sequence[Mapping[str, object]]) -> None:
    full_rows = payload.get("full_sample_ood")
    offset_rows = payload.get("offset_ood")
    if not isinstance(full_rows, list) or not isinstance(offset_rows, list):
        _fail("OOD aggregate sections are missing")
    expected_all = []
    expected_by_key = {}
    for key in results:
        selected = _selected(key, len(receipts))
        rows = []
        for component in range(4):
            assigned = [receipts[index] for index in selected
                        if receipts[index]["primary_component_index"] == component]
            numerator = sum(bool(row["ood_exceeds"]) for row in assigned)
            denominator = len(assigned)
            rows.append({"sample_scope": key[0], "spacing_days": key[1], "offset": key[2],
                "primary_component_index": component,
                "primary_component_fingerprint": source.primary_fit.fingerprints[component],
                "numerator": numerator, "denominator": denominator,
                "rate": numerator / denominator if denominator else None,
                "distance_source": "frozen_primary_ood_row",
                "threshold_source": "frozen_primary_component_threshold"})
        expected_by_key[key] = rows
        expected_all.extend(rows)
    _compare_objects(full_rows, expected_by_key[("full_sample", None, None)], "full OOD")
    _exact(sum(row["numerator"] for row in expected_by_key[("full_sample", None, None)]),
           76, "full-sample OOD numerator")
    _exact(sum(row["denominator"] for row in expected_by_key[("full_sample", None, None)]),
           1641, "full-sample OOD denominator")
    _compare_objects(offset_rows, expected_all[4:], "offset OOD")
    full_result = results[("full_sample", None, None)]
    full_ood = _max_ood(expected_by_key[("full_sample", None, None)])
    expected_conclusions = []
    for spacing in (3, 7):
        for offset in range(spacing):
            key = ("offset_subsample", spacing, offset)
            maximum = results[key]["maximum"]
            maximum_ood = _max_ood(expected_by_key[key])
            top5 = tuple(results[key]["top5"])
            full_top5 = tuple(full_result["top5"])
            expected_conclusions.append({
                "spacing_days": spacing, "offset": offset,
                "maximum_drift_half_label": maximum["half_label"],
                "maximum_drift_primary_component_index": maximum["primary_component_index"],
                "maximum_drift_primary_component_fingerprint": maximum["primary_component_fingerprint"],
                "maximum_drift_half_component_index": maximum["half_component_index"],
                "maximum_drift_half_component_fingerprint": maximum["half_component_fingerprint"],
                "maximum_ood_primary_component_index": maximum_ood["primary_component_index"],
                "maximum_ood_primary_component_fingerprint": maximum_ood["primary_component_fingerprint"],
                "top_five_drift_features": list(top5),
                "drift_component_matches_full_sample": maximum["primary_component_index"] == full_result["maximum"]["primary_component_index"],
                "ood_component_matches_full_sample": maximum_ood["primary_component_index"] == full_ood["primary_component_index"],
                "ordered_top5_matches_full_sample": top5 == full_top5,
                "top5_set_matches_full_sample": set(top5) == set(full_top5),
            })
    _compare_objects(conclusions, expected_conclusions, "offset conclusions")


def _verify_empirical_csvs(files: Mapping[str, bytes], centroids: Sequence[Mapping[str, object]],
                           features: Sequence[Mapping[str, object]], payload: Mapping[str, object]) -> None:
    feature_headers = ("sample_scope", "spacing_days", "offset", "half_label",
        "primary_component_index", "primary_component_fingerprint", "half_component_index",
        "half_component_fingerprint", "feature_name", "registry_family", "rank",
        "squared_distance", "contribution_ratio", "is_top_five")
    rows = _parse_csv(files[EMPIRICAL_FEATURE_CSV], feature_headers, EMPIRICAL_FEATURE_CSV)
    expected = [{**row, "is_top_five": row["rank"] <= 5} for row in features]
    _compare_csv_nullable(rows, expected, "empirical feature CSV")
    diagnostic_headers = ("record_type", "sample_scope", "spacing_days", "offset",
        "offset_origin_anchor", "half_label", "primary_component_index",
        "primary_component_fingerprint", "half_component_index", "half_component_fingerprint",
        "sample_count", "sample_share", "centroid_status", "metric_name",
        "empirical_centroid", "distance", "ood_numerator", "ood_denominator", "ood_rate",
        "distance_source", "threshold_source", "maximum_drift_half_label",
        "maximum_drift_primary_component_index", "maximum_drift_primary_component_fingerprint",
        "maximum_drift_half_component_index", "maximum_drift_half_component_fingerprint",
        "maximum_ood_primary_component_index", "maximum_ood_primary_component_fingerprint",
        "top_five_drift_features", "drift_component_matches_full_sample",
        "ood_component_matches_full_sample", "ordered_top5_matches_full_sample",
        "top5_set_matches_full_sample")
    rows = _parse_csv(files[DIAGNOSTIC_CSV], diagnostic_headers, DIAGNOSTIC_CSV)
    expected_total = len(centroids) + len(payload["full_sample_ood"]) + len(payload["offset_ood"]) + len(payload["offset_consistency"])
    if len(rows) != expected_total or {row["record_type"] for row in rows} != {"centroid", "ood", "conclusion"}:
        _fail("diagnostic CSV record graph differs")
    centroid_rows = [row for row in rows if row["record_type"] == "centroid"]
    if len(centroid_rows) != len(centroids):
        _fail("diagnostic centroid CSV row count differs")
    for actual, expected_row in zip(centroid_rows, centroids):
        for key in ("sample_scope", "half_label", "primary_component_fingerprint",
                    "half_component_fingerprint", "centroid_status", "metric_name",
                    "offset_origin_anchor"):
            _exact(actual[key], str(expected_row[key]), f"diagnostic CSV {key}")
        for key in ("spacing_days", "offset", "primary_component_index", "half_component_index",
                    "sample_count"):
            expected_value = expected_row[key]
            _exact(actual[key], "" if expected_value is None else str(expected_value),
                   f"diagnostic CSV {key}")
        _close(actual["sample_share"], expected_row["sample_share"], "diagnostic sample share")
        centroid = expected_row["empirical_centroid"]
        expected_text = "" if centroid is None else ";".join(format(float(value), ".17g") for value in centroid)
        _exact(actual["empirical_centroid"], expected_text, "diagnostic empirical centroid")
        if expected_row["distance"] is None:
            _exact(actual["distance"], "", "diagnostic null distance")
        else:
            _close(actual["distance"], expected_row["distance"], "diagnostic distance")
    scopes = [payload["full_sample_empirical"], *payload["offset_empirical"]]
    scope_map = {_scope_key(scope): scope for scope in scopes}
    ood_json = [*payload["full_sample_ood"], *payload["offset_ood"]]
    ood_map = {
        (row["sample_scope"], row.get("spacing_days"), row.get("offset"),
         row["primary_component_index"]): row for row in ood_json
    }
    ood_csv_rows = [row for row in rows if row["record_type"] == "ood"]
    ood_csv_identities = [
        (row["sample_scope"], _nullable_int(row["spacing_days"]),
         _nullable_int(row["offset"]), _i(row["primary_component_index"], "diagnostic OOD component"))
        for row in ood_csv_rows
    ]
    if len(ood_csv_identities) != len(set(ood_csv_identities)) or set(ood_csv_identities) != set(ood_map):
        _fail("diagnostic CSV OOD identities are not exact one-to-one")
    for actual in ood_csv_rows:
        key = (actual["sample_scope"], _nullable_int(actual["spacing_days"]),
               _nullable_int(actual["offset"]), _i(actual["primary_component_index"], "diagnostic OOD component"))
        expected_row = ood_map.get(key)
        if expected_row is None:
            _fail("diagnostic CSV contains an unknown OOD identity")
        for field in ("primary_component_fingerprint", "distance_source", "threshold_source"):
            _exact(actual[field], str(expected_row[field]), f"diagnostic OOD {field}")
        _exact(_i(actual["ood_numerator"], "diagnostic OOD numerator"), expected_row["numerator"],
               "diagnostic OOD numerator")
        _exact(_i(actual["ood_denominator"], "diagnostic OOD denominator"), expected_row["denominator"],
               "diagnostic OOD denominator")
        if expected_row["rate"] is None:
            _exact(actual["ood_rate"], "", "diagnostic null OOD rate")
        else:
            _close(actual["ood_rate"], expected_row["rate"], "diagnostic OOD rate")
        _verify_decorated_scope(actual, scope_map[key[:3]], ood_json)
    conclusion_map = {(row["spacing_days"], row["offset"]): row
                      for row in payload["offset_consistency"]}
    conclusion_csv_rows = [row for row in rows if row["record_type"] == "conclusion"]
    conclusion_identities = [
        (_i(row["spacing_days"], "diagnostic conclusion spacing"),
         _i(row["offset"], "diagnostic conclusion offset"))
        for row in conclusion_csv_rows
    ]
    if (len(conclusion_identities) != len(set(conclusion_identities))
            or set(conclusion_identities) != set(conclusion_map)):
        _fail("diagnostic CSV conclusion identities are not exact one-to-one")
    for actual in conclusion_csv_rows:
        spacing = _i(actual["spacing_days"], "diagnostic conclusion spacing")
        offset = _i(actual["offset"], "diagnostic conclusion offset")
        expected_row = conclusion_map.get((spacing, offset))
        if expected_row is None:
            _fail("diagnostic CSV contains an unknown conclusion identity")
        for field in ("maximum_drift_half_label", "maximum_drift_primary_component_fingerprint",
                      "maximum_drift_half_component_fingerprint",
                      "maximum_ood_primary_component_fingerprint"):
            _exact(actual[field], str(expected_row[field]), f"diagnostic conclusion {field}")
        for field in ("maximum_drift_primary_component_index", "maximum_drift_half_component_index",
                      "maximum_ood_primary_component_index"):
            _exact(_i(actual[field], f"diagnostic conclusion {field}"), expected_row[field],
                   f"diagnostic conclusion {field}")
        _exact(actual["top_five_drift_features"], ";".join(expected_row["top_five_drift_features"]),
               "diagnostic conclusion top five")
        for field in ("drift_component_matches_full_sample", "ood_component_matches_full_sample",
                      "ordered_top5_matches_full_sample", "top5_set_matches_full_sample"):
            _exact(_b(actual[field], f"diagnostic conclusion {field}"), expected_row[field],
                   f"diagnostic conclusion {field}")
        _verify_decorated_scope(actual, scope_map[("offset_subsample", spacing, offset)], ood_json)


def _nullable_int(value: str) -> int | None:
    return None if value == "" else _i(value, "nullable integer")


def _verify_decorated_scope(actual: Mapping[str, str], scope: Mapping[str, object],
                            ood_json: Sequence[Mapping[str, object]]) -> None:
    key = _scope_key(scope)
    ood_rows = [row for row in ood_json if _scope_key(row) == key]
    maximum_ood = _max_ood(ood_rows)
    fields = {
        "maximum_drift_half_label": scope["maximum_drift_half_label"],
        "maximum_drift_primary_component_index": scope["maximum_drift_primary_component_index"],
        "maximum_drift_primary_component_fingerprint": scope["maximum_drift_primary_component_fingerprint"],
        "maximum_drift_half_component_index": scope["maximum_drift_half_component_index"],
        "maximum_drift_half_component_fingerprint": scope["maximum_drift_half_component_fingerprint"],
        "maximum_ood_primary_component_index": maximum_ood["primary_component_index"],
        "maximum_ood_primary_component_fingerprint": maximum_ood["primary_component_fingerprint"],
    }
    for field, expected in fields.items():
        if type(expected) is int:
            _exact(_i(actual[field], f"diagnostic decoration {field}"), expected,
                   f"diagnostic decoration {field}")
        else:
            _exact(actual[field], str(expected), f"diagnostic decoration {field}")


def _compare_csv_nullable(actual: Sequence[Mapping[str, str]], expected: Sequence[Mapping[str, object]], label: str) -> None:
    if len(actual) != len(expected):
        _fail(f"{label} row count differs")
    for row, target in zip(actual, expected):
        for key, value in target.items():
            current = row[key]
            if value is None:
                _exact(current, "", f"{label}.{key}")
            elif type(value) is bool:
                _exact(_b(current, f"{label}.{key}"), value, f"{label}.{key}")
            elif type(value) is int:
                _exact(_i(current, f"{label}.{key}"), value, f"{label}.{key}")
            elif type(value) is float:
                _close(_f(current, f"{label}.{key}"), value, f"{label}.{key}")
            else:
                _exact(current, str(value), f"{label}.{key}")


def _classification(count: int, total: int) -> str:
    return "universal" if count == total else ("subset-only" if count == 0 else "mixed")


def _float_text(value: object) -> str:
    number = _f(value, "rendered float")
    return format(number, ".17g")


def _verify_fitted_reference(payload: Mapping[str, object], parent_files: Mapping[str, bytes]) -> dict[str, object]:
    name = "frozen_k4_cluster_diagnostics.csv"
    try:
        rows = list(csv.DictReader(io.StringIO(parent_files[name].decode("utf-8"))))
    except (KeyError, UnicodeDecodeError, csv.Error) as error:
        raise AuditError("parent fitted diagnostics are malformed") from error
    expected_headers = (
        "half_label", "primary_component_index", "half_component_index",
        "primary_component_fingerprint", "half_component_fingerprint", "sample_count",
        "exceedance_count", "euclidean_distance", "top_drift_features", "diagnostic_only",
    )
    if not rows or tuple(rows[0]) != expected_headers:
        _fail("parent fitted diagnostic schema differs")
    maximum = min(rows, key=lambda row: (
        -_f(row["euclidean_distance"], "parent fitted distance"), row["half_label"],
        _i(row["primary_component_index"], "parent fitted primary component"),
        _i(row["half_component_index"], "parent fitted half component"),
    ))
    expected = {
        "metric_name": "fitted_parameter_centroid_distance",
        "half_label": maximum["half_label"],
        "primary_component_index": _i(maximum["primary_component_index"], "fitted primary component"),
        "half_component_index": _i(maximum["half_component_index"], "fitted half component"),
        "primary_component_fingerprint": maximum["primary_component_fingerprint"],
        "half_component_fingerprint": maximum["half_component_fingerprint"],
        "distance": _f(maximum["euclidean_distance"], "fitted distance"),
        "top_five_drift_features": maximum["top_drift_features"].split("|")[:5],
    }
    reference = payload.get("fitted_parameter_reference")
    if not isinstance(reference, dict):
        _fail("JSON fitted-parameter reference is missing")
    _compare_objects([reference], [expected], "JSON fitted-parameter reference")
    return expected


def _verify_markdown(payload: Mapping[str, object], data: bytes,
                     fitted: Mapping[str, object]) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AuditError("Markdown is not UTF-8") from error
    required = (
        "# Frozen K4 Diagnosis Completion",
        "This diagnostic-only report completes the frozen K4 cause diagnosis.",
        "## Component 0 OOD (24/409)",
        "fitted_parameter_centroid_distance=",
        "full_sample_empirical_centroid_distance=",
        "offset_empirical_centroid_distance is reported for every 3-day and 7-day offset.",
        "No model gate was re-evaluated and no strategy mapping was performed.",
    )
    if any(sentence not in text for sentence in required):
        _fail("Markdown required claims do not reconcile")
    component = payload["component_zero_ood"]
    top_five_sentence = f"- Top five features: {', '.join(component['top_five_features'])}"
    if top_five_sentence not in text:
        _fail("Markdown Component 0 top-five claim differs")
    for family in component["family_rows"]:
        sentence = f"- family {family['family_name']}: contribution_ratio={_float_text(family['contribution_ratio'])}"
        if sentence not in text:
            _fail(f"Markdown family ratio differs: {family['family_name']}")
    for key in ("single_feature_concentration", "volatility_family_concentration",
                "recurrent_feature_dominance"):
        sentence = f"- {key}={'true' if component[key] else 'false'}"
        if sentence not in text:
            _fail(f"Markdown flag claim differs: {key}")
    fitted_sentence = f"- fitted_parameter_centroid_distance={_float_text(fitted['distance'])}"
    if fitted_sentence not in text:
        _fail("Markdown fitted-parameter value differs")
    full = payload["full_sample_empirical"]
    full_sentence = f"- full_sample_empirical_centroid_distance={_float_text(full['maximum_drift_distance'])}"
    if full_sentence not in text:
        _fail("Markdown full-sample empirical value differs")
    conclusions = payload["offset_consistency"]
    scope_map = {(scope["spacing_days"], scope["offset"]): scope
                 for scope in payload["offset_empirical"]}
    for conclusion in conclusions:
        scope = scope_map[(conclusion["spacing_days"], conclusion["offset"])]
        origin = scope["centroid_rows"][0]["offset_origin_anchor"]
        sentence = (
            f"- {conclusion['spacing_days']}-day offset={conclusion['offset']} origin={origin} "
            f"offset_empirical_centroid_distance: max={_float_text(scope['maximum_drift_distance'])} "
            f"half={scope['maximum_drift_half_label']} "
            f"primary_component={scope['maximum_drift_primary_component_index']} "
            f"primary_fingerprint={scope['maximum_drift_primary_component_fingerprint']} "
            f"half_component={scope['maximum_drift_half_component_index']} "
            f"half_fingerprint={scope['maximum_drift_half_component_fingerprint']} "
            f"maximum_ood_primary_component={conclusion['maximum_ood_primary_component_index']} "
            f"maximum_ood_fingerprint={conclusion['maximum_ood_primary_component_fingerprint']} "
            f"top_five={','.join(conclusion['top_five_drift_features'])}"
        )
        if sentence not in text:
            _fail(f"Markdown offset detail differs: {conclusion['spacing_days']}/{conclusion['offset']}")
    for spacing in (3, 7):
        rows = [row for row in conclusions if row["spacing_days"] == spacing]
        fields = (("drift component", "drift_component_matches_full_sample"),
                  ("OOD component", "ood_component_matches_full_sample"),
                  ("ordered top five", "ordered_top5_matches_full_sample"),
                  ("top-five set", "top5_set_matches_full_sample"))
        for label, field in fields:
            count = sum(bool(row[field]) for row in rows)
            sentence = f"- {spacing}-day {label}: {count}/{len(rows)} ({_classification(count, len(rows))})"
            if sentence not in text:
                _fail(f"Markdown offset claim differs: {spacing}-day {label}")
    if text.count("offset_empirical_centroid_distance:") != 10:
        _fail("Markdown must contain exactly ten offset detail claims")


def _verify_replay(parent_reproduction: Mapping[str, object], child: Mapping[str, object]) -> None:
    validation = child.get("replay_parent_validation")
    if (
        child.get("replay_parent_match_verified") is not True
        or not isinstance(validation, dict)
        or validation.get("match_verified") is not True
    ):
        _fail("replay-parent verification is not asserted")
    status = parent_reproduction.get("status")
    if not isinstance(status, dict):
        _fail("parent replay status is missing")
    temporal = status.get("temporal_half_refit_stability_reproduction")
    ood = status.get("primary_model_ood_reproduction")
    bits = parent_reproduction.get("metric_ieee_float_bits")
    if not isinstance(temporal, dict) or not isinstance(ood, dict) or not isinstance(bits, dict):
        _fail("parent failed metric receipts are missing")
    expected = {
        "status": status.get("status"),
        "temporal_expected_value": temporal.get("expected_value"),
        "temporal_reproduced_value": temporal.get("reproduced_value"),
        "ood_expected_value": ood.get("expected_value"),
        "ood_reproduced_value": ood.get("reproduced_value"),
        "ood_numerator": status.get("ood_exceedance_numerator"),
        "ood_denominator": status.get("ood_denominator"),
        "metric_ieee_float_bits": bits,
    }
    _exact(expected["status"], "reproduced", "pinned replay status")
    _exact((expected["ood_numerator"], expected["ood_denominator"]), (76, 1641),
           "pinned replay OOD counts")
    for name, pinned in (
        ("temporal_expected_value", _EXPECTED_TEMPORAL),
        ("temporal_reproduced_value", _EXPECTED_TEMPORAL),
        ("ood_expected_value", _EXPECTED_OOD_RATE),
        ("ood_reproduced_value", _EXPECTED_OOD_RATE),
    ):
        if _float_bits(float(expected[name])) != _float_bits(pinned):
            _fail(f"pinned replay value differs: {name}")
    for name in ("parent_receipt", "new_replay_receipt"):
        receipt = validation.get(name)
        if not isinstance(receipt, dict):
            _fail(f"{name} is missing")
        _exact(receipt, expected, name)
    expected_bits = {
        "maximum_distance_exceedance_rate": [
            _float_bits(float(expected["ood_expected_value"])),
            _float_bits(float(expected["ood_reproduced_value"]))],
        "maximum_matched_centroid_distance": [
            _float_bits(float(expected["temporal_expected_value"])),
            _float_bits(float(expected["temporal_reproduced_value"]))],
    }
    _exact(bits, expected_bits, "parent IEEE receipts")


def audit_frozen_k4_diagnosis_completion(*, parent_run: Path, completion_run: Path,
                                         model_attempt: Path, raw_kline_root: Path) -> Mapping[str, object]:
    parent_run = Path(parent_run).resolve(strict=True)
    completion_run = Path(completion_run).resolve(strict=True)
    if parent_run == completion_run or parent_run in completion_run.parents or completion_run in parent_run.parents:
        _fail("parent and child paths must be separate")
    parent_files = _directory(parent_run)
    parent_manifest = _read_manifest(parent_run, parent_files, child=False)
    child_files = _directory(completion_run, set(ARTIFACTS) | {MANIFEST})
    child_manifest = _read_manifest(completion_run, child_files, child=True)
    _exact(child_manifest.get("diagnostic_schema_version"), SCHEMA, "child schema")
    _exact(child_manifest.get("completion_scope"), SCOPE, "completion scope")
    _exact(child_manifest.get("parent_run_id"), parent_manifest["run_id"], "parent run ID")
    if child_manifest["run_id"] == parent_manifest["run_id"]:
        _fail("parent and child run IDs must differ")
    _exact(child_manifest.get("parent_manifest_sha256"), _sha256(parent_files[MANIFEST]),
           "parent manifest byte hash")
    _exact(child_manifest.get("thresholds"), THRESHOLDS, "fixed thresholds")
    _exact(child_manifest.get("replay_parent_match_verified"), True, "manifest replay receipt")
    implementation_files, implementation_hash = _implementation_receipt()
    _exact(child_manifest.get("implementation_file_sha256"), implementation_files,
           "producer implementation file hashes")
    _exact(child_manifest.get("implementation_sha256"), implementation_hash,
           "producer implementation hash")
    identity = {
        "diagnostic_schema_version": SCHEMA,
        "parent_run_id": parent_manifest["run_id"],
        "parent_manifest_sha256": _sha256(parent_files[MANIFEST]),
        "input_identity_sha256": child_manifest.get("input_identity_sha256"),
        "registry_schema_version": child_manifest.get("registry_schema_version"),
        "registry_sha256": child_manifest.get("registry_sha256"),
        "implementation_sha256": implementation_hash,
        "completion_scope": SCOPE, "replay_parent_match_verified": True,
        "thresholds": THRESHOLDS,
    }
    _exact(child_manifest["run_id"], _document_hash(identity), "deterministic child run ID")
    payload = _load_canonical_json(completion_run / COMPLETION_JSON)
    if not isinstance(payload, dict):
        _fail("completion JSON must be an object")
    for key in ("completion_scope", "implementation_file_sha256", "implementation_sha256",
                "replay_parent_match_verified"):
        _exact(payload.get(key), child_manifest.get(key), f"JSON/manifest {key}")
    _exact(payload.get("fixed_thresholds"), THRESHOLDS, "JSON fixed thresholds")
    _exact(payload.get("diagnostic_schema_version"), SCHEMA, "JSON schema")
    _exact(payload.get("diagnostic_only"), True, "JSON diagnostic-only policy")
    _exact(payload.get("primary_replacement_allowed"), False, "JSON replacement policy")
    provenance = payload.get("parent_provenance")
    if not isinstance(provenance, dict):
        _fail("JSON parent provenance is missing")
    _exact(provenance.get("parent_run_id"), parent_manifest["run_id"], "JSON parent ID")
    _exact(provenance.get("parent_manifest_sha256"), _sha256(parent_files[MANIFEST]),
           "JSON parent manifest hash")
    _exact(provenance.get("input_identity_sha256"), parent_manifest["input_identity_sha256"],
           "JSON parent input identity")
    registry_provenance = payload.get("registry_provenance")
    if not isinstance(registry_provenance, dict):
        _fail("JSON registry provenance is missing")
    _exact(registry_provenance.get("registry_schema_version"),
           child_manifest.get("registry_schema_version"), "JSON registry schema")
    _exact(registry_provenance.get("registry_sha256"), child_manifest.get("registry_sha256"),
           "JSON registry hash")
    parent_reproduction = _load_canonical_json(parent_run / PARENT_REPRODUCTION)
    if not isinstance(parent_reproduction, dict):
        _fail("parent reproduction must be an object")
    _verify_replay(parent_reproduction, payload)
    source = load_frozen_k4_diagnostic_source(Path(model_attempt), Path(raw_kline_root))
    try:
        identity_hash = _document_hash(source.identity.canonical_payload())
        _exact(identity_hash, parent_manifest.get("input_identity_sha256"), "source/parent identity")
        _exact(identity_hash, child_manifest.get("input_identity_sha256"), "source/child identity")
        independently_computed_registry = _registry_hash(tuple(source.primary_fit.feature_names))
        _exact(child_manifest.get("registry_schema_version"),
               THREE_DAY_CHART_FEATURE_SCHEMA_VERSION, "manifest registry schema")
        _exact(child_manifest.get("registry_sha256"), independently_computed_registry,
               "manifest independently recomputed registry hash")
        receipts, scaled = _verify_receipts(payload, source, parent_reproduction)
        flags = _verify_component_zero(payload, source, receipts, scaled, child_files)
        _verify_empirical(payload, source, receipts, scaled, child_files)
        fitted = _verify_fitted_reference(payload, parent_files)
        _verify_markdown(payload, child_files[REPORT], fitted)
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            close()
    return {
        "status": "verified", "parent_run_id": parent_manifest["run_id"],
        "completion_run_id": child_manifest["run_id"],
        "implementation_sha256": implementation_hash, "completion_scope": SCOPE,
        "replay_parent_match_verified": True, "checked_file_count": len(child_files),
        "component_0_scope": COMPONENT_SCOPE, "component_0_ood_numerator": 24,
        "component_0_ood_denominator": 409, "component_0_ood": "24/409",
        "registry_sha256": child_manifest["registry_sha256"], "checked_offsets": 10,
        "single_feature_concentration": flags[0],
        "volatility_family_concentration": flags[1],
        "recurrent_feature_dominance": flags[2],
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-run", type=Path, required=True)
    parser.add_argument("--completion-run", type=Path, required=True)
    parser.add_argument("--model-attempt", type=Path, required=True)
    parser.add_argument("--raw-kline-root", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        receipt = audit_frozen_k4_diagnosis_completion(
            parent_run=args.parent_run, completion_run=args.completion_run,
            model_attempt=args.model_attempt, raw_kline_root=args.raw_kline_root)
    except AuditError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(_canonical_bytes(dict(receipt)).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
