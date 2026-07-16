"""Offline, descriptive balance diagnostics for overlapping three-day regimes."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Callable, Iterable, Mapping, Sequence
from dataclasses import fields, is_dataclass

import numpy as np
from scipy.special import logsumexp
from sklearn.metrics import silhouette_score
import threadpoolctl

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.services.regime_balance_diagnostics import (
    BalanceCandidate,
    ClusterBalanceSummary,
    bootstrap_cluster_share_intervals,
    effective_sample_sizes,
    match_refit_centroids,
    prevalence_drift,
    quarterly_cluster_counts,
    rank_balance_candidates,
    seed_stability,
    summarize_cluster_balance,
)
from src.domain.market import Candle
from src.domain.regime import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
    ThreeDayChartFeatureVector,
    build_daily_regime_episodes,
)
from src.domain.regime.model import RegimeModelConfig
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
    ArchiveDownloader,
    iter_archive_requests,
    iter_zip_csv_rows,
)
from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
    candle_from_kline_row as _shared_candle_from_kline_row,
    candles_from_kline_rows,
    load_three_day_feature_history,
)
from src.infrastructure.regime.sklearn_cluster_diagnostic import SklearnClusterDiagnostic


UTC = timezone.utc
DEFAULT_START = datetime(2024, 7, 1, tzinfo=UTC)
DEFAULT_END = datetime(2026, 7, 1, tzinfo=UTC)
EXPECTED_SAMPLE_COUNT = 727
PRIMARY_SEED = 20260714
SUPPORTING_SEEDS = (20260715, 20260716)
REPORT_VERSION = "three-day-regime-balance-diagnostic-v1"


@dataclass(frozen=True)
class CandidateConfig:
    identity: str
    model: RegimeModelConfig


def _midnight_z(value: str) -> datetime:
    formats = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ")
    for format_string in formats:
        try:
            parsed = datetime.strptime(value, format_string).replace(tzinfo=UTC)
            break
        except ValueError:
            continue
    else:
        raise argparse.ArgumentTypeError(
            "timestamp must be canonical YYYY-MM-DD or YYYY-MM-DDT00:00:00Z"
        )
    if parsed.time() != datetime.min.time():
        raise argparse.ArgumentTypeError("timestamp must be canonical midnight UTC")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic three-day regime balance diagnostic (no strategy evaluation)."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", type=_midnight_z, default=DEFAULT_START)
    parser.add_argument("--end", type=_midnight_z, default=DEFAULT_END)
    raw_group = parser.add_mutually_exclusive_group()
    raw_group.add_argument("--raw-kline-root", type=Path)
    raw_group.add_argument("--raw-root", type=Path)
    parser.add_argument(
        "--json-output", "--output-json", dest="json_output", type=Path,
        default=Path("docs/reports/chart-regime-balance-3d.json"),
    )
    parser.add_argument(
        "--markdown-output", "--output-markdown", dest="markdown_output", type=Path,
        default=Path("docs/reports/chart-regime-balance-3d.md"),
    )
    args = parser.parse_args(argv)
    if args.raw_kline_root is None:
        base = args.raw_root or Path(".research-data/binance-usdm")
        args.raw_kline_root = base / "raw" / "klines" if args.raw_root is None else base / "klines"
    if args.raw_root is None:
        args.raw_root = Path(".research-data/binance-usdm")
    if args.symbol != args.symbol.strip().upper() or not args.symbol.endswith("USDT"):
        parser.error("symbol must be canonical uppercase and end in USDT")
    if args.end <= args.start:
        parser.error("end must be after start")
    try:
        _validate_distinct_destinations(args.json_output, args.markdown_output)
    except ValueError as error:
        parser.error(str(error))
    return args


def _destination_identity(path: Path) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=False)))


def _validate_distinct_destinations(*paths: Path) -> None:
    destinations = tuple(Path(path) for path in paths)
    if len(destinations) < 2:
        raise ValueError("at least two report destinations are required")
    is_reserved = getattr(os.path, "isreserved", None)
    if callable(is_reserved) and any(is_reserved(os.fspath(path)) for path in destinations):
        raise ValueError("report destination uses a platform-reserved path name")
    identities = tuple(_destination_identity(path) for path in destinations)
    if len(set(identities)) != len(identities):
        raise ValueError("report destinations must be distinct")
    for path in destinations:
        is_junction = getattr(path, "is_junction", None)
        if (
            path.is_symlink()
            or (callable(is_junction) and is_junction())
            or (path.exists() and not path.is_file())
        ):
            raise ValueError("existing report destination must be a regular file that is replaceable")
    existing = tuple(path for path in destinations if path.exists())
    for index, first in enumerate(existing):
        for second in existing[index + 1 :]:
            if os.path.samefile(first, second):
                raise ValueError("report destinations must be distinct (hardlink alias)")


def build_primary_configs() -> tuple[CandidateConfig, ...]:
    values = [
        CandidateConfig(f"kmeans-k{count}", RegimeModelConfig("kmeans", count, random_seed=PRIMARY_SEED))
        for count in range(3, 9)
    ]
    values.extend(
        CandidateConfig(
            f"gmm-{covariance}-k{count}",
            RegimeModelConfig("gmm", count, random_seed=PRIMARY_SEED, covariance_type=covariance, regularization=1e-6),
        )
        for count in range(3, 9)
        for covariance in ("diag", "tied")
    )
    return tuple(values)


def _candle_from_row(row: Sequence[object], symbol: str) -> Candle:
    return _shared_candle_from_kline_row(row, symbol=symbol)


def validate_vectors(
    vectors: Sequence[ThreeDayChartFeatureVector], *, symbol: str, start: datetime, end: datetime
) -> tuple[ThreeDayChartFeatureVector, ...]:
    values = tuple(vectors)
    episodes = build_daily_regime_episodes(start, end)
    if len(values) != EXPECTED_SAMPLE_COUNT or len(episodes) != EXPECTED_SAMPLE_COUNT:
        raise ValueError(f"approved diagnostic requires exactly {EXPECTED_SAMPLE_COUNT} vectors")
    if any(not isinstance(vector, ThreeDayChartFeatureVector) for vector in values):
        raise ValueError("vectors must be canonical three-day feature vectors")
    if any(vector.symbol != symbol for vector in values):
        raise ValueError("feature vector symbol mismatch")
    expected_anchors = tuple(episode.anchor_at for episode in episodes)
    if tuple(vector.anchor_at for vector in values) != expected_anchors:
        raise ValueError("feature vector anchors must exactly match daily episodes")
    if any(vector.window_start_at != episode.feature_start_at for vector, episode in zip(values, episodes)):
        raise ValueError("feature vectors must contain only pre-anchor candles")
    return values


def acquire_feature_vectors(
    *, symbol: str, start: datetime, end: datetime, raw_root: Path,
    downloader: ArchiveDownloader | None = None,
    request_factory: Callable[..., Iterable[object]] = iter_archive_requests,
    row_reader: Callable[[Path], Iterable[Sequence[object]]] = iter_zip_csv_rows,
) -> tuple[tuple[ThreeDayChartFeatureVector, ...], list[dict[str, object]]]:
    vectors, provenance = load_three_day_feature_history(
        symbol=symbol,
        start=start,
        end=end,
        raw_root=raw_root,
        expected_anchor_count=EXPECTED_SAMPLE_COUNT,
        downloader=downloader,
        request_factory=request_factory,
        row_reader=row_reader,
    )
    return vectors, [dict(item) for item in provenance]


def _config_payload(config: RegimeModelConfig) -> dict[str, object]:
    return asdict(config)


def _fit_payload(fit: object) -> dict[str, object]:
    return {
        "retained_feature_names": list(fit.feature_names), "lower_bounds": list(fit.lower_bounds),
        "upper_bounds": list(fit.upper_bounds), "medians": list(fit.medians), "scales": list(fit.scales),
        "fingerprints": list(fit.fingerprints), "means": [list(row) for row in fit.means],
        "weights": list(fit.weights), "covariances": [list(row) for row in fit.covariances],
    }


def _jsonable(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("report metrics must be finite")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("report metrics must be finite")
        return format(value, "f")
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported report value: {type(value).__name__}")


def _scaled_matrix(vectors: Sequence[ThreeDayChartFeatureVector], fit: object) -> np.ndarray:
    matrix = np.asarray([[vector.values[name] for name in fit.feature_names] for vector in vectors])
    return (np.clip(matrix, fit.lower_bounds, fit.upper_bounds) - np.asarray(fit.medians)) / np.asarray(fit.scales)


def _gmm_bic(vectors: Sequence[ThreeDayChartFeatureVector], fit: object) -> float:
    matrix = _scaled_matrix(vectors, fit)
    dimensions = matrix.shape[1]
    terms = []
    for index, mean in enumerate(fit.means):
        covariance = np.asarray(fit.covariances[index])
        covariance = np.diag(covariance) if fit.config.covariance_type == "diag" else covariance.reshape(dimensions, dimensions)
        sign, logdet = np.linalg.slogdet(covariance)
        if sign <= 0:
            raise ValueError("GMM covariance is not positive definite")
        delta = matrix - np.asarray(mean)
        quadratic = np.einsum("ij,jk,ik->i", delta, np.linalg.inv(covariance), delta)
        terms.append(math.log(fit.weights[index]) - .5 * (dimensions * math.log(2 * math.pi) + logdet + quadratic))
    likelihood = float(np.sum(logsumexp(np.stack(terms, axis=1), axis=1)))
    clusters = fit.config.cluster_count
    covariance_parameters = clusters * dimensions if fit.config.covariance_type == "diag" else dimensions * (dimensions + 1) // 2
    parameters = clusters * dimensions + covariance_parameters + clusters - 1
    result = parameters * math.log(len(matrix)) - 2 * likelihood
    if not math.isfinite(result):
        raise ValueError("GMM BIC must be finite")
    return result


def cross_half_prevalence_drift(
    *, first_labels: Sequence[str], second_labels: Sequence[str],
    first_to_primary: Mapping[str, str], second_to_primary: Mapping[str, str],
    primary_fingerprints: Sequence[str],
) -> object:
    """Compare chronological refit prevalence after both halves share primary IDs."""
    primary = tuple(primary_fingerprints)
    first_mapping = dict(first_to_primary)
    second_mapping = dict(second_to_primary)
    try:
        first_mapped = tuple(first_mapping[label] for label in first_labels)
        second_mapped = tuple(second_mapping[label] for label in second_labels)
    except KeyError as error:
        raise ValueError("chronological labels must be covered by centroid mappings") from error
    identity = {fingerprint: fingerprint for fingerprint in primary}
    return prevalence_drift(
        first_half_labels=first_mapped,
        second_half_labels=second_mapped,
        primary_fingerprints=primary,
        refit_fingerprints=primary,
        refit_to_primary=identity,
    )


def _fit_candidate(config: CandidateConfig, vectors: tuple[ThreeDayChartFeatureVector, ...], adapter: object) -> dict[str, object]:
    with threadpoolctl.threadpool_limits(limits=1):
        return _fit_candidate_single_thread(config, vectors, adapter)


def _fit_candidate_single_thread(
    config: CandidateConfig, vectors: tuple[ThreeDayChartFeatureVector, ...], adapter: object,
) -> dict[str, object]:
    registry = THREE_DAY_CHART_FEATURE_REGISTRY_V1
    primary = adapter.fit(config.model, vectors, registry)
    primary_assignments = adapter.assign(primary, vectors, registry)
    labels = tuple(item.fingerprint for item in primary_assignments)
    balance = summarize_cluster_balance(labels, primary.fingerprints)
    bootstrap = bootstrap_cluster_share_intervals(labels, primary.fingerprints, block_length=3, resamples=5000,
                                                  confidence=.95, seed=PRIMARY_SEED)
    ess = effective_sample_sizes(labels, primary.fingerprints, max_lag=30)
    episodes = build_daily_regime_episodes(
        vectors[0].window_start_at,
        vectors[-1].anchor_at + timedelta(days=1),
    )
    quarters = quarterly_cluster_counts(episodes, labels, primary.fingerprints)
    quarter_warnings = [
        {"quarter": quarter, "zero_count_fingerprints": [name for name, count in quarters.counts[quarter].items() if count == 0]}
        for quarter in quarters.quarters
        if any(count == 0 for count in quarters.counts[quarter].values())
    ]
    seed_results = []
    for seed in SUPPORTING_SEEDS:
        refit_config = RegimeModelConfig(config.model.model_type, config.model.cluster_count, random_seed=seed,
                                         covariance_type=config.model.covariance_type, regularization=config.model.regularization)
        refit = adapter.fit(refit_config, vectors, registry, retained_feature_names=primary.feature_names)
        refit_labels = tuple(item.fingerprint for item in adapter.assign(refit, vectors, registry))
        stability = seed_stability(labels, refit_labels, primary.fingerprints, refit.fingerprints)
        seed_results.append({"seed": seed, **_jsonable(stability)})
    chronological = []
    chronological_labels = []
    chronological_mappings = []
    split = len(vectors) // 2
    for name, block in (("first", vectors[:split]), ("second", vectors[split:])):
        refit = adapter.fit(config.model, block, registry, retained_feature_names=primary.feature_names)
        refit_labels = tuple(item.fingerprint for item in adapter.assign(refit, block, registry))
        matching = match_refit_centroids(
            primary_centroids=primary.means, refit_centroids=refit.means,
            primary_feature_names=primary.feature_names, refit_feature_names=refit.feature_names,
            primary_means=primary.medians, primary_scales=primary.scales,
            refit_means=refit.medians, refit_scales=refit.scales,
            primary_fingerprints=primary.fingerprints, refit_fingerprints=refit.fingerprints,
        )
        chronological.append({"block": name, "sample_count": len(block), "fit": _fit_payload(refit),
                              "centroid_matching": _jsonable(matching)})
        chronological_labels.append(refit_labels)
        chronological_mappings.append(matching.refit_to_primary)
    cross_half_drift = cross_half_prevalence_drift(
        first_labels=chronological_labels[0], second_labels=chronological_labels[1],
        first_to_primary=chronological_mappings[0], second_to_primary=chronological_mappings[1],
        primary_fingerprints=primary.fingerprints,
    )
    if config.model.model_type == "kmeans":
        label_indices = [primary.fingerprints.index(label) for label in labels]
        family_metric = {"silhouette": float(silhouette_score(_scaled_matrix(vectors, primary), label_indices)), "bic": None}
    else:
        family_metric = {"silhouette": None, "bic": _gmm_bic(vectors, primary)}
    return {
        "identity": config.identity, "status": "accepted", "model": _config_payload(config.model),
        "fit": _fit_payload(primary),
        "metrics": {
            "counts": dict(balance.counts), "shares": dict(balance.shares),
            "empty_cluster_count": sum(count == 0 for count in balance.counts.values()),
            "normalized_entropy": balance.normalized_entropy, "minimum_share": balance.minimum_share,
            "maximum_share": balance.maximum_share, "quarterly": _jsonable(quarters),
            "quarter_warnings": quarter_warnings,
            "bootstrap": _jsonable(bootstrap), "minimum_ess": ess.minimum, "effective_sample_sizes": _jsonable(ess),
            "seed_stability": seed_results, "chronological_stability": chronological,
            "cross_half_prevalence_drift": _jsonable(cross_half_drift), **family_metric,
        },
        "rejections": [],
    }


def evaluate_candidates(
    vectors: tuple[ThreeDayChartFeatureVector, ...], *, configs: Sequence[CandidateConfig] | None = None,
    adapter: object | None = None,
) -> list[dict[str, object]]:
    adapter = adapter or SklearnClusterDiagnostic()
    records = []
    for config in tuple(configs or build_primary_configs()):
        try:
            records.append(_fit_candidate(config, vectors, adapter))
        except (ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
            records.append({"identity": config.identity, "status": "rejected", "model": _config_payload(config.model),
                            "fit": None, "metrics": None,
                            "rejections": [{"stage": "technical_fit_or_metric", "reason": str(error)}]})
    return records


def _registry_payload() -> list[dict[str, object]]:
    return [asdict(spec) for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1]


def assemble_report(
    *, vectors: Sequence[ThreeDayChartFeatureVector], candidates: Sequence[Mapping[str, object]],
    archive_provenance: Sequence[Mapping[str, object]], start: datetime, end: datetime, symbol: str,
) -> dict[str, object]:
    values = validate_vectors(vectors, symbol=symbol, start=start, end=end)
    candidate_values = [_jsonable(item) for item in candidates]
    if not candidate_values:
        raise ValueError("diagnostic must include candidate records")
    if not archive_provenance:
        raise ValueError("archive provenance must be nonempty")
    provenance = []
    required_provenance_fields = {"period", "url", "sha256", "bytes", "member_identity"}
    for raw_item in archive_provenance:
        item = _jsonable(raw_item)
        if "status" in item:
            raise ValueError("archive provenance must not contain ephemeral acquisition status")
        if set(item) != required_provenance_fields:
            raise ValueError("archive provenance must contain exactly the stable canonical fields")
        stable = {key: item[key] for key in ("period", "url", "sha256", "bytes", "member_identity")}
        provenance.append(stable)
    for item in provenance:
        sha256 = item.get("sha256")
        period = item.get("period")
        url = item.get("url")
        member_identity = item.get("member_identity")
        if (
            not isinstance(period, str) or not period or period != period.strip()
            or not isinstance(url, str) or url != url.strip() or not url.startswith("https://")
            or not isinstance(sha256, str) or len(sha256) != 64
            or sha256 != sha256.lower() or any(character not in "0123456789abcdef" for character in sha256)
            or not isinstance(item.get("bytes"), int) or isinstance(item["bytes"], bool) or item["bytes"] <= 0
            or not isinstance(member_identity, str) or not member_identity or member_identity != member_identity.strip()
            or "/" in member_identity or "\\" in member_identity
            or url.rsplit("/", 1)[-1] != member_identity
        ):
            raise ValueError("archive provenance fields must be complete and canonical")
    if len({(item["period"], item["url"], item["sha256"]) for item in provenance}) != len(provenance):
        raise ValueError("archive provenance entries must be unique")
    accepted = [item for item in candidate_values if item["status"] == "accepted"]
    for item in accepted:
        counts = item["metrics"].get("counts")
        if not isinstance(counts, Mapping) or not counts:
            raise ValueError("accepted candidate metrics require cluster counts")
        empty_cluster_count = sum(count == 0 for count in counts.values())
        reported = item["metrics"].get("empty_cluster_count", empty_cluster_count)
        if reported != empty_cluster_count:
            raise ValueError("empty cluster count is inconsistent with cluster counts")
        item["metrics"]["empty_cluster_count"] = empty_cluster_count
    ranking_inputs = []
    for item in accepted:
        metrics = item["metrics"]
        counts = dict(metrics["counts"])
        shares = dict(metrics["shares"])
        summary = ClusterBalanceSummary(
            tuple(counts), len(values), counts, shares, metrics["normalized_entropy"],
            min(shares.values()), max(shares.values()),
        )
        ranking_inputs.append(BalanceCandidate(item["identity"], summary))
    ranking = [item.config_identity for item in rank_balance_candidates(ranking_inputs)] if ranking_inputs else []
    retained = {item["identity"]: item["fit"]["retained_feature_names"] for item in accepted}
    registry_names = [spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1]
    removals = {identity: [name for name in registry_names if name not in names] for identity, names in retained.items()}
    combined_hash = hashlib.sha256(canonical_json_bytes(provenance)).hexdigest()
    return _jsonable({
        "version": REPORT_VERSION, "kind": "three_day_regime_balance_diagnostic",
        "symbol": symbol, "interval": {"start_inclusive": start.isoformat().replace("+00:00", "Z"),
                                          "end_exclusive": end.isoformat().replace("+00:00", "Z")},
        "sample_count": len(values),
        "archive_provenance": provenance, "archive_combined_sha256": combined_hash,
        "feature_schema": {"version": THREE_DAY_CHART_FEATURE_SCHEMA_VERSION, "registry": _registry_payload(),
                           "retained_by_candidate": retained, "removed_by_candidate": removals},
        "candidate_configs": candidate_values, "ranking": ranking, "ranking_purpose": "descriptive_only",
        "strategy_outcomes_read": False, "strategy_outcomes_evaluated": False,
        "production_model_selected": False, "outcome_evaluation": "reserved_not_evaluated",
    })


def canonical_json_bytes(payload: object) -> bytes:
    return (json.dumps(_jsonable(payload), ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def render_markdown(payload: Mapping[str, object]) -> str:
    lines = ["# Three-day regime balance diagnostic", "", "Descriptive comparison only; ranking is not selection.", "",
             "| Candidate | Status | Counts | Shares | Empty clusters | Entropy | Min ESS | Quarter warnings | Seed stability | Chronological stability | Cross-half prevalence drift | Rejections |",
             "|---|---|---|---|---:|---:|---:|---|---|---|---|---|"]
    for candidate in payload.get("candidate_configs", []):
        metrics = candidate.get("metrics") or {}
        quarterly = metrics.get("quarterly", {})
        quarter_counts = quarterly.get("counts", {}) if isinstance(quarterly, Mapping) else {}
        warnings = [quarter for quarter, counts in quarter_counts.items() if any(value == 0 for value in counts.values())]
        seed_summary = _seed_stability_summary(metrics.get("seed_stability"))
        chronological_summary = _chronological_stability_summary(metrics.get("chronological_stability"))
        prevalence_summary = _prevalence_drift_summary(metrics.get("cross_half_prevalence_drift"))
        lines.append(
            f"| {candidate['identity']} | {candidate['status']} | {metrics.get('counts', {})} | {metrics.get('shares', {})} | "
            f"{metrics.get('empty_cluster_count', 'n/a')} | "
            f"{metrics.get('normalized_entropy', 'n/a')} | {metrics.get('minimum_ess', 'n/a')} | {warnings or 'none'} | "
            f"{seed_summary} | {chronological_summary} | {prevalence_summary} | "
            f"{candidate.get('rejections') or 'none'} |"
        )
    lines.extend(["", "## Limitations", "", "- 727 overlapping 3d windows are not independent.",
                  "- No strategy evaluated.", "- No production model selected.", ""])
    return "\n".join(lines)


def _seed_stability_summary(value: object) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        return "n/a"
    records = tuple(value)
    if any(not isinstance(record, Mapping) for record in records):
        return "n/a"
    try:
        minimum_ari = min(record["adjusted_rand_index"] for record in records)
        minimum_nmi = min(record["normalized_mutual_information"] for record in records)
    except (KeyError, TypeError):
        return "n/a"
    return f"min ARI={minimum_ari}; min NMI={minimum_nmi}"


def _chronological_stability_summary(value: object) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        return "n/a"
    summaries = []
    for record in value:
        if not isinstance(record, Mapping) or not isinstance(record.get("centroid_matching"), Mapping):
            return "n/a"
        matching = record["centroid_matching"]
        try:
            summaries.append(
                f"{record['block']}: mean={matching['mean_distance']}, max={matching['maximum_distance']}"
            )
        except KeyError:
            return "n/a"
    return "; ".join(summaries)


def _prevalence_drift_summary(value: object) -> str:
    if not isinstance(value, Mapping):
        return "n/a"
    try:
        return f"max={value['maximum']}; L1={value['l1']}"
    except KeyError:
        return "n/a"


def _best_effort_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _write_temp(final: Path, content: bytes) -> Path:
    final.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{final.name}.", suffix=".tmp", dir=final.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        return temporary
    except BaseException:
        _best_effort_unlink(temporary)
        raise


def _unused_sibling(final: Path, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=f".{final.name}.", suffix=suffix, dir=final.parent)
    os.close(descriptor)
    path = Path(name)
    path.unlink()
    return path


def write_bytes_pair_atomic(
    first_content: bytes, second_content: bytes, *, first_path: Path, second_path: Path,
) -> None:
    """Publish a byte pair transactionally, retaining recoverable backups on rollback failure."""

    write_bytes_atomic(
        ((Path(first_path), first_content), (Path(second_path), second_content))
    )


def write_bytes_atomic(items: Sequence[tuple[Path, bytes]]) -> None:
    """Publish two or more byte artifacts in one recoverable transaction."""

    supplied = tuple((Path(path), content) for path, content in items)
    if len(supplied) < 2 or any(not isinstance(content, bytes) for _, content in supplied):
        raise TypeError("transactional report content must contain at least two byte artifacts")
    finals = tuple(path for path, _ in supplied)
    _validate_distinct_destinations(*finals)
    temporaries: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    originally_absent: set[Path] = set()
    published: set[Path] = set()
    publication_succeeded = False
    try:
        for final, content in supplied:
            temporaries[final] = _write_temp(final, content)
        for final in finals:
            if final.exists():
                backup = _unused_sibling(final, ".bak")
                final.replace(backup)
                backups[final] = backup
            else:
                originally_absent.add(final)
        for final in finals:
            temporary = temporaries[final]
            temporary.replace(final)
            temporaries.pop(final)
            published.add(final)
        publication_succeeded = True
    except BaseException as publication_error:
        rollback_errors = []
        for final in finals:
            try:
                if final in published:
                    final.unlink(missing_ok=True)
                if final in backups:
                    backups[final].replace(final)
                    backups.pop(final)
                elif final in originally_absent:
                    final.unlink(missing_ok=True)
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
        if rollback_errors:
            for error in rollback_errors:
                publication_error.add_note(f"rollback error: {error}")
        raise
    finally:
        for temporary in temporaries.values():
            _best_effort_unlink(temporary)
        if publication_succeeded:
            for backup in backups.values():
                _best_effort_unlink(backup)


def write_reports_atomic(payload: Mapping[str, object], *, json_path: Path, markdown_path: Path) -> None:
    _validate_distinct_destinations(json_path, markdown_path)
    write_bytes_pair_atomic(
        canonical_json_bytes(payload), render_markdown(payload).encode("utf-8"),
        first_path=json_path, second_path=markdown_path,
    )


def run_diagnostic(
    args: argparse.Namespace, *, vector_source: Callable[..., object] = acquire_feature_vectors,
    configs: Sequence[CandidateConfig] | None = None, adapter: object | None = None,
) -> dict[str, object]:
    vectors, provenance = vector_source(
        symbol=args.symbol, start=args.start, end=args.end, raw_root=args.raw_kline_root,
    )
    vectors = validate_vectors(vectors, symbol=args.symbol, start=args.start, end=args.end)
    candidates = evaluate_candidates(vectors, configs=configs, adapter=adapter)
    report = assemble_report(vectors=vectors, candidates=candidates, archive_provenance=provenance,
                             start=args.start, end=args.end, symbol=args.symbol)
    write_reports_atomic(report, json_path=args.json_output, markdown_path=args.markdown_output)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    run_diagnostic(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
