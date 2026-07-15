"""Deterministic reverse-time replay of fixed three-day BTC regime fits."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.chart_regime_balance_diagnostic import canonical_json_bytes
from src.application.services.regime_historical_replay import (
    build_confidence_reference,
    diagnose_gmm_assignments,
    rank_historical_replay_candidates,
    summarize_historical_replay_candidate,
)
from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
    load_three_day_feature_history,
)
from src.infrastructure.regime.historical_replay_source import (
    HistoricalReplaySource,
    load_historical_replay_source,
)


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


def _model_payload(identity, fit, reference, result) -> dict[str, object]:
    return {
        "identity": identity,
        "config": _plain(fit.config),
        "fingerprints": list(fit.fingerprints),
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
        "historical": _plain(result),
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
    historical = tuple(historical_vectors)
    training = tuple(training_vectors)
    if len(historical) != HISTORICAL_SAMPLE_COUNT or len(training) != TRAINING_SAMPLE_COUNT:
        raise ValueError("replay vector counts must be exactly 1,274 historical and 727 training")

    models = []
    results = []
    for identity in ("gmm-diag-k4", "gmm-diag-k8"):
        fit = source.fits[identity]
        training_diagnostics = diagnose_gmm_assignments(fit, training, source.registry)
        historical_diagnostics = diagnose_gmm_assignments(fit, historical, source.registry)
        reference = build_confidence_reference(training_diagnostics, fit.fingerprints)
        counts = source.training_counts[identity]
        training_shares = {name: counts[name] / TRAINING_SAMPLE_COUNT for name in fit.fingerprints}
        result = summarize_historical_replay_candidate(
            identity=identity, fit=fit, vectors=historical,
            diagnostics=historical_diagnostics, reference=reference,
            training_shares=training_shares,
        )
        results.append(result)
        models.append(_model_payload(identity, fit, reference, result))
    ranked = rank_historical_replay_candidates(results)
    report = {
        "kind": "three_day_regime_historical_replay",
        "version": REPORT_VERSION,
        "symbol": symbol,
        "historical_interval": {"start_inclusive": _z(historical_start), "end_exclusive": _z(historical_end)},
        "training_reference_interval": {"start_inclusive": _z(training_start), "end_exclusive": _z(training_end)},
        "historical_sample_count": len(historical),
        "training_reference_sample_count": len(training),
        "source_report_sha256": source.report_sha256,
        "archive_provenance": {
            "historical": _plain(tuple(historical_provenance)),
            "training_reference": _plain(tuple(training_provenance)),
        },
        "models": models,
        "research_preference": [item.identity for item in ranked],
        "preferred_research_model": ranked[0].identity,
        "preference_rule": "lexicographic: clipping, margin-tail, distance-tail, quarter warnings, negative minimum ESS, JSD, K, identity",
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
        "| Model | Clip share | Posterior tail | Margin tail | Distance tail | JSD | Min ESS | Quarter warnings |",
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


def _same_destination(left: Path, right: Path) -> bool:
    a, b = Path(left), Path(right)
    if a == b or os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b)):
        return True
    try:
        return a.resolve(strict=False) == b.resolve(strict=False)
    except OSError:
        return False


def write_reports_atomic(payload: Mapping[str, object], *, json_path: Path, markdown_path: Path) -> None:
    if _same_destination(json_path, markdown_path):
        raise ValueError("JSON and Markdown destinations must be distinct")
    json_bytes = canonical_json_bytes(payload)
    markdown_bytes = render_markdown(payload).encode("utf-8")
    finals = (Path(json_path), Path(markdown_path))
    temps: list[Path] = []
    backups: dict[Path, Path] = {}
    published: set[Path] = set()
    try:
        for final, content in zip(finals, (json_bytes, markdown_bytes)):
            final.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=f".{final.name}.", suffix=".tmp", dir=final.parent)
            temp = Path(name); temps.append(temp)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
        for final in finals:
            if final.exists():
                fd, name = tempfile.mkstemp(prefix=f".{final.name}.", suffix=".bak", dir=final.parent)
                os.close(fd); backup = Path(name); backup.unlink()
                final.replace(backup); backups[final] = backup
        for temp, final in zip(tuple(temps), finals):
            temp.replace(final); temps.remove(temp); published.add(final)
    except BaseException:
        for final in finals:
            try:
                if final in published:
                    final.unlink(missing_ok=True)
                if final in backups:
                    backups[final].replace(final)
                    backups.pop(final, None)
            except BaseException:
                pass
        raise
    finally:
        for path in (*temps, *backups.values()):
            try: path.unlink(missing_ok=True)
            except OSError: pass


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
