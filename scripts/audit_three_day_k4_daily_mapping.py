"""Independent verifier for the BTCUSDT three-day K4 daily-mapping publication.

The auditor deliberately consumes bytes and raw lineage again.  It does not call
the experiment orchestrator and never accepts a report's pass/fail summaries as
evidence.  Pure artifact parsers, candidate factories and accounting math are
reused so that the independently reconstructed values have exactly the same
domain semantics as the researched system.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Callable, Mapping, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.stats import chi2
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@dataclass(frozen=True)
class AuditInputs:
    report: Path
    markdown: Path
    model: Path
    mapping: Path
    evidence_rows_path: Path | None = None

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            value = getattr(self, field)
            object.__setattr__(self, field, None if value is None else Path(value))


def _canonical(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite decimal")
        return str(value.normalize()) if value else "0"
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("nonfinite float")
    return value


def canonical_json_bytes(value: object, *, newline: bool = True) -> bytes:
    encoded = json.dumps(
        _canonical(value), allow_nan=False, ensure_ascii=True,
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return encoded + (b"\n" if newline else b"")


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value, newline=False)).hexdigest()


def _read_canonical_json(path: Path, failures: list[str], label: str) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        failures.append(f"{label} could not be read: {error}")
        return {}
    return _read_canonical_json_bytes(raw, failures, label)


def _read_canonical_json_bytes(
    raw: bytes, failures: list[str], label: str,
) -> dict[str, object]:
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
        if not isinstance(value, dict):
            raise ValueError("top-level value is not an object")
        accepted = {canonical_json_bytes(value), canonical_json_bytes(value, newline=False)}
        if label == "report":
            accepted.add(
                (json.dumps(
                    value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
                ) + "\n").encode("utf-8")
            )
        if raw not in accepted:
            failures.append(f"{label} bytes are not canonical JSON")
        return value
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        failures.append(f"{label} could not be read: {error}")
        return {}


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _default_manifest() -> Mapping[str, object]:
    from scripts.chart_regime_strategy_mapping import (
        _freeze_boundary_payload,
        build_three_day_daily_candidate_manifest,
    )

    return _freeze_boundary_payload(
        build_three_day_daily_candidate_manifest(
            include_deferred=True, expected_count=459
        )
    )


def _same(expected: object, actual: object, failures: list[str], label: str) -> None:
    if _canonical(expected) != _canonical(actual):
        failures.append(f"{label} mismatch")


def _decimal(value: object, label: str, failures: list[str]) -> Decimal | None:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        failures.append(f"{label} is not a decimal")
        return None
    if not result.is_finite():
        failures.append(f"{label} is nonfinite")
        return None
    return result


def _audit_raw_inputs(
    model: Mapping[str, object], report: Mapping[str, object], failures: list[str]
) -> int:
    descriptors = model.get("source_provenance", ())
    if not isinstance(descriptors, list):
        failures.append("model source provenance is not a list")
        return 0
    report_sources = report.get("source_verification", {})
    if isinstance(report_sources, Mapping) and "raw_inputs" in report_sources:
        _same(descriptors, report_sources["raw_inputs"], failures, "raw source lineage")
    checked = 0
    for index, descriptor in enumerate(descriptors):
        if not isinstance(descriptor, Mapping):
            failures.append(f"raw input {index} descriptor is invalid")
            continue
        raw_path = descriptor.get("local_path")
        if raw_path is None:
            # Real artifacts bind immutable archive URL/member/hash.  The loader
            # may not preserve a local_path, so locate the downloaded basename
            # beneath the verified raw root without trusting a report summary.
            source_root = report_sources.get("raw_kline_root") if isinstance(report_sources, Mapping) else None
            url = descriptor.get("url") or descriptor.get("source_url")
            if source_root and isinstance(url, str):
                matches = tuple(Path(str(source_root)).rglob(Path(url).name))
                raw_path = str(matches[0]) if len(matches) == 1 else None
        if raw_path is None:
            failures.append(f"raw input {index} has no uniquely resolvable local file")
            continue
        path = Path(str(raw_path))
        try:
            raw = path.read_bytes()
        except OSError as error:
            failures.append(f"raw input {index} could not be read: {error}")
            continue
        reported_bytes = descriptor.get("bytes", descriptor.get("byte_count"))
        if reported_bytes is not None and reported_bytes != len(raw):
            failures.append(f"raw input {index} byte count mismatch")
        if hashlib.sha256(raw).hexdigest() != descriptor.get("sha256"):
            failures.append(f"raw input {index} SHA-256 mismatch")
        checked += 1
    expected_combined = model.get("source_combined_hash")
    if expected_combined is not None and expected_combined != _hash({"archives": descriptors}):
        failures.append("model source combined hash mismatch")
    return checked


def _audit_model(
    report_model: Mapping[str, object], file_model: Mapping[str, object], failures: list[str]
) -> object | None:
    _same(file_model, report_model, failures, "report/model artifact binding")
    supplied = file_model.get("artifact_hash")
    unhashed = {key: value for key, value in file_model.items() if key != "artifact_hash"}
    if supplied != _hash(unhashed):
        failures.append("model artifact hash mismatch")
    vectors = file_model.get("fit_input_vectors")
    if vectors is not None and file_model.get("fit_input_vector_hash") != _hash(vectors):
        failures.append("model fit-input feature-vector hash mismatch")
    components = file_model.get("component_fingerprints")
    if "component_fingerprint_hash" in file_model and file_model.get("component_fingerprint_hash") != _hash(components):
        failures.append("model component fingerprint hash mismatch")
    parsed = None
    if file_model.get("artifact_version") == "three-day-k4-model-v2":
        try:
            from src.infrastructure.regime.three_day_k4_model_artifact import ThreeDayK4ModelArtifact

            parsed = ThreeDayK4ModelArtifact.from_json(canonical_json_bytes(file_model, newline=False))
        except (TypeError, ValueError) as error:
            failures.append(f"model parameters/fingerprints are invalid: {error}")
    else:
        means, covariances, weights = (
            file_model.get("means"), file_model.get("covariances"), file_model.get("weights")
        )
        if not all(isinstance(item, list) and len(item) == 4 for item in (means, covariances)) or not isinstance(weights, list) or len(weights) != 4:
            failures.append("model parameters do not describe K4")
    return parsed


def _progress(message: str) -> None:
    print(f"audit: {message}", file=sys.stderr, flush=True)


class _LocalVerifiedDownloader:
    def __init__(self, descriptors: Sequence[Mapping[str, object]], raw_root: Path):
        self._by_url = {str(item.get("url") or item.get("source_url")): item for item in descriptors}
        self._raw_root = raw_root.resolve()

    def download(self, url: str, destination: Path, *, source=None, max_bytes=None):
        from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
            DownloadResult, validate_archive,
        )

        descriptor = self._by_url.get(url)
        if descriptor is None:
            raise ValueError(f"archive is absent from frozen provenance: {url}")
        path = Path(destination).resolve()
        if self._raw_root not in path.parents or not path.is_file():
            raise ValueError(f"verified local archive is missing: {path}")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        expected = descriptor.get("sha256")
        if digest != expected or descriptor.get("expected_sha256", expected) != digest:
            raise ValueError(f"verified local archive hash mismatch: {path.name}")
        reported = descriptor.get("bytes", descriptor.get("byte_count"))
        if reported != len(raw):
            raise ValueError(f"verified local archive byte count mismatch: {path.name}")
        member = validate_archive(path, source=source, expected_archive_filename=path.name)
        return DownloadResult("cached", path, digest, len(raw), digest, member)


def _load_cluster_fit_vectors(raw_root: Path, provenance=()):
    from datetime import timedelta
    from src.domain.regime import ThreeDayDailyResearchProfile
    from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
        load_three_day_feature_history,
    )

    interval = ThreeDayDailyResearchProfile().fold.cluster_fit
    return load_three_day_feature_history(
        symbol="BTCUSDT", start=interval.start_at - timedelta(days=3),
        end=interval.end_at, raw_root=raw_root,
        expected_anchor_count=(interval.end_at - interval.start_at).days,
        downloader=_LocalVerifiedDownloader(provenance, raw_root),
    )


_INDEPENDENT_GATE_THRESHOLDS = {
    "minimum_adjusted_rand_index": 0.8,
    "minimum_normalized_mutual_information": 0.8,
    "maximum_matched_centroid_distance": 0.5,
    "maximum_prevalence_drift": 0.2,
    "maximum_low_confidence_rate": 0.25,
    "maximum_distance_exceedance_rate": 0.02,
}


def _independent_vector_hash(vectors) -> str:
    from src.domain.regime import THREE_DAY_CHART_FEATURE_REGISTRY_V1

    return _hash({
        "schema_version": vectors[0].schema_version if vectors else None,
        "registry_names": [spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1],
        "vectors": [{
            "symbol": vector.symbol,
            "anchor_at": vector.anchor_at.isoformat(),
            "window_start_at": vector.window_start_at.isoformat(),
            "values": list(vector.values.items()),
        } for vector in vectors],
    })


def _independent_project_centroids(block_fit, primary) -> np.ndarray:
    if block_fit.feature_names != primary.feature_names:
        raise ValueError("independent centroid projection feature mismatch")
    raw = (
        np.asarray(block_fit.means, dtype=float)
        * np.asarray(block_fit.scales, dtype=float)
        + np.asarray(block_fit.medians, dtype=float)
    )
    clipped = np.clip(
        raw, np.asarray(primary.lower_bounds, dtype=float),
        np.asarray(primary.upper_bounds, dtype=float),
    )
    return (
        clipped - np.asarray(primary.medians, dtype=float)
    ) / np.asarray(primary.scales, dtype=float)


def _independent_technical_reason(error: BaseException) -> str:
    message = str(error).lower()
    for token, reason in (
        ("clipping bound", "invalid_clipping_bounds"),
        ("robust scaler", "invalid_scaler"),
        ("converg", "nonconvergence"),
        ("covariance", "invalid_covariance"),
        ("mahalanobis", "invalid_assignment_distance"),
        ("fingerprint", "invalid_component_fingerprint"),
        ("probabil", "invalid_assignment_probability"),
    ):
        if token in message:
            return reason
    return "model_fit_type_error" if isinstance(error, TypeError) else "model_fit_value_error"


def _independent_attempt_base(vectors, provenance, code_hash: str) -> dict[str, object]:
    from src.domain.regime import ThreeDayDailyResearchProfile

    profile = ThreeDayDailyResearchProfile()
    return {
        "profile_id": profile.profile_id,
        "model_config": {
            "model_type": "gmm", "cluster_count": 4,
            "covariance_type": "diag", "random_seed": profile.random_seed,
            "regularization": profile.regularization,
        },
        "fit_interval": {
            "start_at": profile.fold.cluster_fit.start_at.isoformat(),
            "end_at": profile.fold.cluster_fit.end_at.isoformat(),
        },
        "fit_input_anchor_count": len(vectors),
        "first_usable_anchor_at": vectors[0].anchor_at.isoformat(),
        "last_usable_anchor_at": vectors[-1].anchor_at.isoformat(),
        "fit_input_vector_hash": _independent_vector_hash(vectors),
        "source_provenance": list(provenance),
        "source_provenance_hash": _hash(list(provenance)),
        "code_provenance_hash": code_hash,
    }


def _independently_recompute_k4(vectors, provenance, code_hash: str):
    from src.domain.regime import (
        THREE_DAY_CHART_FEATURE_REGISTRY_V1, ThreeDayDailyResearchProfile,
    )
    from src.domain.regime.model import RegimeModelConfig
    from src.infrastructure.regime.sklearn_cluster_diagnostic import (
        SklearnClusterDiagnostic,
    )

    profile = ThreeDayDailyResearchProfile()
    config = RegimeModelConfig(
        "gmm", 4, profile.random_seed, "diag", profile.regularization
    )
    engine = SklearnClusterDiagnostic()
    base = _independent_attempt_base(vectors, provenance, code_hash)
    try:
        primary = engine.fit(config, vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
        assignments = engine.assign(primary, vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
        labels = tuple(item.fingerprint for item in assignments)
        represented = set(labels) == set(primary.fingerprints)
        midpoint = len(vectors) // 2
        blocks = (vectors[:midpoint], vectors[midpoint:])
        block_represented = all(
            set(item.fingerprint for item in engine.assign(
                primary, block, THREE_DAY_CHART_FEATURE_REGISTRY_V1
            )) == set(primary.fingerprints)
            for block in blocks
        )
        seed_scores = []
        for seed in (profile.random_seed + 1, profile.random_seed + 2):
            refit = engine.fit(
                replace(config, random_seed=seed), vectors,
                THREE_DAY_CHART_FEATURE_REGISTRY_V1,
                retained_feature_names=primary.feature_names,
            )
            compared = tuple(
                item.fingerprint for item in engine.assign(
                    refit, vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1
                )
            )
            seed_scores.append((
                float(adjusted_rand_score(labels, compared)),
                float(normalized_mutual_info_score(labels, compared)),
            ))
        minimum_ari = min(item[0] for item in seed_scores)
        minimum_nmi = min(item[1] for item in seed_scores)
        maximum_centroid_distance = 0.0
        block_shares = []
        for block in blocks:
            block_fit = engine.fit(
                config, block, THREE_DAY_CHART_FEATURE_REGISTRY_V1,
                retained_feature_names=primary.feature_names,
            )
            projected = _independent_project_centroids(block_fit, primary)
            distances = np.linalg.norm(
                np.asarray(primary.means)[:, None, :] - projected[None, :, :], axis=2
            )
            rows, columns = linear_sum_assignment(distances)
            maximum_centroid_distance = max(
                maximum_centroid_distance,
                max(float(distances[row, column]) for row, column in zip(rows, columns)),
            )
            mapping = {
                block_fit.fingerprints[column]: primary.fingerprints[row]
                for row, column in zip(rows, columns)
            }
            block_labels = tuple(
                mapping[item.fingerprint] for item in engine.assign(
                    block_fit, block, THREE_DAY_CHART_FEATURE_REGISTRY_V1
                )
            )
            block_shares.append({
                fingerprint: block_labels.count(fingerprint) / len(block_labels)
                for fingerprint in primary.fingerprints
            })
        maximum_prevalence_drift = max(
            abs(block_shares[0][fingerprint] - block_shares[1][fingerprint])
            for fingerprint in primary.fingerprints
        )
        low_confidence_rate = sum(
            item.dominant_probability < 0.65
            or item.dominant_probability - item.second_probability < 0.10
            for item in assignments
        ) / len(assignments)
        distance_threshold = float(chi2.ppf(0.995, df=len(primary.feature_names)))
        if any(item.distance is None or not math.isfinite(item.distance) for item in assignments):
            raise ValueError("diagonal GMM assignments require finite squared Mahalanobis distance")
        distance_exceedance_rate = sum(
            item.distance > distance_threshold for item in assignments
        ) / len(assignments)
        checks = {
            "all_components_represented": represented,
            "all_chronological_blocks_represented": block_represented,
            "minimum_adjusted_rand_index": minimum_ari >= 0.8,
            "minimum_normalized_mutual_information": minimum_nmi >= 0.8,
            "maximum_matched_centroid_distance": maximum_centroid_distance <= 0.5,
            "maximum_prevalence_drift": maximum_prevalence_drift <= 0.2,
            "maximum_low_confidence_rate": low_confidence_rate <= 0.25,
            "maximum_distance_exceedance_rate": distance_exceedance_rate <= 0.02,
        }
        passed = all(checks.values())
        gates = {
            "convergence_required": True, "converged": primary.converged,
            "iterations": primary.iterations, "lower_bound": primary.lower_bound,
            "finite_scaler_required": True,
            "finite_scaler": all(math.isfinite(value) for values in (
                primary.lower_bounds, primary.upper_bounds, primary.medians, primary.scales
            ) for value in values),
            "finite_model_parameters_required": True,
            "finite_model_parameters": all(math.isfinite(value) for values in (
                *primary.means, primary.weights, *primary.covariances
            ) for value in values),
            "positive_weights_required": True, "minimum_weight": min(primary.weights),
            "weight_sum_expected": 1.0, "weight_sum_tolerance": 1e-8,
            "weight_sum": math.fsum(primary.weights),
            "covariance_floor_threshold": profile.regularization,
            "minimum_covariance": min(value for row in primary.covariances for value in row),
            "component_count_expected": 4, "component_count": len(primary.fingerprints),
            "all_components_represented_required": True,
            "minimum_adjusted_rand_index": minimum_ari,
            "minimum_adjusted_rand_index_threshold": 0.8,
            "minimum_normalized_mutual_information": minimum_nmi,
            "minimum_normalized_mutual_information_threshold": 0.8,
            "maximum_matched_centroid_distance": maximum_centroid_distance,
            "maximum_matched_centroid_distance_threshold": 0.5,
            "maximum_prevalence_drift": maximum_prevalence_drift,
            "maximum_prevalence_drift_threshold": 0.2,
            "low_confidence_rate": low_confidence_rate,
            "maximum_low_confidence_rate_threshold": 0.25,
            "gmm_probability_threshold": 0.65, "gmm_margin_threshold": 0.10,
            "minimum_observed_dominant_probability": min(item.dominant_probability for item in assignments),
            "minimum_observed_probability_margin": min(item.dominant_probability - item.second_probability for item in assignments),
            "distance_threshold": distance_threshold,
            "distance_result": checks["maximum_distance_exceedance_rate"],
            "distance_threshold_policy": "maximum_chi_square_995_squared_mahalanobis",
            "distance_exceedance_rate": distance_exceedance_rate,
            "maximum_distance_exceedance_rate_threshold": 0.02,
            "feature_registry_version_expected": "three-day-chart-feature-registry-v1",
            "feature_registry_exact": True,
            "feature_family_cap_maximum_count": 5,
            "feature_family_cap_maximum_share": 0.5,
            "feature_family_observed_maximum_count": max(
                sum(spec.family == family and spec.name in primary.feature_names for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1)
                for family in {spec.family for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
            ),
            "feature_family_observed_maximum_share": max(
                sum(spec.family == family and spec.name in primary.feature_names for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1) / len(primary.feature_names)
                for family in {spec.family for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1}
            ),
            "feature_family_cap_passed": True,
            "all_components_represented": represented,
            "all_chronological_blocks_represented_required": True,
            "all_chronological_blocks_represented": block_represented,
            "nondegenerate_confidence": checks["maximum_low_confidence_rate"],
            "passed": passed,
            "all_components_represented_threshold": True,
            "all_chronological_blocks_represented_threshold": True,
            "maximum_low_confidence_rate": low_confidence_rate,
            "maximum_distance_exceedance_rate": distance_exceedance_rate,
        }
        gates.update({f"{name}_passed": value for name, value in checks.items()})
        failed = sorted(name for name, value in checks.items() if not value)
        if passed:
            from src.infrastructure.regime.three_day_k4_model_artifact import (
                ThreeDayK4ModelArtifact,
            )

            vector_hash = base["fit_input_vector_hash"]
            artifact = ThreeDayK4ModelArtifact.from_fit(
                primary,
                training_start_at=profile.fold.cluster_fit.start_at,
                training_end_at=profile.fold.cluster_fit.end_at,
                first_usable_anchor_at=vectors[0].anchor_at,
                last_usable_anchor_at=vectors[-1].anchor_at,
                usable_anchor_count=len(vectors),
                source_provenance=provenance,
                feature_history_hash=vector_hash,
                fit_input_vector_hash=vector_hash,
                code_provenance_hash=code_hash,
                model_gates=gates,
            )
            return artifact, None
        payload = {
            "schema_version": "three-day-k4-model-attempt-v1",
            "status": "failed-model-gates", **base,
            "feature_names": list(primary.feature_names),
            "model_parameters": {
                "converged": primary.converged, "iterations": primary.iterations,
                "lower_bound": primary.lower_bound,
                "lower_bounds": list(primary.lower_bounds),
                "upper_bounds": list(primary.upper_bounds),
                "medians": list(primary.medians), "scales": list(primary.scales),
                "weights": list(primary.weights),
                "means": [list(row) for row in primary.means],
                "covariances": [list(row) for row in primary.covariances],
                "component_fingerprints": list(primary.fingerprints),
            },
            "model_gates": gates, "failed_gate_names": failed,
        }
    except (TypeError, ValueError) as error:
        payload = {
            "schema_version": "three-day-k4-technical-failure-v1",
            "status": "technical_failure", **base,
            "technical_failure": {
                "stage": "fit_and_gate",
                "reason_code": _independent_technical_reason(error),
            },
        }
    return None, {**payload, "attempt_hash": _hash(payload)}


def _independently_recompute_model_attempt(vectors, provenance, code_hash: str):
    artifact, attempt = _independently_recompute_k4(vectors, provenance, code_hash)
    if artifact is not None or attempt is None:
        raise ValueError("independent K4 unexpectedly passed while auditing failure")
    return attempt


def _reconstruct_cluster_fit(
    report: Mapping[str, object], published_model: Mapping[str, object],
    failures: list[str],
):
    sources = report.get("source_verification", {})
    raw_root = sources.get("raw_kline_root") if isinstance(sources, Mapping) else None
    if not raw_root:
        failures.append("raw-refitted K4 requires verified raw_kline_root")
        return None
    try:
        _progress("reconstructing Cluster Fit vectors and deterministic K4")
        published_provenance = published_model.get("source_provenance", ())
        vectors, provenance = _load_cluster_fit_vectors(
            Path(str(raw_root)), published_provenance
        )
        chart_script = ROOT / "scripts" / "chart_regime_strategy_mapping.py"
        code_hash = hashlib.sha256(chart_script.read_bytes()).hexdigest()
        artifact, attempt = _independently_recompute_k4(
            vectors, provenance, code_hash
        )
        if artifact is None:
            reasons = attempt.get("failed_gate_names", ()) if isinstance(attempt, Mapping) else ()
            failures.append(f"independently raw-refitted K4 failed gates: {list(reasons)}")
            return None
        rebuilt = artifact.canonical_payload()
        _same(rebuilt, published_model, failures, "raw-refitted K4 artifact")
        return artifact
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        failures.append(f"raw-refitted K4 reconstruction failed: {error}")
        return None


def _reconstruct_failed_model_attempt(
    report: Mapping[str, object], published_model: Mapping[str, object],
    failures: list[str],
) -> Mapping[str, object] | None:
    sources = report.get("source_verification", {})
    raw_root = sources.get("raw_kline_root") if isinstance(sources, Mapping) else None
    if not raw_root:
        failures.append("failed-model raw refit requires verified raw_kline_root")
        return None
    try:
        _progress("reconstructing failed Cluster Fit model attempt")
        provenance = published_model.get("source_provenance", ())
        vectors, rebuilt_provenance = _load_cluster_fit_vectors(
            Path(str(raw_root)), provenance
        )
        code_hash = hashlib.sha256(
            (ROOT / "scripts" / "chart_regime_strategy_mapping.py").read_bytes()
        ).hexdigest()
        rebuilt = _independently_recompute_model_attempt(
            vectors, rebuilt_provenance, code_hash
        )
        _same(rebuilt, published_model, failures, "raw-refitted failed K4 model attempt")
        return rebuilt
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        failures.append(f"raw-refitted failed K4 reconstruction failed: {error}")
        return None


def _failed_markdown_bytes(report: Mapping[str, object]) -> bytes:
    attempt = report["model_attempt"]
    gates = attempt.get("model_gates", {})
    failed = attempt.get("failed_gate_names", ())
    lines = [
        "# BTCUSDT three-day K4 daily strategy mapping", "",
        "The frozen K4 model gates failed, so the experiment stopped at cash before candidate, evidence, mapping, or Test access.",
        "", f"- Status: `{report['status']}`",
        f"- Model attempt: `{attempt['attempt_hash']}`",
        f"- Cluster Fit anchors: `{attempt['fit_input_anchor_count']}`",
        f"- Failed gates: `{', '.join(str(item) for item in failed) or 'technical_failure'}`",
    ]
    if failed:
        lines.extend(("", "## Fixed model gates", "", "| Gate | Value | Threshold | Passed |", "|---|---:|---:|---:|"))
        for name in failed:
            lines.append(
                f"| `{name}` | {gates.get(name, 'missing')} | "
                f"{gates.get(f'{name}_threshold', 'missing')} | {gates.get(f'{name}_passed', False)} |"
            )
    else:
        technical = attempt["technical_failure"]
        lines.extend((
            "", "## Technical model failure", "",
            f"- Stage: `{technical['stage']}`",
            f"- Reason code: `{technical['reason_code']}`",
        ))
    lines.extend((
        "", "## Leakage and execution boundary", "",
        "- Candidate manifest frozen: `false`",
        "- Evidence ledger opened: `false`",
        "- Strategy mapping built: `false`",
        "- Untouched Test loaded: `false`",
        "- Resulting action: `cash-only`", "",
        "No strategy performance or backtest result exists for this stopped run.", "",
    ))
    return "\n".join(lines).encode("utf-8")


def _exact_failed_attempt_schema(model: Mapping[str, object], failures: list[str]) -> None:
    common = {
        "schema_version", "status", "profile_id", "model_config", "fit_interval",
        "fit_input_anchor_count", "first_usable_anchor_at", "last_usable_anchor_at",
        "fit_input_vector_hash", "source_provenance", "source_provenance_hash",
        "code_provenance_hash", "attempt_hash",
    }
    schema = model.get("schema_version")
    expected = (
        common | {"feature_names", "model_parameters", "model_gates", "failed_gate_names"}
        if schema == "three-day-k4-model-attempt-v1"
        else common | {"technical_failure"}
    )
    if set(model) != expected:
        failures.append("failed-model attempt exact schema mismatch")
    if set(model.get("model_config", {})) != {
        "model_type", "cluster_count", "covariance_type", "random_seed", "regularization"
    }:
        failures.append("failed-model config exact schema mismatch")
    if set(model.get("fit_interval", {})) != {"start_at", "end_at"}:
        failures.append("failed-model interval exact schema mismatch")
    if schema == "three-day-k4-model-attempt-v1":
        if set(model.get("model_parameters", {})) != {
            "converged", "iterations", "lower_bound", "lower_bounds", "upper_bounds",
            "medians", "scales", "weights", "means", "covariances",
            "component_fingerprints",
        }:
            failures.append("failed-model parameters exact schema mismatch")
    elif schema == "three-day-k4-technical-failure-v1":
        if set(model.get("technical_failure", {})) != {"stage", "reason_code"}:
            failures.append("technical failure exact schema mismatch")
        if "model_gates" in model or "model_parameters" in model:
            failures.append("technical failure must not contain fabricated model results")
    else:
        failures.append("failed-model attempt schema is invalid")
def _audit_failed_model_terminal(
    *, report: Mapping[str, object], model: Mapping[str, object],
    mapping: Mapping[str, object], inputs: AuditInputs,
    input_bytes: Mapping[str, bytes | None], failures: list[str],
) -> dict[str, object]:
    _exact_failed_attempt_schema(model, failures)
    if report.get("status") != "failed-model-cash":
        failures.append("failed-model terminal status is invalid")
    if report.get("test_comparisons") != {}:
        failures.append("failed-model terminal must not contain Test comparisons")
    attempt_hash = model.get("attempt_hash")
    unhashed_attempt = {key: value for key, value in model.items() if key != "attempt_hash"}
    if attempt_hash != _hash(unhashed_attempt):
        failures.append("failed-model attempt hash mismatch")
    _same(model, report.get("model_attempt"), failures, "report/model attempt binding")
    if report.get("model_attempt_hash") != attempt_hash:
        failures.append("report model attempt hash mismatch")
    schema = model.get("schema_version")
    is_gate = schema == "three-day-k4-model-attempt-v1"
    expected_terminal = "model_gate_failed" if is_gate else "model_technical_failure"
    expected_mapping_status = (
        "cash-only-model-gate-failure" if is_gate
        else "cash-only-model-technical-failure"
    )
    expected_status = "failed-model-gates" if is_gate else "technical_failure"
    if report.get("terminal_stage") != expected_terminal or model.get("status") != expected_status:
        failures.append("failed-model terminal/attempt status is invalid")
    technical = model.get("technical_failure", {})
    failed_names = (
        model.get("failed_gate_names") if is_gate
        else [technical.get("reason_code")] if isinstance(technical, Mapping) else []
    )
    gates = model.get("model_gates")
    if is_gate and (
        not isinstance(failed_names, list) or not failed_names
        or failed_names != sorted(set(failed_names))
        or not isinstance(gates, Mapping) or gates.get("passed") is not False
    ):
        failures.append("failed-model gate result is invalid")
    elif is_gate and any(
        name not in gates or f"{name}_threshold" not in gates
        or gates.get(f"{name}_passed") is not False
        for name in failed_names
    ):
        failures.append("failed-model gate metrics/thresholds are incomplete")
    if report.get("rejection_reasons") != failed_names:
        failures.append("failed-model rejection reasons mismatch")

    expected_access = {
        "candidate_manifest_frozen": False,
        "evidence_ledger_opened": False,
        "mapping_built": False,
        "test_loader_called": False,
    }
    if report.get("pipeline_access") != expected_access:
        failures.append("failed-model pipeline access proof is invalid")
    forbidden = {
        "candidate_manifest", "evidence", "strict_mapping", "final_mapping",
        "pre_test_freeze", "pre_test_freeze_hash", "global_fixed_baseline",
        "events", "trades", "equity_curve",
    }
    present = sorted(forbidden.intersection(report))
    if present:
        failures.append(f"failed-model report contains post-gate material: {present}")
    leakage = report.get("leakage_audit")
    if not isinstance(leakage, Mapping) or leakage.get("test_loader_called") is not False or leakage.get("first_test_read") is not None:
        failures.append("failed-model Test non-read proof is invalid")

    cash = report.get("cash_only_mapping")
    _same(mapping, cash, failures, "report/cash sentinel binding")
    mapping_hash = mapping.get("artifact_hash")
    unhashed_mapping = {key: value for key, value in mapping.items() if key != "artifact_hash"}
    if mapping_hash != _hash(unhashed_mapping):
        failures.append("cash sentinel artifact hash mismatch")
    if (
        set(mapping) != {
            "schema_version", "status", "model_attempt_hash",
            "rejection_reasons", "artifact_hash",
        }
        or mapping.get("schema_version") != "three-day-k4-cash-sentinel-v1"
        or mapping.get("status") != expected_mapping_status
        or mapping.get("model_attempt_hash") != attempt_hash
        or mapping.get("rejection_reasons") != failed_names
    ):
        failures.append("cash sentinel model-gate binding is invalid")

    source_verification = report.get("source_verification", {})
    if not isinstance(source_verification, Mapping) or set(source_verification) != {
        "raw_kline_root", "raw_inputs", "fit_input_vector_hash", "evidence_rows_path"
    }:
        failures.append("failed-model source verification exact schema mismatch")
        source_verification = {}
    expected_report = {
        "schema_version": "three-day-daily-k4-report-v1",
        "status": "failed-model-cash", "terminal_stage": expected_terminal,
        "rejection_reasons": failed_names,
        "source_verification": dict(source_verification),
        "model_attempt": dict(model), "model_attempt_hash": attempt_hash,
        "cash_only_mapping": dict(mapping),
        "pipeline_access": expected_access,
        "test_comparisons": {},
        "leakage_audit": {
            "test_loader_called": False, "first_test_read": None,
            "adoption_status": "inconclusive", "test_policy": "strict",
        },
    }
    report_payload = {key: value for key, value in report.items() if key != "publication"}
    _same(expected_report, report_payload, failures, "failed-model exact report payload")

    raw_count = _audit_raw_inputs(model, report, failures)
    rebuilt = _reconstruct_failed_model_attempt(report, model, failures)
    if rebuilt is None:
        failures.append("failed-model attempt could not be independently reconstructed")

    sources = report.get("source_verification", {})
    reported_base = sources.get("evidence_rows_path") if isinstance(sources, Mapping) else None
    ledger_base = inputs.evidence_rows_path or (Path(str(reported_base)) if reported_base else None)
    if ledger_base is None:
        failures.append("failed-model evidence ledger base is missing")
    else:
        for phase in ("mapping_fit", "validation"):
            if _phase_ledger_override(ledger_base, phase).exists():
                failures.append(f"failed-model terminal unexpectedly has {phase} evidence ledger")

    publication = report.get("publication")
    from scripts.chart_regime_strategy_mapping import (
        THREE_DAY_PUBLICATION_HASH_DEFINITION,
    )
    expected_keys = {
        "hash_definition", "report_payload_hash", "model_byte_hash",
        "mapping_byte_hash", "markdown_byte_hash",
    }
    if not isinstance(publication, Mapping) or set(publication) != expected_keys:
        failures.append("report publication output binding is invalid")
        publication = {}
    if publication.get("hash_definition") != THREE_DAY_PUBLICATION_HASH_DEFINITION:
        failures.append("report publication hash_definition is invalid")
    payload = {key: value for key, value in report.items() if key != "publication"}
    if publication.get("report_payload_hash") != _hash(payload):
        failures.append("report publication payload hash mismatch")
    for label in ("model", "mapping", "markdown"):
        raw = input_bytes.get(label)
        if raw is not None and publication.get(f"{label}_byte_hash") != hashlib.sha256(raw).hexdigest():
            failures.append(f"{label} report output hash mismatch")
    markdown_raw = input_bytes.get("markdown")
    if markdown_raw is not None and markdown_raw != _failed_markdown_bytes(expected_report):
        failures.append("failed-model Markdown independent rerender mismatch")

    return {
        "schema_version": "three-day-k4-daily-independent-audit-v1",
        "passed": not failures,
        "checked_counts": {
            "raw_inputs": raw_count, "candidates": 0, "evidence_rows": 0,
            "test_transitions": 0, "test_trades": 0,
        },
        "hashes": {
            "report_file_hash": hashlib.sha256(input_bytes["report"]).hexdigest() if input_bytes["report"] is not None else None,
            "model_file_hash": hashlib.sha256(input_bytes["model"]).hexdigest() if input_bytes["model"] is not None else None,
            "mapping_file_hash": hashlib.sha256(input_bytes["mapping"]).hexdigest() if input_bytes["mapping"] is not None else None,
            "markdown_file_hash": hashlib.sha256(input_bytes["markdown"]).hexdigest() if input_bytes["markdown"] is not None else None,
            "pre_test_freeze_hash": None,
            "model_artifact_hash": None,
            "mapping_artifact_hash": mapping_hash,
            "model_attempt_hash": attempt_hash,
        },
        "failures": failures,
    }
def _audit_manifest(
    report: Mapping[str, object], factory: Callable[[], Mapping[str, object]], failures: list[str]
) -> Mapping[str, object]:
    manifest = report.get("candidate_manifest", {})
    try:
        rebuilt = factory()
    except Exception as error:
        failures.append(f"candidate factory reconstruction failed: {error}")
        return {}
    _same(rebuilt, manifest, failures, "candidate manifest")
    if isinstance(manifest, Mapping):
        base = {key: value for key, value in manifest.items() if key != "manifest_hash"}
        if "manifest_hash" in manifest and manifest.get("manifest_hash") != _hash(base):
            # The production manifest uses its domain canonical identity rather
            # than this generic envelope; equality to a fresh factory remains
            # authoritative there.  Generic fixtures use the envelope hash.
            if rebuilt != manifest:
                failures.append("candidate manifest hash mismatch")
    return manifest if isinstance(manifest, Mapping) else {}


def _gaussian_assignment(model: Mapping[str, object], values: Sequence[object]) -> str | None:
    means = model.get("means")
    covariances = model.get("covariances")
    weights = model.get("weights")
    numeric = model.get("numeric_index_to_fingerprint")
    if not all(isinstance(item, list) for item in (means, covariances, weights)) or not isinstance(numeric, Mapping):
        return None
    try:
        x = [float(value) for value in values]
        scores = []
        for weight, mean, covariance in zip(weights, means, covariances):
            score = math.log(float(weight)) - 0.5 * sum(
                math.log(2 * math.pi * float(var)) + (value - float(mu)) ** 2 / float(var)
                for value, mu, var in zip(x, mean, covariance)
            )
            scores.append(score)
        return str(numeric[str(max(range(len(scores)), key=scores.__getitem__))])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _audit_trade(trade: Mapping[str, object], failures: list[str], prefix: str) -> Decimal | None:
    values = {
        name: _decimal(trade.get(name), f"{prefix} {name}", failures)
        for name in ("entry_price", "exit_price", "quantity", "gross_pnl", "fee_paid", "net_pnl")
    }
    if any(value is None for value in values.values()):
        return None
    entry, exit_price, quantity = values["entry_price"], values["exit_price"], values["quantity"]
    expected_gross = (
        (exit_price - entry) * quantity
        if trade.get("direction") == "long" else (entry - exit_price) * quantity
    )
    if values["gross_pnl"] != expected_gross:
        failures.append(f"{prefix} gross PnL mismatch")
    if values["net_pnl"] != values["gross_pnl"] - values["fee_paid"]:
        failures.append(f"{prefix} net PnL mismatch")
    return values["net_pnl"]


class _MemoryEvidenceLedger:
    def __init__(self, key_fields: Sequence[str]):
        self.key_fields = tuple(key_fields)
        self.rows: list[dict[str, object]] = []
        self._index: dict[tuple[object, ...], dict[str, object]] = {}

    def load(self):
        return self.rows

    def append(self, row: Mapping[str, object]):
        normalized = json.loads(canonical_json_bytes(dict(row), newline=False))
        key = tuple(normalized[field] for field in self.key_fields)
        existing = self._index.get(key)
        if existing is not None:
            if existing != normalized:
                raise ValueError("conflicting in-memory evidence key")
            return False
        self.rows.append(normalized)
        self._index[key] = normalized
        return True


def _phase_ledger_override(base: Path, phase: str) -> Path:
    label = phase.replace("_", "-")
    return base.with_name(f"{base.stem}-{label}{base.suffix or '.jsonl'}")


def _load_actual_ledger_rows(
    phase: str, bundle: Mapping[str, object], override: Path | None,
    failures: list[str],
) -> list[dict[str, object]]:
    from src.application.services.daily_strategy_evidence import (
        AppendOnlyEvidenceLedger, DAILY_EVIDENCE_KEY_FIELDS,
    )

    path = _phase_ledger_override(override, phase) if override is not None else Path(str(bundle.get("ledger_path", "")))
    if not str(path) or str(path) == ".":
        failures.append(f"{phase} evidence ledger path is missing")
        return []
    if not path.is_absolute():
        path = ROOT / path
    if not path.is_file():
        failures.append(f"{phase} evidence ledger is missing: {path}")
        return []
    try:
        actual_ledger_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if bundle.get("ledger_hash") != actual_ledger_hash:
            failures.append(f"{phase} evidence ledger hash mismatch")
        rows = list(AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS).load())
    except (OSError, TypeError, ValueError) as error:
        failures.append(f"{phase} evidence ledger parse failed: {error}")
        return []
    return rows


def _compare_phase_reconstruction(
    phase: str, bundle: Mapping[str, object], ledger_rows: Sequence[Mapping[str, object]],
    replay_rows: Sequence[Mapping[str, object]], assignments: Sequence[str],
    failures: list[str],
) -> None:
    report_rows = bundle.get("daily_evidence_rows", [])
    ledger_evidence = [
        row.get("evidence") for row in sorted(
            ledger_rows,
            key=lambda item: (str(item.get("outcome_start_at")), str(item.get("candidate_id"))),
        )
        if row.get("phase") == phase
    ]
    replay_evidence = sorted(
        replay_rows,
        key=lambda item: (
            str(item.get("outcome_interval", {}).get("start_at")),
            str(item.get("candidate_id")),
        ),
    )
    _same(ledger_evidence, report_rows, failures, f"{phase} ledger/report evidence")
    _same(replay_evidence, report_rows, failures, f"{phase} raw scheduler-replayed evidence")
    _same(list(assignments), bundle.get("component_assignments"), failures, f"{phase} replay assignments")


def _run_identity_from_payload(payload: Mapping[str, object]):
    from src.application.services.daily_strategy_evidence import DailyEvidenceRunIdentity

    interval = payload["phase_interval"]
    return DailyEvidenceRunIdentity(
        profile_id=str(payload["profile_id"]),
        feature_schema_version=str(payload["feature_schema_version"]),
        phase=str(payload["phase"]),
        phase_start_at=datetime.fromisoformat(str(interval["start_at"])),
        phase_end_at=datetime.fromisoformat(str(interval["end_at"])),
        model_artifact_hash=str(payload["model_artifact_hash"]),
        candidate_manifest_hash=str(payload["candidate_manifest_hash"]),
        candidate_universe_hash=str(payload["candidate_universe_hash"]),
        ordered_candidate_definition_hashes=tuple(
            (str(item[0]), str(item[1]))
            for item in payload["ordered_candidate_definition_hashes"]
        ),
        market_data_hash=str(payload["market_data_hash"]),
        feature_cache_hash=payload["feature_cache_hash"],
        feature_config_hash=payload["feature_config_hash"],
        feature_cache_schema_version=str(payload["feature_cache_schema_version"]),
        feature_provenance_hash=str(payload["feature_provenance_hash"]),
        feature_source_coverage_hash=str(payload["feature_source_coverage_hash"]),
        feature_unavailable_counts_hash=str(payload["feature_unavailable_counts_hash"]),
        engine_version=str(payload["engine_version"]), cost_model=payload["cost_model"],
        symbol=str(payload["symbol"]), timeframe=str(payload["timeframe"]),
        initial_equity=Decimal(str(payload["initial_equity"])),
        code_version=str(payload["code_version"]),
        evidence_schema_version=str(payload["evidence_schema_version"]),
    )


def _load_verified_minute_market(
    descriptors: Sequence[Mapping[str, object]], *, raw_root: Path,
    start_at: datetime, end_at: datetime,
):
    from scripts.chart_regime_strategy_mapping import _archive_candles
    from src.domain.market import MarketSnapshot

    root = raw_root.resolve()
    candles = []
    expected = start_at
    if not descriptors:
        raise ValueError("minute archive provenance is empty")
    for descriptor in descriptors:
        supplied = descriptor.get("path")
        if supplied:
            path = Path(str(supplied))
            if not path.is_absolute():
                path = ROOT / path
        else:
            url = descriptor.get("source_url") or descriptor.get("url")
            path = raw_root / "BTCUSDT" / Path(str(url)).name
        path = path.resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError(f"verified minute archive is missing: {path}")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != descriptor.get("sha256"):
            raise ValueError(f"verified minute archive hash mismatch: {path.name}")
        expected_hash = descriptor.get("expected_sha256")
        if expected_hash is not None and expected_hash != digest:
            raise ValueError(f"verified minute archive checksum mismatch: {path.name}")
        reported = descriptor.get("byte_count", descriptor.get("bytes", descriptor.get("size")))
        if reported != len(raw):
            raise ValueError(f"verified minute archive byte count mismatch: {path.name}")
        for candle in _archive_candles(
            path, "BTCUSDT", start_at=start_at, end_at=end_at
        ):
            if candle.opened_at != expected:
                raise ValueError("verified minute market contains a gap or overlap")
            candles.append(candle)
            expected = candle.closed_at
    if expected != end_at:
        raise ValueError("verified minute market does not cover the exact interval")
    return MarketSnapshot(tuple(candles))


def _replay_phase_from_raw(
    *, phase: str, bundle: Mapping[str, object], report: Mapping[str, object],
    model_artifact: object, manifest: object, ledger_override: Path | None,
    failures: list[str],
) -> list[Mapping[str, object]]:
    provider = None
    try:
        from datetime import timedelta
        from scripts.chart_regime_strategy_mapping import (
            _select_feature_cache,
            canonical_daily_evidence_replay_contract,
        )
        from scripts.scheduler_driven_scalping_backtest import required_warmup_candles
        from src.application.services.daily_strategy_evidence import (
            DAILY_EVIDENCE_KEY_FIELDS, run_daily_strategy_evidence,
        )
        from src.application.services.verified_market_timeline import (
            VerifiedPhaseMarketTimeline,
        )
        from src.domain.regime import ThreeDayDailyResearchProfile

        sources = report.get("source_verification", {})
        raw_root = sources.get("raw_kline_root") if isinstance(sources, Mapping) else None
        cache_root = sources.get("feature_cache_root") if isinstance(sources, Mapping) else None
        if not raw_root or not cache_root:
            raise ValueError("verified raw_kline_root and feature_cache_root are required")
        profile = ThreeDayDailyResearchProfile()
        interval = getattr(profile.fold, phase)
        calendar_rows = bundle.get("calendar_rows", [])
        days = [
            datetime.fromisoformat(str(item["outcome_start_at"]).replace("Z", "+00:00"))
            for item in calendar_rows
        ]
        if not days or any(not interval.start_at <= day < interval.end_at for day in days):
            raise ValueError("phase replay calendar is empty or outside the frozen interval")
        candidates = tuple(entry.candidate for entry in manifest.entries)
        warmup = required_warmup_candles(candidates, None)
        market_start = min(days) - timedelta(minutes=warmup)
        market_end = max(days) + timedelta(days=1)
        market = _load_verified_minute_market(
            bundle.get("archive_descriptors", ()), raw_root=Path(str(raw_root)),
            start_at=market_start, end_at=market_end,
        )
        verified_timeline = VerifiedPhaseMarketTimeline.from_market(market)
        provider, _ = _select_feature_cache(
            Path(str(cache_root)), required_start=market_start,
            required_end=market_end, verify_full_file=True,
        )
        identity_payload = bundle.get("run_identity")
        if not isinstance(identity_payload, Mapping):
            raise ValueError("phase run identity is missing")
        identity = _run_identity_from_payload(identity_payload)
        if identity.digest != bundle.get("run_identity_hash"):
            raise ValueError("phase run identity digest mismatch")
        if verified_timeline.market_data_hash != identity.market_data_hash:
            raise ValueError("verified phase market hash does not match run identity")
        daily_markets = tuple(
            verified_timeline.daily_slice(day, warmup_minutes=warmup) for day in days
        )
        vector_start = min(days) - timedelta(days=3)
        vector_end = max(days) + timedelta(days=1)
        assignments = [
            model_artifact.assign(vector).fingerprint
            for vector in _load_phase_vectors(
                phase, Path(str(raw_root)), bundle.get("vector_provenance", ()),
                start=vector_start, end=vector_end,
            )[0]
        ]
        actual_ledger = _load_actual_ledger_rows(phase, bundle, ledger_override, failures)
        memory = _MemoryEvidenceLedger(DAILY_EVIDENCE_KEY_FIELDS)
        replay_contract = canonical_daily_evidence_replay_contract()
        replayed = []
        for index, (day, component, daily_market) in enumerate(
            zip(days, assignments, daily_markets), start=1
        ):
            if index == 1 or index % 10 == 0 or index == len(days):
                _progress(f"{phase}: replaying day {index}/{len(days)} across 459 candidates")
            replayed.extend(run_daily_strategy_evidence(
                manifest=manifest, phase=phase, outcome_start_at=day,
                component_fingerprint=component, market=daily_market,
                market_feature_provider=provider, run_identity=identity,
                ledger=memory, replay_contract=replay_contract,
            ))
        replay_payloads = [item.canonical_payload() for item in replayed]
        _same(
            sorted(actual_ledger, key=lambda item: tuple(str(item.get(field)) for field in DAILY_EVIDENCE_KEY_FIELDS)),
            sorted(memory.rows, key=lambda item: tuple(str(item.get(field)) for field in DAILY_EVIDENCE_KEY_FIELDS)),
            failures, f"{phase} full ledger/raw scheduler replay",
        )
        _compare_phase_reconstruction(
            phase, bundle, actual_ledger, replay_payloads, assignments, failures
        )
        return replay_payloads
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        failures.append(f"{phase} independent scheduler evidence replay failed: {error}")
        return []
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def _load_phase_vectors(
    phase: str, raw_root: Path, provenance=(), *,
    start: datetime | None = None, end: datetime | None = None,
):
    from datetime import timedelta
    from src.domain.regime import ThreeDayDailyResearchProfile
    from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
        load_three_day_feature_history,
    )

    interval = getattr(ThreeDayDailyResearchProfile().fold, phase)
    requested_start = start or interval.start_at - timedelta(days=3)
    requested_end = end or interval.end_at
    anchor_count = int((requested_end - requested_start - timedelta(days=3)).days)
    return load_three_day_feature_history(
        symbol="BTCUSDT", start=requested_start,
        end=requested_end, raw_root=raw_root,
        expected_anchor_count=anchor_count,
        downloader=_LocalVerifiedDownloader(provenance, raw_root),
    )


def _audit_evidence(
    report: Mapping[str, object], model: Mapping[str, object], parsed_model: object | None,
    failures: list[str]
) -> tuple[int, list[Mapping[str, object]]]:
    evidence_root = report.get("evidence", {})
    if not isinstance(evidence_root, Mapping):
        failures.append("evidence root is invalid")
        return 0, []
    checked = 0
    all_rows: list[Mapping[str, object]] = []
    for phase, bundle in sorted(evidence_root.items()):
        if not isinstance(bundle, Mapping):
            failures.append(f"{phase} evidence bundle is invalid")
            continue
        assignments = bundle.get("component_assignments", [])
        if bundle.get("assignment_hash") != _hash(assignments):
            failures.append(f"{phase} assignment hash mismatch")
        archives = bundle.get("archive_descriptors", [])
        if "archive_descriptor_hash" in bundle and bundle.get("archive_descriptor_hash") != _hash(archives):
            failures.append(f"{phase} archive descriptor hash mismatch")
        for field in (
            "feature_provenance", "feature_source_coverage", "feature_unavailable_counts",
            "vector_provenance",
        ):
            hash_field = field + "_hash"
            if field in bundle and hash_field in bundle and bundle.get(hash_field) != _hash(bundle.get(field)):
                failures.append(f"{phase} {field.replace('_', ' ')} hash mismatch")
        identity = bundle.get("run_identity")
        if isinstance(identity, Mapping) and bundle.get("run_identity_hash") != _hash(identity):
            failures.append(f"{phase} evidence run identity hash mismatch")
        rows = bundle.get("daily_evidence_rows", [])
        if "evidence_hash" in bundle and bundle.get("evidence_hash") != _hash(rows):
            failures.append(f"{phase} evidence row hash mismatch")
        features = bundle.get("assignment_features")
        if isinstance(features, list) and isinstance(assignments, list):
            recomputed = [_gaussian_assignment(model, values) for values in features]
            if recomputed != assignments:
                failures.append(f"{phase} component assignment mismatch")
        elif parsed_model is not None and isinstance(assignments, list):
            calendar_for_reload = bundle.get("calendar_rows", [])
            source_verification = report.get("source_verification", {})
            raw_root = (
                source_verification.get("raw_kline_root")
                if isinstance(source_verification, Mapping) else None
            )
            try:
                if not raw_root or not isinstance(calendar_for_reload, list) or not calendar_for_reload:
                    raise ValueError("raw root or calendar is absent")
                days = [
                    datetime.fromisoformat(str(item["outcome_start_at"]).replace("Z", "+00:00"))
                    for item in calendar_for_reload if isinstance(item, Mapping)
                ]
                from datetime import timedelta
                vectors, provenance = _load_phase_vectors(
                    str(phase), Path(str(raw_root)), bundle.get("vector_provenance", ()),
                    start=min(days) - timedelta(days=3), end=max(days) + timedelta(days=1),
                )
                recomputed = [parsed_model.assign(vector).fingerprint for vector in vectors]
                if recomputed != assignments:
                    failures.append(f"{phase} raw feature/model assignment mismatch")
                if "vector_provenance" in bundle:
                    _same(list(provenance), bundle.get("vector_provenance"), failures, f"{phase} vector provenance")
                if "vector_provenance_hash" in bundle and bundle.get("vector_provenance_hash") != _hash(list(provenance)):
                    failures.append(f"{phase} vector provenance hash mismatch")
            except (OSError, TypeError, ValueError) as error:
                failures.append(f"{phase} raw feature assignment reconstruction failed: {error}")
        calendar_rows = bundle.get("calendar_rows", [])
        if isinstance(calendar_rows, list) and isinstance(assignments, list):
            labels = [item.get("component_fingerprint") for item in calendar_rows if isinstance(item, Mapping)]
            if labels != assignments:
                failures.append(f"{phase} calendar/assignment mismatch")
        if not isinstance(rows, list):
            failures.append(f"{phase} evidence rows are invalid")
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                failures.append(f"{phase} evidence row {index} is invalid")
                continue
            all_rows.append(row)
            if row.get("availability_status") == "unavailable":
                checked += 1
                continue
            initial = _decimal(row.get("initial_equity"), f"{phase} evidence initial equity", failures)
            final = _decimal(row.get("final_equity"), f"{phase} evidence final equity", failures)
            net = _decimal(row.get("net_pnl"), f"{phase} evidence net PnL", failures)
            ratio = _decimal(row.get("net_return_ratio"), f"{phase} evidence return", failures)
            trades = row.get("trades")
            if isinstance(trades, list):
                pnls = [_audit_trade(item, failures, f"{phase} evidence trade") for item in trades if isinstance(item, Mapping)]
                if None not in pnls and net is not None and sum(pnls, Decimal(0)) != net:
                    failures.append(f"{phase} evidence trade total mismatch")
                if row.get("closed_trade_count") != len(trades):
                    failures.append(f"{phase} evidence trade count mismatch")
            elif isinstance(row.get("trade_pnls"), list):
                pnls = [_decimal(item, f"{phase} evidence trade PnL", failures) for item in row["trade_pnls"]]
                if None not in pnls and net is not None and sum(pnls, Decimal(0)) != net:
                    failures.append(f"{phase} evidence trade PnL total mismatch")
            if None not in (initial, final, net, ratio) and initial != 0:
                if final - initial != net or net / initial != ratio:
                    failures.append(f"{phase} evidence return/accounting mismatch")
            checked += 1
    return checked, all_rows


def _winner_key(item: Mapping[str, object]) -> tuple[object, ...]:
    def neg(name: str) -> Decimal:
        return -Decimal(str(item.get(name, "0")))

    return (
        neg("corrected_lower_bound_ratio"), neg("return_without_best_episode_ratio"),
        neg("expected_shortfall_10_ratio"), Decimal(str(item.get("maximum_drawdown_ratio", "0"))),
        neg("median_daily_return_ratio"), str(item.get("candidate_id")),
    )


def _audit_mapping(
    report: Mapping[str, object], mapping_file: Mapping[str, object],
    manifest: Mapping[str, object], model: Mapping[str, object], failures: list[str],
    *, independent_evidence_rows: Sequence[Mapping[str, object]] | None = None,
) -> object | None:
    mapping = report.get("strict_mapping", {})
    report_mapping = dict(mapping) if isinstance(mapping, Mapping) else {}
    companion_without_hash = {
        key: value for key, value in mapping_file.items() if key != "artifact_hash"
    }
    if "artifact_hash" in report_mapping:
        _same(mapping_file, report_mapping, failures, "report/mapping artifact binding")
    else:
        _same(companion_without_hash, report_mapping, failures, "report/mapping artifact binding")
    supplied = mapping_file.get("artifact_hash")
    unhashed = {key: value for key, value in mapping_file.items() if key != "artifact_hash"}
    if supplied != _hash(unhashed):
        # Production mapping hash is computed by its typed domain artifact and
        # is also independently checked below when reconstruction is possible.
        if mapping_file.get("artifact_version") != "daily-strategy-mapping-v1":
            failures.append("mapping artifact hash mismatch")
    if report.get("strict_mapping_artifact_hash") != supplied:
        failures.append("strict mapping report hash mismatch")
    if mapping_file.get("model_artifact_hash") != model.get("artifact_hash"):
        failures.append("mapping/model identity mismatch")
    if mapping_file.get("candidate_universe_hash") != manifest.get("candidate_universe_hash"):
        failures.append("mapping/candidate universe mismatch")
    candidate_hashes = mapping_file.get("candidate_hashes", {})
    assessments = mapping_file.get("candidate_assessments", [])
    entries = mapping_file.get("entries", [])
    if not isinstance(assessments, list) or not isinstance(entries, list):
        failures.append("mapping assessments/entries are invalid")
        return None
    grouped: dict[str, list[Mapping[str, object]]] = {}
    for item in assessments:
        if not isinstance(item, Mapping):
            failures.append("mapping assessment is invalid")
            continue
        candidate = item.get("candidate_id")
        if not isinstance(candidate_hashes, Mapping) or item.get("candidate_hash") != candidate_hashes.get(candidate):
            failures.append("mapping assessment candidate hash mismatch")
        grouped.setdefault(str(item.get("component_fingerprint")), []).append(item)
    for entry in entries:
        if not isinstance(entry, Mapping):
            failures.append("mapping entry is invalid")
            continue
        eligible = [item for item in grouped.get(str(entry.get("component_fingerprint")), []) if item.get("eligible") is True]
        expected = min(eligible, key=_winner_key).get("candidate_id") if eligible else None
        expected_decision = "strategy" if expected is not None else "cash"
        if entry.get("decision") != expected_decision or entry.get("strategy_candidate_id") != expected:
            failures.append("mapping cash/winner decision mismatch")
    if mapping_file.get("artifact_version") != "daily-strategy-mapping-v1":
        return None
    try:
        from src.application.services.daily_strategy_evidence import _evidence_from_payload
        from src.application.usecases.regime.build_daily_strategy_mapping_usecase import (
            BuildDailyStrategyMappingCommand,
            BuildDailyStrategyMappingUseCase,
        )
        from src.domain.regime.temporal import UtcInterval

        evidence_root = report.get("evidence", {})
        source_rows = (
            tuple(independent_evidence_rows)
            if independent_evidence_rows is not None
            else tuple(
                row for phase in sorted(evidence_root)
                for row in evidence_root[phase].get("daily_evidence_rows", [])
            )
        )
        evidence_rows = tuple(_evidence_from_payload(row) for row in source_rows)
        statistical = mapping_file.get("statistical_calendar", [])
        calendar = tuple(
            datetime.fromisoformat(str(item["day"]).replace("Z", "+00:00"))
            for item in statistical
        )
        evidence_intervals = tuple(
            (
                str(item["role"]),
                UtcInterval(
                    datetime.fromisoformat(str(item["start_at"]).replace("Z", "+00:00")),
                    datetime.fromisoformat(str(item["end_at"]).replace("Z", "+00:00")),
                ),
            )
            for item in mapping_file.get("evidence_intervals", [])
        )
        ledger_identities = tuple(
            (str(item["phase"]), str(item["ledger_hash"]), str(item["run_identity_hash"]))
            for item in mapping_file.get("evidence_ledger_identities", [])
        )
        ordered_manifest = tuple(
            (str(item[0]), str(item[1]))
            for item in manifest.get("ordered_definition_hashes", [])
        )
        command = BuildDailyStrategyMappingCommand(
            model_artifact_hash=str(model["artifact_hash"]),
            candidate_manifest=ordered_manifest,
            frozen_component_fingerprints=tuple(str(item) for item in model["component_fingerprints"]),
            calendar=calendar,
            component_assignments=tuple(item.get("component_fingerprint") for item in statistical),
            evidence_rows=evidence_rows,
            calendar_roles=tuple(str(item["role"]) for item in statistical),
            evidence_intervals=evidence_intervals,
            evidence_ledger_identities=ledger_identities,
        )
        rebuilt = BuildDailyStrategyMappingUseCase().execute(command).artifact
        _same(rebuilt.canonical_payload(), companion_without_hash, failures, "recomputed corrected-LCB mapping")
        from src.domain.regime import daily_mapping_artifact_hash

        if daily_mapping_artifact_hash(rebuilt) != supplied:
            failures.append("recomputed mapping artifact hash mismatch")
        return rebuilt
    except (KeyError, TypeError, ValueError) as error:
        failures.append(f"mapping statistics could not be independently reconstructed: {error}")
        return None


def _timestamp_strings(value: object, path: tuple[str, ...] = ()):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _timestamp_strings(item, (*path, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _timestamp_strings(item, (*path, str(index)))
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        yield path, parsed.astimezone(timezone.utc)


def _audit_freeze(report: Mapping[str, object], failures: list[str]) -> None:
    payload = report.get("pre_test_freeze_payload")
    if not isinstance(payload, Mapping):
        # Published production reports expose every constituent. Reconstruct
        # the exact typed freeze envelope independently.
        profile = report.get("profile", {})
        pretest_profile = dict(profile) if isinstance(profile, Mapping) else {}
        if isinstance(pretest_profile.get("fold"), Mapping):
            pretest_profile["fold"] = {
                key: value for key, value in pretest_profile["fold"].items() if key != "test"
            }
        freeze_mapping = dict(report.get("strict_mapping", {})) if isinstance(report.get("strict_mapping"), Mapping) else {}
        freeze_mapping["artifact_hash"] = report.get("strict_mapping_artifact_hash")
        payload = {
            "freeze_schema_version": "three-day-pre-test-freeze-v1",
            "report_schema_version": "three-day-daily-k4-report-v1",
            "model": report.get("model_artifact"),
            "candidate_manifest": report.get("candidate_manifest"),
            "evidence": {
                "mapping": report.get("evidence", {}).get("mapping_fit") if isinstance(report.get("evidence"), Mapping) else None,
                "validation": report.get("evidence", {}).get("validation") if isinstance(report.get("evidence"), Mapping) else None,
            },
            "mapping": freeze_mapping,
            "global_fixed_baseline": report.get("global_fixed_baseline"),
            "profile": pretest_profile,
            "chronology": pretest_profile.get("fold"),
        }
    if report.get("pre_test_freeze_hash") != _hash(payload):
        failures.append("pre-Test freeze hash/identity mismatch")
    boundary = datetime(2026, 4, 4, tzinfo=timezone.utc)
    for path, timestamp in _timestamp_strings(payload):
        canonical_interval_metadata = path in {
            ("model", "profile", "fold", "test", "start_at"),
            ("model", "profile", "fold", "test", "end_at"),
            ("mapping", "research_profile", "fold", "test", "start_at"),
            ("mapping", "research_profile", "fold", "test", "end_at"),
        }
        if canonical_interval_metadata:
            continue
        if timestamp >= boundary:
            failures.append("Test timestamp appears in pre-Test lineage at " + ".".join(path))
            break
    provenance = report.get("test_provenance", {})
    if isinstance(provenance, Mapping) and provenance.get("pre_test_freeze_hash") != report.get("pre_test_freeze_hash"):
        failures.append("Test provenance does not bind the pre-Test freeze")


def _drawdown(equities: Sequence[Decimal]) -> Decimal:
    if not equities:
        return Decimal(0)
    peak = equities[0]
    result = Decimal(0)
    for value in equities:
        peak = max(peak, value)
        if peak > 0:
            result = max(result, (peak - value) / peak)
    return result


def _audit_comparison(label: str, row: Mapping[str, object], failures: list[str]) -> tuple[int, int]:
    trades = row.get("trades", [])
    transition_count = 0
    if isinstance(row.get("transitions"), list):
        transitions = row["transitions"]
        transition_count = len(transitions)
        if row.get("transition_hash") != _hash(transitions):
            failures.append(f"{label} Test transition hash mismatch")
    elif isinstance(row.get("selection_events"), list):
        events = row["selection_events"]
        transition_types = {
            "cluster_transition": "component_transition_count",
            "strategy_transition": "strategy_transition_count",
            "cash_transition": "cash_transition_count",
        }
        previous = None
        for event in events:
            if not isinstance(event, Mapping):
                failures.append(f"{label} Test selection event is invalid")
                continue
            timestamp = event.get("boundary_at")
            if previous is not None and str(timestamp) < str(previous):
                failures.append(f"{label} Test selection events are not chronological")
            previous = timestamp
        for event_type, count_field in transition_types.items():
            reconstructed = sum(
                isinstance(event, Mapping) and event.get("type") == event_type
                for event in events
            )
            if row.get(count_field) != reconstructed:
                failures.append(f"{label} Test {count_field} mismatch")
            transition_count += reconstructed
    trade_count = len(trades) if isinstance(trades, list) else 0
    if isinstance(trades, list):
        if "trade_hash" in row and row.get("trade_hash") != _hash(trades):
            failures.append(f"{label} Test trade hash mismatch")
        if row.get("trade_count") != trade_count:
            failures.append(f"{label} Test trade count mismatch")
        for index, trade in enumerate(trades):
            if isinstance(trade, Mapping):
                _audit_trade(trade, failures, f"{label} Test trade {index}")
            else:
                failures.append(f"{label} Test trade {index} is invalid")
        opposite = sum(
            isinstance(trade, Mapping) and trade.get("exit_reason") == "active_strategy_opposite_signal"
            for trade in trades
        )
        if "active_strategy_opposite_exit_count" in row and row.get("active_strategy_opposite_exit_count") != opposite:
            failures.append(f"{label} active-strategy opposite-exit mismatch")
    curve = row.get("equity_curve", [])
    if isinstance(curve, list):
        if "equity_curve_hash" in row and row.get("equity_curve_hash") != _hash(curve):
            failures.append(f"{label} Test equity-curve hash mismatch")
        equities = []
        for point in curve:
            value = point.get("equity") if isinstance(point, Mapping) else point
            parsed = _decimal(value, f"{label} Test equity", failures)
            if parsed is not None:
                equities.append(parsed)
        initial = _decimal(row.get("initial_equity"), f"{label} initial equity", failures)
        final = _decimal(row.get("final_equity"), f"{label} final equity", failures)
        returned = _decimal(row.get("return_ratio"), f"{label} return", failures)
        reported_drawdown = _decimal(
            row.get("portfolio_max_drawdown_ratio", row.get("max_drawdown_ratio")),
            f"{label} drawdown", failures,
        )
        if initial is not None and final is not None and returned is not None and initial != 0:
            if (final - initial) / initial != returned:
                failures.append(f"{label} Test return/equity mismatch")
        if initial is not None and (not equities or equities[0] != initial):
            equities.insert(0, initial)
        if reported_drawdown is not None and equities and _drawdown(equities) != reported_drawdown:
            failures.append(f"{label} Test equity/MDD mismatch")
    return trade_count, transition_count


def _audit_test_and_baselines(
    report: Mapping[str, object], failures: list[str],
    *, manifest: Mapping[str, object], evidence_rows: Sequence[Mapping[str, object]],
) -> tuple[int, int]:
    comparisons = report.get("test_comparisons", {})
    if not isinstance(comparisons, Mapping):
        failures.append("Test comparisons are invalid")
        return 0, 0
    trades = transitions = 0
    for label, row in sorted(comparisons.items()):
        if not isinstance(row, Mapping):
            failures.append(f"{label} comparison is invalid")
            continue
        count, transition_count = _audit_comparison(str(label), row, failures)
        trades += count
        transitions += transition_count
    baseline = report.get("global_fixed_baseline", {})
    manifest = report.get("candidate_manifest", {})
    ids = manifest.get("candidate_ids", []) if isinstance(manifest, Mapping) else []
    if isinstance(baseline, Mapping):
        decision, candidate = baseline.get("decision"), baseline.get("candidate_id")
        if decision == "strategy" and candidate not in ids:
            failures.append("global fixed baseline candidate is outside frozen manifest")
        if decision == "cash" and candidate is not None:
            failures.append("global fixed cash baseline contains a candidate")
        assessments = baseline.get("assessments")
        if isinstance(assessments, list):
            eligible = [item for item in assessments if isinstance(item, Mapping) and item.get("eligible") is True]
            expected = min(eligible, key=_winner_key).get("candidate_id") if eligible else None
            if candidate != expected:
                failures.append("global fixed baseline winner mismatch")
        if assessments is not None:
            try:
                from src.application.services.daily_strategy_evidence import _evidence_from_payload
                from src.application.usecases.regime.build_daily_strategy_mapping_usecase import (
                    select_global_fixed_daily_candidate,
                )

                rebuilt = select_global_fixed_daily_candidate(
                    candidate_manifest=tuple(
                        (str(item[0]), str(item[1]))
                        for item in manifest.get("ordered_definition_hashes", [])
                    ),
                    evidence_rows=tuple(_evidence_from_payload(item) for item in evidence_rows),
                )
                _same(rebuilt.canonical_payload(), baseline, failures, "recomputed global fixed baseline")
            except (KeyError, TypeError, ValueError) as error:
                failures.append(f"global fixed baseline could not be reconstructed: {error}")
    else:
        failures.append("global fixed baseline is invalid")
    return trades, transitions


def _replay_untouched_test(
    report: Mapping[str, object], parsed_model: object, rebuilt_mapping: object,
    failures: list[str],
) -> None:
    """Re-run all six Test comparisons through engines, not report helpers."""
    sources = report.get("source_verification", {})
    if not isinstance(sources, Mapping) or not sources.get("raw_kline_root"):
        failures.append("untouched Test replay requires verified raw_kline_root")
        return
    provider = None
    try:
        from datetime import timedelta
        from scripts.chart_regime_strategy_mapping import (
            _manual_router_candidate,
            _select_feature_cache,
            build_three_day_daily_candidate_manifest,
            default_candidate,
        )
        from scripts.scheduler_driven_scalping_backtest import (
            PositionExitPolicy,
            run_scheduler_driven_backtest,
            run_scheduler_driven_daily_regime_backtest,
        )
        from src.domain.regime import ThreeDayDailyResearchProfile

        profile = ThreeDayDailyResearchProfile()
        interval = profile.fold.test
        context_start = interval.start_at - timedelta(days=3)
        test_provenance = report.get("test_provenance", {})
        archives = test_provenance.get("archives", ()) if isinstance(test_provenance, Mapping) else ()
        market = _load_verified_minute_market(
            archives, raw_root=Path(str(sources["raw_kline_root"])),
            start_at=context_start, end_at=interval.end_at,
        )
        provider, _ = _select_feature_cache(
            sources.get("feature_cache_root"), required_start=context_start,
            required_end=interval.end_at, verify_full_file=True,
        )
        manifest = build_three_day_daily_candidate_manifest(
            include_deferred=True, expected_count=459
        )
        candidates = tuple(entry.candidate for entry in manifest.entries)
        by_id = {item.candidate_id: item for item in candidates}
        initial = Decimal("10000")

        def static(candidate):
            return run_scheduler_driven_backtest(
                market, context_start_at=context_start, start_at=interval.start_at,
                end_at=interval.end_at, candidate=candidate,
                market_feature_provider=provider, initial_equity=initial,
                include_trade_details=True, force_close_at_end=True,
                include_deferred=True,
            )

        def dynamic(policy):
            return run_scheduler_driven_daily_regime_backtest(
                market, start_at=interval.start_at, end_at=interval.end_at,
                candidates=candidates, model_artifact=parsed_model,
                mapping_artifact=rebuilt_mapping, position_exit_policy=policy,
                candidate_manifest=manifest, market_feature_provider=provider,
                initial_equity=initial, include_deferred=True, force_close_at_end=True,
            )

        baseline = report.get("global_fixed_baseline", {})
        global_id = baseline.get("candidate_id") if isinstance(baseline, Mapping) else None
        cash = {
            "status": "completed", "candidate_id": "cash",
            "initial_equity": str(initial), "final_equity": str(initial),
            "return_ratio": "0", "max_drawdown_ratio": "0", "trade_count": 0,
            "trades": [], "equity_curve": [],
        }
        rebuilt = {
            "cash": cash,
            "current_adopted_fixed": static(default_candidate()),
            "pre_test_global_best_fixed": cash if global_id is None else static(by_id[str(global_id)]),
            "k4_dynamic_entry_owner_exit": dynamic(PositionExitPolicy.ENTRY_OWNER_ONLY),
            "k4_dynamic_active_strategy_opposite_exit": dynamic(PositionExitPolicy.ACTIVE_STRATEGY_OPPOSITE),
            "existing_manual_regime_router": static(_manual_router_candidate()),
        }
        _same(rebuilt, report.get("test_comparisons"), failures, "scheduler-replayed Test comparisons")
    except (KeyError, LookupError, OSError, RuntimeError, TypeError, ValueError) as error:
        failures.append(f"untouched Test scheduler replay failed: {error}")
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def audit_three_day_k4_daily_mapping(
    inputs: AuditInputs,
    *,
    candidate_manifest_factory: Callable[[], Mapping[str, object]] = _default_manifest,
) -> dict[str, object]:
    failures: list[str] = []
    paths = {
        "report": inputs.report, "model": inputs.model,
        "mapping": inputs.mapping, "markdown": inputs.markdown,
    }
    input_bytes: dict[str, bytes | None] = {}
    for label, path in paths.items():
        try:
            input_bytes[label] = path.read_bytes()
        except OSError as error:
            input_bytes[label] = None
            failures.append(f"{label} output could not be read: {error}")
    report = _read_canonical_json_bytes(
        input_bytes["report"] or b"", failures, "report"
    )
    model = _read_canonical_json_bytes(
        input_bytes["model"] or b"", failures, "model"
    )
    mapping = _read_canonical_json_bytes(
        input_bytes["mapping"] or b"", failures, "mapping"
    )

    if report.get("terminal_stage") in {"model_gate_failed", "model_technical_failure"}:
        return _audit_failed_model_terminal(
            report=report, model=model, mapping=mapping, inputs=inputs,
            input_bytes=input_bytes, failures=failures,
        )

    parsed_model = _audit_model(
        report.get("model_artifact", {}) if isinstance(report.get("model_artifact"), Mapping) else {},
        model, failures,
    )
    if model.get("artifact_version") == "three-day-k4-model-v2":
        refitted_model = _reconstruct_cluster_fit(report, model, failures)
        if refitted_model is not None:
            parsed_model = refitted_model
    raw_count = _audit_raw_inputs(model, report, failures)
    manifest = _audit_manifest(report, candidate_manifest_factory, failures)
    evidence_count, evidence_rows = _audit_evidence(report, model, parsed_model, failures)
    independent_evidence_rows: list[Mapping[str, object]] | None = None
    if model.get("artifact_version") == "three-day-k4-model-v2" and parsed_model is not None:
        try:
            from scripts.chart_regime_strategy_mapping import (
                build_three_day_daily_candidate_manifest,
            )

            typed_manifest = build_three_day_daily_candidate_manifest(
                include_deferred=True, expected_count=459
            )
            independent_evidence_rows = []
            evidence_root = report.get("evidence", {})
            for phase in ("mapping_fit", "validation"):
                bundle = evidence_root.get(phase) if isinstance(evidence_root, Mapping) else None
                if not isinstance(bundle, Mapping):
                    failures.append(f"{phase} report evidence is missing")
                    continue
                independent_evidence_rows.extend(_replay_phase_from_raw(
                    phase=phase, bundle=bundle, report=report,
                    model_artifact=parsed_model, manifest=typed_manifest,
                    ledger_override=inputs.evidence_rows_path, failures=failures,
                ))
        except (RuntimeError, TypeError, ValueError) as error:
            failures.append(f"candidate/evidence replay setup failed: {error}")
            independent_evidence_rows = []
    rebuilt_mapping = _audit_mapping(
        report, mapping, manifest, model, failures,
        independent_evidence_rows=independent_evidence_rows,
    )
    _audit_freeze(report, failures)
    test_trade_count, transition_count = _audit_test_and_baselines(
        report, failures, manifest=manifest,
        evidence_rows=(independent_evidence_rows if independent_evidence_rows is not None else evidence_rows),
    )
    if parsed_model is not None and rebuilt_mapping is not None:
        _replay_untouched_test(report, parsed_model, rebuilt_mapping, failures)

    publication = report.get("publication")
    has_publication = "publication" in report
    has_legacy = "output_hashes" in report
    output_hashes: Mapping[str, object] | None = None
    if has_publication and has_legacy:
        failures.append("report output binding is ambiguous")
    elif has_publication:
        from scripts.chart_regime_strategy_mapping import (
            THREE_DAY_PUBLICATION_HASH_DEFINITION,
        )
        expected_publication_keys = {
            "hash_definition", "report_payload_hash", "model_byte_hash",
            "mapping_byte_hash", "markdown_byte_hash",
        }
        if not isinstance(publication, Mapping) or set(publication) != expected_publication_keys:
            failures.append("report publication output binding is invalid")
            publication = {}
        if publication.get("hash_definition") != THREE_DAY_PUBLICATION_HASH_DEFINITION:
            failures.append("report publication hash_definition is invalid")
        payload = {key: value for key, value in report.items() if key != "publication"}
        if publication.get("report_payload_hash") != _hash(payload):
            failures.append("report publication payload hash mismatch")
        output_hashes = {
            "model": publication.get("model_byte_hash"),
            "mapping": publication.get("mapping_byte_hash"),
            "markdown": publication.get("markdown_byte_hash"),
        }
        if "output_binding_schema_version" in report:
            failures.append("publication output binding has legacy version metadata")
    elif has_legacy:
        output_hashes = report.get("output_hashes")
        if report.get("output_binding_schema_version") != "legacy-output-hashes-v1":
            failures.append("legacy report output binding version is invalid")
        if not isinstance(output_hashes, Mapping) or set(output_hashes) != {"model", "mapping", "markdown"}:
            failures.append("legacy report output binding is invalid")
            output_hashes = {}
    else:
        failures.append("report output binding is missing")

    if output_hashes is not None:
        for label in ("model", "mapping", "markdown"):
            raw = input_bytes[label]
            if raw is None:
                continue
            actual = hashlib.sha256(raw).hexdigest()
            if output_hashes.get(label) != actual:
                failures.append(f"{label} report output hash mismatch")

    hashes = {
        "report_file_hash": hashlib.sha256(input_bytes["report"]).hexdigest() if input_bytes["report"] is not None else None,
        "model_file_hash": hashlib.sha256(input_bytes["model"]).hexdigest() if input_bytes["model"] is not None else None,
        "mapping_file_hash": hashlib.sha256(input_bytes["mapping"]).hexdigest() if input_bytes["mapping"] is not None else None,
        "markdown_file_hash": hashlib.sha256(input_bytes["markdown"]).hexdigest() if input_bytes["markdown"] is not None else None,
        "pre_test_freeze_hash": report.get("pre_test_freeze_hash"),
        "model_artifact_hash": model.get("artifact_hash"),
        "mapping_artifact_hash": mapping.get("artifact_hash"),
    }
    return {
        "schema_version": "three-day-k4-daily-independent-audit-v1",
        "passed": not failures,
        "checked_counts": {
            "raw_inputs": raw_count,
            "candidates": int(manifest.get("candidate_count", 0)) if isinstance(manifest, Mapping) else 0,
            "evidence_rows": evidence_count,
            "test_transitions": transition_count,
            "test_trades": test_trade_count,
        },
        "hashes": hashes,
        "failures": failures,
    }


def _default_paths(report: Path) -> AuditInputs:
    stem = report.with_suffix("")
    return AuditInputs(
        report=report, markdown=stem.with_suffix(".md"),
        model=stem.with_name(stem.name + "-model").with_suffix(".json"),
        mapping=stem.with_name(stem.name + "-mapping").with_suffix(".json"),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument(
        "--evidence-rows-path", type=Path,
        help="base evidence JSONL path; phase suffixes are resolved exactly as the experiment does",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    defaults = _default_paths(args.report)
    inputs = AuditInputs(
        report=args.report,
        markdown=args.markdown or defaults.markdown,
        model=args.model or defaults.model,
        mapping=args.mapping or defaults.mapping,
        evidence_rows_path=args.evidence_rows_path,
    )
    result = audit_three_day_k4_daily_mapping(inputs)
    sys.stdout.buffer.write(canonical_json_bytes(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
