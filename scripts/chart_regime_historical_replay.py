"""Deterministic reverse-time replay of fixed three-day BTC regime fits."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.chart_regime_balance_diagnostic import (
    _validate_distinct_destinations,
    canonical_json_bytes,
    write_bytes_pair_atomic,
)
from src.application.services.regime_historical_replay import (
    build_confidence_reference,
    diagnose_gmm_assignments,
    rank_historical_replay_candidates,
    summarize_historical_replay_candidate,
)
from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
    load_three_day_feature_history,
)
from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
    iter_archive_requests,
)
from src.infrastructure.regime.historical_replay_source import (
    HistoricalReplaySource,
    load_historical_replay_source,
)
from src.domain.regime import ThreeDayChartFeatureVector, build_daily_regime_episodes


UTC = timezone.utc
HISTORICAL_START = datetime(2021, 1, 1, tzinfo=UTC)
HISTORICAL_END = datetime(2024, 7, 1, tzinfo=UTC)
TRAINING_START = HISTORICAL_END
TRAINING_END = datetime(2026, 7, 1, tzinfo=UTC)
HISTORICAL_SAMPLE_COUNT = 1274
TRAINING_SAMPLE_COUNT = 727
SOURCE_SHA256 = "2e656b11b89baf412d1f6af3217c8900165d45c14531c28f64795695baaa8f4c"
REPORT_VERSION = "three-day-regime-historical-replay-v1"


def _midnight(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be canonical YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise argparse.ArgumentTypeError("date must be canonical YYYY-MM-DD")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay fixed BTCUSDT three-day regime fits on older data (research only)."
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--historical-start", type=_midnight, default=HISTORICAL_START)
    parser.add_argument("--historical-end", type=_midnight, default=HISTORICAL_END)
    parser.add_argument("--training-start", type=_midnight, default=TRAINING_START)
    parser.add_argument("--training-end", type=_midnight, default=TRAINING_END)
    parser.add_argument("--source-report", type=Path, default=Path("docs/backtests/chart-regime-balance-btcusdt-3d-1d-2024-2026.json"))
    parser.add_argument("--expected-source-sha256", default=SOURCE_SHA256)
    parser.add_argument("--raw-kline-root", type=Path, default=Path(".research-data/binance-usdm/raw/klines"))
    parser.add_argument("--output-json", type=Path, default=Path("docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.json"))
    parser.add_argument("--output-markdown", type=Path, default=Path("docs/backtests/chart-regime-historical-replay-btcusdt-3d-2021-2024.md"))
    return parser.parse_args(argv)


def _z(value: datetime) -> str:
    if value.tzinfo is not UTC or value.time() != datetime.min.time():
        raise ValueError("report timestamps must be canonical midnight UTC")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return _z(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("report cannot contain non-finite values")
        return value
    raise ValueError(f"report contains unsupported value type: {type(value).__name__}")


def _validate_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("report cannot contain non-finite values")
    if isinstance(value, Mapping):
        for item in value.values():
            _validate_finite(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _validate_finite(item)


def _canonical_provenance(
    values: Sequence[Mapping[str, object]], *, interval_name: str,
    symbol: str, start: datetime, end: datetime,
) -> list[dict[str, object]]:
    required = ("period", "url", "sha256", "bytes", "member_identity")
    expected_requests = tuple(iter_archive_requests(
        "klines", symbol, start, end, now=end + timedelta(days=32),
    ))
    rows = []
    for raw in values:
        if not isinstance(raw, Mapping) or tuple(raw) != required:
            raise ValueError(f"{interval_name} archive provenance must use stable canonical field order")
        row = {key: raw[key] for key in required}
        sha = row["sha256"]
        if (
            not isinstance(row["period"], str) or not row["period"] or row["period"] != row["period"].strip()
            or not isinstance(row["url"], str) or row["url"] != row["url"].strip() or not row["url"].startswith("https://")
            or not isinstance(sha, str) or len(sha) != 64 or sha != sha.lower()
            or any(char not in "0123456789abcdef" for char in sha)
            or not isinstance(row["bytes"], int) or isinstance(row["bytes"], bool) or row["bytes"] <= 0
            or not isinstance(row["member_identity"], str) or not row["member_identity"]
            or row["member_identity"] != row["member_identity"].strip()
            or "/" in row["member_identity"] or "\\" in row["member_identity"]
            or row["url"].rsplit("/", 1)[-1] != row["member_identity"]
        ):
            raise ValueError(f"{interval_name} archive provenance is not canonical")
        rows.append(row)
    if not rows or len({(row["period"], row["url"], row["member_identity"]) for row in rows}) != len(rows):
        raise ValueError(f"{interval_name} archive provenance must be nonempty and unique")
    identities = tuple((row["period"], row["url"], row["member_identity"]) for row in rows)
    expected = tuple((request.period, request.url, request.filename) for request in expected_requests)
    if identities != expected:
        raise ValueError(f"{interval_name} archive provenance must exactly match the ordered Binance request set")
    return rows


def _validate_vectors(values: Sequence, *, symbol: str, start: datetime, end: datetime, count: int, name: str):
    vectors = tuple(values)
    episodes = build_daily_regime_episodes(start, end)
    if len(vectors) != count or len(episodes) != count:
        raise ValueError(f"{name} vectors must contain exactly {count} canonical anchors")
    if any(not isinstance(vector, ThreeDayChartFeatureVector) for vector in vectors):
        raise ValueError(f"{name} vectors must be canonical three-day feature vectors")
    if any(vector.symbol != symbol for vector in vectors):
        raise ValueError(f"{name} vector symbol mismatch")
    if tuple(vector.anchor_at for vector in vectors) != tuple(episode.anchor_at for episode in episodes):
        raise ValueError(f"{name} vector anchors do not match the frozen interval")
    if any(vector.window_start_at != episode.feature_start_at for vector, episode in zip(vectors, episodes)):
        raise ValueError(f"{name} feature windows cross their anchor boundary")
    return vectors


def _model_payload(identity, fit, reference, result, training_counts) -> dict[str, object]:
    historical = _plain(result)
    historical_counts = historical["balance"]["counts"]
    total = sum(training_counts.values())
    training_shares = {name: training_counts[name] / total for name in fit.fingerprints}
    prevalence_delta = {
        name: historical["balance"]["shares"][name] - training_shares[name]
        for name in fit.fingerprints
    }
    return {
        "identity": identity,
        "config": _plain(fit.config),
        "fingerprints": list(fit.fingerprints),
        "source_fit_sha256": hashlib.sha256(canonical_json_bytes(_plain(fit))).hexdigest(),
        "training_distribution": {"counts": dict(training_counts), "shares": training_shares},
        "historical_distribution": {
            "counts": historical_counts,
            "shares": historical["balance"]["shares"],
            "prevalence_delta_vs_training": prevalence_delta,
        },
        "reference_cutoffs": {
            "source": "training_only",
            "sample_count": reference.sample_count,
            "quantile_method": reference.quantile_method,
            "dominant_posterior_p05": reference.posterior_fifth_percentile,
            "posterior_margin_p05": reference.margin_fifth_percentile,
            "assigned_component_mahalanobis_p995": dict(reference.component_distance_995),
            "posterior_quantiles": dict(reference.posterior_quantiles),
            "margin_quantiles": dict(reference.margin_quantiles),
            "distance_quantiles": dict(reference.distance_quantiles),
        },
        "historical": historical,
    }


def build_report(
    *, symbol: str, historical_start: datetime, historical_end: datetime,
    training_start: datetime, training_end: datetime,
    source: HistoricalReplaySource | None,
    historical_vectors: Sequence, historical_provenance: Sequence[Mapping[str, object]],
    training_vectors: Sequence, training_provenance: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if historical_end != training_start:
        raise ValueError("historical and training intervals must be disjoint and adjacent")
    if not historical_start < historical_end < training_end:
        raise ValueError("historical and training intervals must be ordered and nonempty")
    if (historical_start, historical_end, training_start, training_end) != (
        HISTORICAL_START, HISTORICAL_END, TRAINING_START, TRAINING_END,
    ):
        raise ValueError("replay intervals must match the frozen historical and training contracts")
    if source is None:
        raise ValueError("fixed historical replay source is required")
    if symbol != "BTCUSDT" or source.training_start_at != training_start or source.training_end_at != training_end:
        raise ValueError("symbol or training interval disagrees with fixed source")
    if tuple(source.fits) != ("gmm-diag-k4", "gmm-diag-k8") or tuple(source.training_counts) != tuple(source.fits):
        raise ValueError("fixed replay source must contain exactly K4 and K8")
    historical = _validate_vectors(
        historical_vectors, symbol=symbol, start=historical_start, end=historical_end,
        count=HISTORICAL_SAMPLE_COUNT, name="historical",
    )
    training = _validate_vectors(
        training_vectors, symbol=symbol, start=training_start, end=training_end,
        count=TRAINING_SAMPLE_COUNT, name="training-reference",
    )
    historical_archive = _canonical_provenance(
        historical_provenance, interval_name="historical", symbol=symbol,
        start=historical_start, end=historical_end,
    )
    training_archive = _canonical_provenance(
        training_provenance, interval_name="training-reference", symbol=symbol,
        start=training_start, end=training_end,
    )
    training_archive_hash = hashlib.sha256(canonical_json_bytes(training_archive)).hexdigest()
    if (
        tuple(training_archive) != source.archive_provenance
        or training_archive_hash != source.archive_combined_sha256
    ):
        raise ValueError("current training archive provenance does not exactly match the frozen source")

    models = []
    results = []
    for identity in ("gmm-diag-k4", "gmm-diag-k8"):
        fit = source.fits[identity]
        training_diagnostics = diagnose_gmm_assignments(fit, training, source.registry)
        observed_training_counts = {
            fingerprint: sum(row.fingerprint == fingerprint for row in training_diagnostics)
            for fingerprint in fit.fingerprints
        }
        if observed_training_counts != dict(source.training_counts[identity]):
            raise ValueError("current training assignment counts do not match the frozen source")
        reference = build_confidence_reference(training_diagnostics, fit.fingerprints)
        historical_diagnostics = diagnose_gmm_assignments(fit, historical, source.registry)
        counts = source.training_counts[identity]
        training_shares = {name: counts[name] / TRAINING_SAMPLE_COUNT for name in fit.fingerprints}
        result = summarize_historical_replay_candidate(
            identity=identity, fit=fit, vectors=historical,
            diagnostics=historical_diagnostics, reference=reference,
            training_shares=training_shares,
        )
        results.append(result)
        models.append(_model_payload(identity, fit, reference, result, counts))
    ranked = rank_historical_replay_candidates(results)
    report = {
        "kind": "three_day_regime_historical_replay",
        "version": REPORT_VERSION,
        "symbol": symbol,
        "historical_interval": {"start_inclusive": _z(historical_start), "end_exclusive": _z(historical_end)},
        "training_reference_interval": {"start_inclusive": _z(training_start), "end_exclusive": _z(training_end)},
        "historical_sample_count": len(historical),
        "training_reference_sample_count": len(training),
        "historical_first_anchor": _z(historical[0].anchor_at),
        "historical_last_anchor": _z(historical[-1].anchor_at),
        "training_reference_first_anchor": _z(training[0].anchor_at),
        "training_reference_last_anchor": _z(training[-1].anchor_at),
        "source_report_sha256": source.report_sha256,
        "archive_provenance": {
            "historical": historical_archive,
            "training_reference": training_archive,
        },
        "archive_combined_sha256": {
            "historical": hashlib.sha256(canonical_json_bytes(historical_archive)).hexdigest(),
            "training_reference": training_archive_hash,
            "overall": hashlib.sha256(canonical_json_bytes({
                "historical": historical_archive, "training_reference": training_archive,
            })).hexdigest(),
        },
        "models": models,
        "research_preference": [item.identity for item in ranked],
        "preferred_research_model": ranked[0].identity,
        "preference_rule": "lexicographic: clipping, margin-tail, distance-tail, empty-cluster quarter warnings, negative minimum ESS, JSD, K, identity",
        "models_refit": False,
        "runtime_thresholds_present": False,
        "historical_cutoffs_fitted": False,
        "strategy_outcomes_read": False,
        "strategy_outcomes_evaluated": False,
        "production_model_selected": False,
    }
    _validate_finite(report)
    return report


def render_markdown(payload: Mapping[str, object]) -> str:
    models = payload["models"]
    lines = [
        "# BTCUSDT 3-day regime historical replay",
        "",
        "| Model | Clip share | Posterior tail | Margin tail | Distance tail | JSD | Min ESS | Quarterly warnings |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model in models:
        historical = model["historical"]
        confidence = historical["confidence"]
        lines.append(
            f"| {model['identity']} | {historical['envelope']['any_feature_exceedance_share']:.6f} "
            f"| {confidence['posterior_below_reference_share']:.6f} | {confidence['margin_below_reference_share']:.6f} "
            f"| {confidence['component_distance_above_reference_share']:.6f} | {historical['jensen_shannon_divergence']:.6f} "
            f"| {historical['effective_sample_sizes']['minimum']:.2f} | {len(historical['quarter_warnings'])} |"
        )
    lines.extend(["", "## Training-reference tails", ""])
    for model in models:
        cutoff = model["reference_cutoffs"]
        lines.append(
            f"- {model['identity']}: posterior p05={cutoff['dominant_posterior_p05']:.6f}, "
            f"margin p05={cutoff['posterior_margin_p05']:.6f}; component distance uses training p99.5 (linear quantile)."
        )
    lines.extend(["", "## Prevalence comparison", ""])
    for model in models:
        training = model["training_distribution"]
        historical = model["historical_distribution"]
        lines.append(
            f"- {model['identity']}: training counts/shares={training['counts']} / {training['shares']}; "
            f"historical counts/shares={historical['counts']} / {historical['shares']}; "
            f"historical-training deltas={historical['prevalence_delta_vs_training']}."
        )
    lines.extend(["", "## Clipping and quarterly warnings", ""])
    for model in models:
        historical = model["historical"]
        warnings = historical["quarter_warnings"]
        warning_text = "; ".join(
            f"{row['quarter']} (zero={','.join(row['zero_count_fingerprints']) or 'none'}; "
            f"concentrated={','.join(row['concentrated_fingerprints']) or 'none'})"
            for row in warnings
        ) or "none"
        clipped = historical["envelope"]["clipped_dimension_quantiles"]
        lines.append(
            f"- {model['identity']}: pre-clipping envelope share="
            f"{historical['envelope']['any_feature_exceedance_share']:.6f}; "
            f"clipped dimensions p50/p95/max={clipped['p50']}/{clipped['p95']}/{clipped['max']}; "
            f"14-quarter warnings: {warning_text}."
        )
    lines.extend([
        "", "## Research preference", "",
        f"Preferred for research comparison only: **{payload['preferred_research_model']}**.",
        f"Rationale: {payload['preference_rule']}.",
        "", "## Limitations", "",
        "- Reverse-time out-of-sample replay; it is not forward validation.",
        "- Three-day feature windows overlap, so 1,274 rows are not independent; ESS and moving-block bootstrap are reported.",
        "- Fourteen calendar quarters are inspected for empty or concentrated clusters.",
        "- No strategy outcomes were read or evaluated.",
        "- No runtime thresholds were created, no model was refit, and no production model was selected.",
        "- Clipping, JSD, confidence tails, ESS, and quarter warnings are descriptive research diagnostics.",
        "",
    ])
    return "\n".join(lines)


def write_reports_atomic(payload: Mapping[str, object], *, json_path: Path, markdown_path: Path) -> None:
    _validate_distinct_destinations(json_path, markdown_path)
    write_bytes_pair_atomic(
        canonical_json_bytes(payload), render_markdown(payload).encode("utf-8"),
        first_path=json_path, second_path=markdown_path,
    )


def run(args: argparse.Namespace) -> dict[str, object]:
    source = load_historical_replay_source(args.source_report, expected_sha256=args.expected_source_sha256)
    historical, historical_provenance = load_three_day_feature_history(
        symbol=args.symbol, start=args.historical_start, end=args.historical_end,
        raw_root=args.raw_kline_root, expected_anchor_count=HISTORICAL_SAMPLE_COUNT,
    )
    training, training_provenance = load_three_day_feature_history(
        symbol=args.symbol, start=args.training_start, end=args.training_end,
        raw_root=args.raw_kline_root, expected_anchor_count=TRAINING_SAMPLE_COUNT,
    )
    return build_report(
        symbol=args.symbol, historical_start=args.historical_start, historical_end=args.historical_end,
        training_start=args.training_start, training_end=args.training_end, source=source,
        historical_vectors=historical, historical_provenance=historical_provenance,
        training_vectors=training, training_provenance=training_provenance,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = run(args)
    write_reports_atomic(report, json_path=args.output_json, markdown_path=args.output_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
