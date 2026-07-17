from __future__ import annotations

import hashlib
import json
import math
import mmap
import argparse
import csv
import os
import sys
import tempfile
import zipfile
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.stats import chi2
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score, silhouette_score
from collections import OrderedDict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum, auto
from pathlib import Path
from io import TextIOWrapper
from types import MappingProxyType
from typing import Callable, Mapping, Sequence
from urllib.request import urlopen
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.deferred_strategy_registry import (
    ensure_candidate_group_allowed,
    ensure_candidate_ids_allowed,
    load_deferred_strategy_registry,
)
from scripts.chart_regime_balance_diagnostic import (
    validate_atomic_destinations,
    write_bytes_atomic,
)
from scripts.scheduler_driven_scalping_backtest import (
    BACKTEST_ENGINE_VERSION,
    FEE_RATE,
    SLIPPAGE_RATE,
    TIMEFRAME,
    _update_drawdown,
    SchedulerBacktestCandidate,
    PositionExitPolicy,
    alpha_entry_candidates,
    build_scheduler_candidates,
    build_strategies,
    counter_microstructure_candidates,
    discovered_metrics_candidates,
    exact_historical_candidates,
    feature_provider_config_hash,
    metrics_positioning_candidates,
    microstructure_alpha_candidates,
    multi_frequency_candidates,
    run_scheduler_driven_backtest,
    run_scheduler_driven_daily_regime_backtest,
    run_scheduler_driven_regime_backtest,
    required_warmup_candles,
    validate_unique_candidate_ids,
    default_candidate,
    candidate_payload,
)
from src.application.usecases.regime.build_strategy_mapping_usecase import (
    BuildStrategyMappingCommand,
    BuildStrategyMappingUseCase,
)
from src.application.usecases.regime.build_daily_strategy_mapping_usecase import (
    BuildDailyStrategyMappingCommand,
    BuildDailyStrategyMappingUseCase,
    select_global_fixed_daily_candidate,
    build_daily_statistical_calendar,
    reassess_daily_mapping_policy,
)
from src.application.usecases.regime.select_regime_model_usecase import (
    RegimeModelEvidence,
    SelectRegimeModelCommand,
    SelectRegimeModelUseCase,
)
from src.domain.regime.model import RegimeModelConfig
from src.domain.regime.selection import SelectionConfidenceThresholds
from src.infrastructure.regime.json_regime_artifact_repository import (
    JsonRegimeArtifactRepository,
    mapping_artifact_hash,
    model_artifact_hash,
    model_fingerprint_hash,
)
from src.infrastructure.regime.sklearn_regime_model import SklearnRegimeModel
from src.infrastructure.regime.sklearn_cluster_diagnostic import SklearnClusterDiagnostic
from src.infrastructure.regime.three_day_k4_model_artifact import (
    DISTANCE_THRESHOLD_POLICY,
    MAXIMUM_DISTANCE_EXCEEDANCE_RATE,
    ThreeDayK4ModelArtifact,
    validate_three_day_k4_source_provenance,
)
from src.infrastructure.exchange.binance.research_data.three_day_feature_history import (
    load_three_day_feature_history,
)
from src.application.services.chart_feature_extractor import ChartFeatureExtractor
from src.application.services.daily_strategy_evidence import (
    AppendOnlyEvidenceLedger,
    DAILY_EVIDENCE_CODE_VERSION,
    DAILY_EVIDENCE_KEY_FIELDS,
    DAILY_EVIDENCE_SCHEMA_VERSION,
    DailyCandidateCatalog,
    DailyEvidenceReplayContract,
    DailyEvidenceRunIdentity,
    candidate_feature_requirements,
    build_three_day_daily_candidate_manifest as _build_daily_candidate_manifest,
    run_daily_strategy_evidence as _run_daily_strategy_evidence,
    market_snapshot_hash,
)
from src.domain.market import Candle, Timeframe
from src.domain.market_feature import MarketFeatureSet, MarketFeatureValue
from src.domain.market import MarketSnapshot, Symbol
from src.domain.regime import (
    CHART_FEATURE_REGISTRY_V1,
    CHART_FEATURE_SCHEMA_VERSION,
    RegimeWalkForwardFold,
    UtcInterval,
    WeeklyEpisode,
    build_weekly_episodes,
    candidate_definition_hash,
    candidate_universe_hash,
)
from src.domain.regime import (
    THREE_DAY_CHART_FEATURE_REGISTRY_V1,
    ThreeDayChartFeatureVector,
    ThreeDayDailyResearchProfile,
    STRICT_RISK_POLICY,
    decimal_arithmetic_context,
    daily_mapping_artifact_hash,
)


_WEEK = timedelta(days=7)
THREE_DAY_PROFILE_ID = "three-day-daily-k4-v1"
THREE_DAY_OUTPUT_STEM = Path(
    "docs/backtests/chart-regime-strategy-mapping-btcusdt-3d-k4-daily"
)


class ThreeDayExperimentStage(Enum):
    INITIAL = auto()
    SOURCES_VERIFIED = auto()
    MODEL_FROZEN = auto()
    CANDIDATES_FROZEN = auto()
    MAPPING_EVIDENCE_LOADED = auto()
    INITIAL_STRICT_MAPPING_BUILT = auto()
    VALIDATION_REPORTED = auto()
    FINAL_MAPPING_FROZEN = auto()
    GLOBAL_BASELINE_FROZEN = auto()
    PRE_TEST_FROZEN = auto()
    TEST_LOADED = auto()
    COMPARISONS_RUN = auto()
    PUBLISHED = auto()


_DETERMINISTIC_STAGE_BOUNDARIES = {
    ThreeDayExperimentStage.SOURCES_VERIFIED: "2021-01-01T00:00:00Z",
    ThreeDayExperimentStage.MODEL_FROZEN: "2025-06-30T00:00:00Z",
    ThreeDayExperimentStage.CANDIDATES_FROZEN: "2025-06-30T00:00:00Z",
    ThreeDayExperimentStage.MAPPING_EVIDENCE_LOADED: "2025-07-07T00:00:00Z",
    ThreeDayExperimentStage.INITIAL_STRICT_MAPPING_BUILT: "2026-01-01T00:00:00Z",
    ThreeDayExperimentStage.VALIDATION_REPORTED: "2026-04-01T00:00:00Z",
    ThreeDayExperimentStage.FINAL_MAPPING_FROZEN: "2026-04-01T00:00:00Z",
    ThreeDayExperimentStage.GLOBAL_BASELINE_FROZEN: "2026-04-01T00:00:00Z",
    ThreeDayExperimentStage.PRE_TEST_FROZEN: "2026-04-01T00:00:00Z",
    ThreeDayExperimentStage.TEST_LOADED: "2026-04-04T00:00:00Z",
    ThreeDayExperimentStage.COMPARISONS_RUN: "2026-07-01T00:00:00Z",
    ThreeDayExperimentStage.PUBLISHED: "publication-plan-v1",
}


@dataclass
class ThreeDayExperimentState:
    stage: ThreeDayExperimentStage = ThreeDayExperimentStage.INITIAL
    events: list[tuple[str, int, str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.stage, ThreeDayExperimentStage):
            raise ValueError("three-day experiment stage is invalid")
        if not isinstance(self.events, list):
            raise ValueError("three-day experiment events must be a list")

    def advance(
        self,
        expected: ThreeDayExperimentStage,
        target: ThreeDayExperimentStage,
        event: str,
    ) -> None:
        if self.stage is not expected:
            raise RuntimeError(
                f"out-of-order three-day stage: expected {expected.name}, found {self.stage.name}"
            )
        self.stage = target
        self.events.append((
            event,
            len(self.events) + 1,
            target.name,
            _DETERMINISTIC_STAGE_BOUNDARIES[target],
        ))


def _deeply_immutable(value: object) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("freeze payload keys must be strings")
        return MappingProxyType(
            {key: _deeply_immutable(item) for key, item in sorted(value.items())}
        )
    if isinstance(value, (tuple, list)):
        return tuple(_deeply_immutable(item) for item in value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("freeze payload decimals must be finite")
        return Decimal(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("freeze payload floats must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported freeze payload value: {type(value).__name__}")


def _reject_nested_test_material(value: object, path: tuple[str, ...] = ()) -> None:
    forbidden = {
        "test", "test_results", "test_data", "test_hash", "test_provenance",
        "test_comparisons", "comparisons",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in forbidden or normalized.startswith("test_"):
                exact_path = (*path, str(key))
                if exact_path in {
                    ("model", "research_profile", "fold", "test"),
                    ("mapping", "research_profile", "fold", "test"),
                }:
                    expected_interval = ThreeDayDailyResearchProfile().canonical_payload()[
                        "fold"
                    ]["test"]
                    if not isinstance(item, Mapping) or dict(item) != expected_interval:
                        raise ValueError(
                            "pre-Test freeze Test interval metadata is not canonical"
                        )
                    continue
                raise ValueError(
                    "pre-Test freeze recursively rejects Test material at "
                    + ".".join(exact_path)
                )
            _reject_nested_test_material(item, (*path, str(key)))
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _reject_nested_test_material(item, (*path, str(index)))


@dataclass(frozen=True)
class PreTestFreeze:
    canonical_payload: Mapping[str, object]
    pre_test_freeze_hash: str

    def __post_init__(self) -> None:
        immutable = _deeply_immutable(self.canonical_payload)
        if not isinstance(immutable, Mapping):
            raise ValueError("pre-Test freeze payload must be a mapping")
        _reject_nested_test_material(immutable)
        expected = _canonical_hash(immutable)
        if self.pre_test_freeze_hash != expected:
            raise ValueError("pre-Test freeze hash is inconsistent")
        object.__setattr__(self, "canonical_payload", immutable)


def create_pre_test_freeze(
    *,
    model: Mapping[str, object],
    candidate_manifest: Mapping[str, object],
    evidence: Mapping[str, object],
    mapping: Mapping[str, object],
    global_fixed_baseline: Mapping[str, object],
    profile: Mapping[str, object],
    chronology: Mapping[str, object],
) -> PreTestFreeze:
    payload = {
        "freeze_schema_version": "three-day-pre-test-freeze-v1",
        "report_schema_version": "three-day-daily-k4-report-v1",
        "model": model,
        "candidate_manifest": candidate_manifest,
        "evidence": evidence,
        "mapping": mapping,
        "global_fixed_baseline": global_fixed_baseline,
        "profile": profile,
        "chronology": chronology,
    }
    immutable = _deeply_immutable(payload)
    return PreTestFreeze(immutable, _canonical_hash(immutable))


def load_test_after_freeze(
    *,
    state: ThreeDayExperimentState,
    freeze: PreTestFreeze | None,
    loader: Callable[[], object],
) -> object:
    if not isinstance(freeze, PreTestFreeze) or freeze.pre_test_freeze_hash != _canonical_hash(
        freeze.canonical_payload
    ):
        raise RuntimeError("validated pre-Test freeze is required before Test loading")
    if state.stage is not ThreeDayExperimentStage.PRE_TEST_FROZEN:
        raise RuntimeError("pre-Test freeze stage is required before Test loading")
    result = loader()
    if result is None:
        raise ValueError("Test loader returned no validated result")
    provenance = getattr(result, "data_provenance", None)
    if provenance is None and isinstance(result, Mapping):
        provenance = result.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("Test loader result requires validated provenance")
    supplied_hash = provenance.get("pre_test_freeze_hash")
    if (
        not isinstance(supplied_hash, str)
        or len(supplied_hash) != 64
        or any(character not in "0123456789abcdef" for character in supplied_hash)
        or supplied_hash != freeze.pre_test_freeze_hash
    ):
        raise ValueError("Test loader provenance freeze hash is missing, malformed, or incompatible")
    freeze_payload = freeze.canonical_payload
    identity_expectations = {
        "model_artifact_hash": freeze_payload.get("model", {}).get("artifact_hash"),
        "candidate_manifest_hash": freeze_payload.get("candidate_manifest", {}).get("manifest_hash"),
        "candidate_universe_hash": freeze_payload.get("candidate_manifest", {}).get("candidate_universe_hash"),
        "mapping_artifact_hash": freeze_payload.get("mapping", {}).get("artifact_hash"),
        "profile_id": freeze_payload.get("profile", {}).get("profile_id"),
    }
    for key, expected in identity_expectations.items():
        supplied = provenance.get(key)
        if expected is not None and supplied is None:
            raise ValueError(f"Test loader provenance {key} is required by freeze")
        if supplied is not None and supplied != expected:
            raise ValueError(f"Test loader provenance {key} is incompatible with freeze")
    state.advance(
        ThreeDayExperimentStage.PRE_TEST_FROZEN,
        ThreeDayExperimentStage.TEST_LOADED,
        "first_test_read",
    )
    return result


@dataclass(frozen=True)
class ThreeDayPublication:
    report_json: bytes
    report_markdown: bytes
    model_json: bytes
    mapping_json: bytes

    @property
    def report_file_hash(self) -> str:
        return hashlib.sha256(self.report_json).hexdigest()


def render_three_day_markdown(report: Mapping[str, object]) -> str:
    mapping = report.get("strict_mapping", {})
    comparisons = report.get("test_comparisons", {})
    lines = [
        "# BTCUSDT three-day K4 daily strategy mapping",
        "",
        "Descriptive research evidence only; this report does not adopt or promote a strategy.",
        "",
        f"- Pre-Test freeze: `{report.get('pre_test_freeze_hash', 'missing')}`",
        f"- Test policy: `{report.get('leakage_audit', {}).get('test_policy', 'strict') if isinstance(report.get('leakage_audit', {}), Mapping) else 'strict'}`",
        "",
        "## Frozen component mapping",
        "",
    ]
    entries = mapping.get("entries", ()) if isinstance(mapping, Mapping) else ()
    for entry in entries if isinstance(entries, (tuple, list)) else ():
        if isinstance(entry, Mapping):
            destination = entry.get("strategy_candidate_id") or "cash"
            reasons = ", ".join(str(item) for item in entry.get("rejection_reasons", ())) or "eligible"
            lines.append(f"- `{entry.get('component_fingerprint', 'unknown')}` -> `{destination}` ({reasons})")
    if not entries:
        lines.append("- No component entries were rendered.")
    lines.extend(("", "## Component and eligibility summaries", ""))
    model = report.get("model_artifact", {})
    model_gates = model.get("model_gates", {}) if isinstance(model, Mapping) else {}
    weights = model.get("weights", ()) if isinstance(model, Mapping) else ()
    fingerprints = model.get("component_fingerprints", ()) if isinstance(model, Mapping) else ()
    numeric_index = (
        model.get("numeric_index_to_fingerprint", {})
        if isinstance(model, Mapping) else {}
    )
    weight_by_component = {
        str(fingerprint): weights[index]
        for raw_index, fingerprint in numeric_index.items()
        for index in (int(raw_index),)
        if (
            isinstance(numeric_index, Mapping)
            and isinstance(weights, (tuple, list))
            and 0 <= index < len(weights)
        )
    }
    assessments = mapping.get("candidate_assessments", ()) if isinstance(mapping, Mapping) else ()
    assessments_by_component: dict[str, list[Mapping[str, object]]] = {}
    if isinstance(assessments, (tuple, list)):
        for item in assessments:
            if isinstance(item, Mapping):
                assessments_by_component.setdefault(
                    str(item.get("component_fingerprint", "unknown")), []
                ).append(item)
        eligible = sum(bool(item.get("eligible")) for item in assessments if isinstance(item, Mapping))
        rejected = sum(not bool(item.get("eligible")) for item in assessments if isinstance(item, Mapping))
        lines.append(f"- Candidate/component assessments: eligible={eligible}; rejected={rejected}")
    validation_rows = {
        str(item.get("component_fingerprint")): item
        for item in (
            report.get("validation_sensitivity", {}).get(
                "mapping_fit_frozen_entries_on_validation", ()
            )
            if isinstance(report.get("validation_sensitivity", {}), Mapping)
            else ()
        )
        if isinstance(item, Mapping)
    }
    entries_by_component = {
        str(item.get("component_fingerprint")): item
        for item in entries
        if isinstance(item, Mapping)
    }
    for fingerprint in fingerprints if isinstance(fingerprints, (tuple, list)) else ():
        component = str(fingerprint)
        component_assessments = assessments_by_component.get(component, [])
        selected = entries_by_component.get(component, {})
        selected_candidate_id = selected.get("strategy_candidate_id")
        selected_assessment = next((
            item for item in component_assessments
            if item.get("candidate_id") == selected_candidate_id
        ), {})
        validation = validation_rows.get(component, {})
        assigned_days = int(selected_assessment.get("assigned_day_count", 0))
        episodes = int(selected_assessment.get("episode_count", 0))
        closed_trades = int(selected_assessment.get("closed_trade_count", 0))
        lines.append(
            f"- `{component}`: weight={weight_by_component.get(component, 'n/a')}; "
            f"distance_threshold={model_gates.get('distance_threshold', 'n/a') if isinstance(model_gates, Mapping) else 'n/a'}; "
            f"selected={selected.get('strategy_candidate_id') or 'cash'}; "
            f"assigned_days={assigned_days}; episodes={episodes}; closed_trades={closed_trades}; "
            f"validation_lcb={validation.get('validation_corrected_lower_bound_ratio', 'n/a')}; "
            f"validation_mdd={validation.get('validation_maximum_drawdown_ratio', 'n/a')}"
        )
    lines.extend(("", "## Validation sensitivity", ""))
    sensitivity = report.get("validation_sensitivity", {})
    lines.append(
        "- Strict/tighter/looser results are descriptive: `"
        + json.dumps(_canonicalize_report(sensitivity), sort_keys=True, separators=(",", ":"))
        + "`"
    )
    lines.extend(("", "## Untouched Test comparisons", "", "| Comparison | Status | Return | Drawdown | Trades |", "|---|---:|---:|---:|---:|"))
    if isinstance(comparisons, Mapping):
        for label, result in sorted(comparisons.items()):
            row = result if isinstance(result, Mapping) else {}
            metrics = row.get("continuous_metrics", row) if isinstance(row, Mapping) else {}
            lines.append(
                f"| `{label}` | {row.get('status', 'missing')} | "
                f"{metrics.get('return_ratio', 'n/a')} | "
                f"{metrics.get('portfolio_max_drawdown_ratio', metrics.get('max_drawdown_ratio', 'n/a'))} | "
                f"{metrics.get('trade_count', row.get('trade_count', 0))} |"
            )
    lines.extend(("", "## Active-exit, concentration, and adoption", ""))
    lines.append(
        "- Active-exit numeric delta (active-opposite minus entry-owner): `"
        + json.dumps(_canonicalize_report(report.get("active_exit_effect", {})), sort_keys=True)
        + "`"
    )
    lines.append(f"- Concentration audit: `{json.dumps(_canonicalize_report(report.get('concentration_audit', {})), sort_keys=True)}`")
    lines.append(f"- Adoption assessment: `{json.dumps(_canonicalize_report(report.get('adoption_assessment', {})), sort_keys=True)}`")
    lines.extend((
        "",
        "## Limitations",
        "",
        "- Sensitivity policies are descriptive and never select the untouched Test policy.",
        "- Test evidence cannot change the frozen model, mapping, candidates, or fixed baseline.",
        "- Adoption remains unadopted or inconclusive unless every stated credibility gate is met.",
        "",
    ))
    return "\n".join(lines)


def render_three_day_publication(
    *, report: Mapping[str, object], model_json: bytes, mapping_json: bytes
) -> ThreeDayPublication:
    if not isinstance(model_json, bytes) or not isinstance(mapping_json, bytes):
        raise TypeError("canonical model and mapping artifacts must be bytes")
    normalized = _canonicalize_report(report)
    if not isinstance(normalized, Mapping):
        raise ValueError("three-day report must be a mapping")
    markdown = render_three_day_markdown(normalized).encode("utf-8")
    envelope = dict(normalized)
    envelope["publication"] = {
        "hash_definition": (
            "report_payload_hash covers the canonical report excluding publication metadata; "
            "byte hashes cover the exact companion file bytes"
        ),
        "report_payload_hash": _canonical_hash(normalized),
        "model_byte_hash": hashlib.sha256(model_json).hexdigest(),
        "mapping_byte_hash": hashlib.sha256(mapping_json).hexdigest(),
        "markdown_byte_hash": hashlib.sha256(markdown).hexdigest(),
    }
    report_json = (
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    return ThreeDayPublication(report_json, markdown, model_json, mapping_json)


THREE_DAY_TEST_COMPARISON_LABELS = (
    "cash",
    "current_adopted_fixed",
    "pre_test_global_best_fixed",
    "k4_dynamic_entry_owner_exit",
    "k4_dynamic_active_strategy_opposite_exit",
    "existing_manual_regime_router",
)


def run_six_three_day_test_comparisons(
    *,
    test_inputs: object,
    model: object,
    mapping: object,
    candidate_manifest: object,
    global_fixed_candidate: object | None,
    candidates: Sequence[object],
    resolve_current_adopted: Callable[[], object],
    cash_runner: Callable[..., Mapping[str, object]],
    static_runner: Callable[..., Mapping[str, object]],
    dynamic_runner: Callable[..., Mapping[str, object]],
    manual_router_runner: Callable[..., Mapping[str, object]],
    cost_config: Mapping[str, object],
    initial_equity: Decimal,
) -> dict[str, object]:
    """Dispatch the six untouched-Test comparisons over one shared snapshot."""

    if not isinstance(initial_equity, Decimal) or not initial_equity.is_finite() or initial_equity <= 0:
        raise ValueError("comparison initial equity must be a finite positive Decimal")
    common = {
        "test_inputs": test_inputs,
        "cost_config": cost_config,
        "initial_equity": initial_equity,
    }
    results: dict[str, object] = {}
    results["cash"] = cash_runner(**common)
    try:
        adopted = resolve_current_adopted()
    except (LookupError, OSError, RuntimeError, ValueError) as error:
        results["current_adopted_fixed"] = {
            "status": "failed_baseline",
            "reason": str(error),
            "substitution_used": False,
        }
    else:
        adopted_payload = (
            candidate_payload(adopted)
            if isinstance(adopted, SchedulerBacktestCandidate)
            else _freeze_boundary_payload(adopted)
        )
        results["current_adopted_fixed"] = static_runner(
            **common,
            candidate=adopted,
            candidate_definition_hash=_canonical_hash(adopted_payload),
        )
    if global_fixed_candidate is None:
        results["pre_test_global_best_fixed"] = cash_runner(**common)
    else:
        results["pre_test_global_best_fixed"] = static_runner(
            **common, candidate=global_fixed_candidate
        )
    dynamic_common = {
        **common,
        "model": model,
        "mapping": mapping,
        "candidate_manifest": candidate_manifest,
        "candidates": tuple(candidates),
    }
    results["k4_dynamic_entry_owner_exit"] = dynamic_runner(
        **dynamic_common,
        position_exit_policy=PositionExitPolicy.ENTRY_OWNER_ONLY,
    )
    results["k4_dynamic_active_strategy_opposite_exit"] = dynamic_runner(
        **dynamic_common,
        position_exit_policy=PositionExitPolicy.ACTIVE_STRATEGY_OPPOSITE,
    )
    results["existing_manual_regime_router"] = manual_router_runner(**common)
    if tuple(results) != THREE_DAY_TEST_COMPARISON_LABELS:
        raise RuntimeError("Test comparison labels or order drifted")
    return results


def _comparison_metric(row: object, name: str) -> Decimal | None:
    if not isinstance(row, Mapping):
        return None
    value = row.get(name)
    nested = row.get("continuous_metrics")
    if value is None and isinstance(nested, Mapping):
        value = nested.get(name)
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def build_three_day_comparison_audits(
    comparisons: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    with decimal_arithmetic_context():
        return _build_three_day_comparison_audits(comparisons)


def _build_three_day_comparison_audits(
    comparisons: Mapping[str, object]
) -> tuple[dict[str, object], dict[str, object]]:
    primary = comparisons.get("k4_dynamic_active_strategy_opposite_exit", {})
    owner = comparisons.get("k4_dynamic_entry_owner_exit", {})
    primary_trades = tuple(primary.get("trades", ())) if isinstance(primary, Mapping) else ()
    daily: dict[str, Decimal] = {}
    positive_trades = []
    for trade in primary_trades:
        if not isinstance(trade, Mapping):
            continue
        try:
            pnl = Decimal(str(trade.get("net_pnl", "0")))
        except (InvalidOperation, TypeError):
            continue
        if not pnl.is_finite():
            continue
        exit_at = str(trade.get("exit_at", "unknown"))[:10]
        daily[exit_at] = daily.get(exit_at, Decimal(0)) + pnl
        if pnl > 0:
            positive_trades.append(pnl)
    positive_days = tuple(value for value in daily.values() if value > 0)
    day_total = sum(positive_days, Decimal(0))
    trade_total = sum(positive_trades, Decimal(0))
    top_day_share = max(positive_days) / day_total if day_total else Decimal(0)
    top_five_share = (
        sum(sorted(positive_trades, reverse=True)[:5], Decimal(0)) / trade_total
        if trade_total else Decimal(0)
    )
    concentration = {
        "source": "k4_dynamic_active_strategy_opposite_exit",
        "profit_basis": "positive daily net PnL and positive closed-trade net PnL",
        "positive_day_count": len(positive_days),
        "positive_trade_count": len(positive_trades),
        "top_day_profit_share": str(top_day_share),
        "top_day_profit_share_threshold": str(
            STRICT_RISK_POLICY.maximum_top_episode_profit_share
        ),
        "top_day_profit_share_passed": (
            bool(positive_days)
            and top_day_share <= STRICT_RISK_POLICY.maximum_top_episode_profit_share
        ),
        "top_episode_profit_share": str(top_day_share),
        "top_episode_profit_share_threshold": str(
            STRICT_RISK_POLICY.maximum_top_episode_profit_share
        ),
        "top_episode_profit_share_passed": (
            bool(positive_days)
            and top_day_share <= STRICT_RISK_POLICY.maximum_top_episode_profit_share
        ),
        "top_five_trade_profit_share": str(top_five_share),
        "top_five_trade_profit_share_threshold": str(
            STRICT_RISK_POLICY.maximum_top_five_trade_profit_share
        ),
        "top_five_trade_profit_share_passed": (
            bool(positive_trades)
            and top_five_share <= STRICT_RISK_POLICY.maximum_top_five_trade_profit_share
        ),
    }
    def count(row, reason=None):
        trades = tuple(row.get("trades", ())) if isinstance(row, Mapping) else ()
        return sum(
            1 for trade in trades
            if isinstance(trade, Mapping)
            and (reason is None or trade.get("exit_reason") == reason)
        )
    primary_return = _comparison_metric(primary, "return_ratio") or Decimal(0)
    owner_return = _comparison_metric(owner, "return_ratio") or Decimal(0)
    primary_drawdown = (
        _comparison_metric(primary, "portfolio_max_drawdown_ratio")
        or _comparison_metric(primary, "max_drawdown_ratio") or Decimal(0)
    )
    owner_drawdown = (
        _comparison_metric(owner, "portfolio_max_drawdown_ratio")
        or _comparison_metric(owner, "max_drawdown_ratio") or Decimal(0)
    )
    primary_trade_count = count(primary)
    owner_trade_count = count(owner)
    primary_active_exit_count = count(primary, "active_strategy_opposite_signal")
    owner_active_exit_count = count(owner, "active_strategy_opposite_signal")
    active_effect = {
        "comparison": (
            "k4_dynamic_active_strategy_opposite_exit minus "
            "k4_dynamic_entry_owner_exit"
        ),
        "return_ratio_delta": str(primary_return - owner_return),
        "maximum_drawdown_ratio_delta": str(primary_drawdown - owner_drawdown),
        "active_strategy_opposite_trade_count": primary_trade_count,
        "entry_owner_trade_count": owner_trade_count,
        "trade_count_delta": primary_trade_count - owner_trade_count,
        "active_strategy_opposite_exit_count": primary_active_exit_count,
        "entry_owner_active_strategy_opposite_exit_count": owner_active_exit_count,
        "active_strategy_opposite_exit_count_delta": (
            primary_active_exit_count - owner_active_exit_count
        ),
    }
    return concentration, active_effect


def assess_three_day_adoption(
    comparisons: Mapping[str, object],
    concentration_audit: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Describe untouched-Test credibility without mutating any adopted state."""
    reasons = []
    required = (
        "cash", "current_adopted_fixed", "pre_test_global_best_fixed",
        "k4_dynamic_active_strategy_opposite_exit",
    )
    rows = {name: comparisons.get(name) for name in required}
    if any(not isinstance(rows[name], Mapping) for name in required):
        reasons.append("required_comparison_missing")
    if any(
        isinstance(rows[name], Mapping) and rows[name].get("status") in {"failed", "failed_baseline"}
        for name in ("current_adopted_fixed", "pre_test_global_best_fixed")
    ):
        reasons.append("required_baseline_failed")

    primary = rows["k4_dynamic_active_strategy_opposite_exit"]
    primary_return = _comparison_metric(primary, "return_ratio")
    baseline_returns = tuple(_comparison_metric(rows[name], "return_ratio") for name in required[:3])
    drawdown = _comparison_metric(primary, "max_drawdown_ratio")
    if drawdown is None:
        drawdown = _comparison_metric(primary, "portfolio_max_drawdown_ratio")
    if primary_return is None or any(value is None for value in baseline_returns):
        reasons.append("insufficient_return_evidence")
    else:
        if primary_return <= 0:
            reasons.append("dynamic_primary_not_positive")
        if any(primary_return <= value for value in baseline_returns if value is not None):
            reasons.append("no_credible_improvement_over_required_baselines")
    if drawdown is None:
        reasons.append("insufficient_drawdown_evidence")
    elif drawdown > STRICT_RISK_POLICY.maximum_drawdown_ratio:
        reasons.append("unacceptable_drawdown")
    if concentration_audit is not None and not all(
        concentration_audit.get(key) is True
        for key in (
            "top_episode_profit_share_passed",
            "top_five_trade_profit_share_passed",
        )
    ):
        reasons.append("unacceptable_or_insufficient_concentration")
    credible = not reasons
    return {
        "status": "unadopted" if credible else "inconclusive",
        "adopted": False,
        "credible_improvement": credible,
        "reasons": reasons or ["descriptive_only_no_automatic_adoption"],
        "runtime_mutated": False,
    }


def write_three_day_publication_atomic(
    *,
    report_json: bytes,
    report_markdown: bytes,
    model_json: bytes,
    mapping_json: bytes,
    output_json: Path | str,
    output_markdown: Path | str,
    output_model: Path | str,
    output_mapping: Path | str,
) -> None:
    """Publish the report and both canonical artifacts as one transaction."""

    write_bytes_atomic(
        (
            (Path(output_json), report_json),
            (Path(output_markdown), report_markdown),
            (Path(output_model), model_json),
            (Path(output_mapping), mapping_json),
        )
    )


@dataclass(frozen=True)
class ThreeDayExperimentDependencies:
    verify_sources: Callable[[], object]
    fit_and_freeze_model: Callable[[object], object]
    freeze_candidates: Callable[[], object]
    load_mapping_evidence: Callable[..., object]
    build_strict_mapping: Callable[..., object]
    load_validation_evidence: Callable[..., object]
    report_validation_sensitivity: Callable[..., object]
    rebuild_final_strict_mapping: Callable[..., object]
    select_global_fixed_baseline: Callable[..., object]
    load_test: Callable[[PreTestFreeze], object]
    run_test_comparisons: Callable[..., object]
    publish: Callable[..., object]

    def __post_init__(self) -> None:
        if any(
            not callable(getattr(self, name))
            for name in self.__dataclass_fields__
        ):
            raise ValueError("three-day experiment dependencies must be callable")


@dataclass(frozen=True)
class ThreeDayPhaseEvidence:
    phase: str
    rows: tuple[object, ...]
    calendar: tuple[datetime, ...]
    assignments: tuple[str, ...]
    run_identity: DailyEvidenceRunIdentity
    ledger_path: Path
    ledger_hash: str
    archive_descriptors: tuple[Mapping[str, object], ...] = ()
    vector_provenance: tuple[Mapping[str, object], ...] = ()
    feature_provenance: Mapping[str, object] = field(default_factory=dict)
    feature_source_coverage: Mapping[str, object] = field(default_factory=dict)
    feature_unavailable_counts: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for descriptor in self.archive_descriptors:
            source_url = descriptor.get("source_url") if isinstance(descriptor, Mapping) else None
            member_name = descriptor.get("member_name") if isinstance(descriptor, Mapping) else None
            byte_count = descriptor.get("byte_count") if isinstance(descriptor, Mapping) else None
            sha256 = descriptor.get("sha256") if isinstance(descriptor, Mapping) else None
            parsed_url = urlparse(source_url) if isinstance(source_url, str) else None
            if (
                not isinstance(descriptor, Mapping)
                or not {"source_url", "member_name", "byte_count", "sha256"}
                <= set(descriptor)
                or parsed_url is None
                or parsed_url.scheme != "https"
                or not parsed_url.netloc
                or not isinstance(member_name, str)
                or not member_name
                or member_name != member_name.strip()
                or not isinstance(byte_count, int)
                or isinstance(byte_count, bool)
                or byte_count < 0
                or not isinstance(sha256, str)
                or len(sha256) != 64
                or any(character not in "0123456789abcdef" for character in sha256)
            ):
                raise ValueError("archive descriptor URL, member, bytes, or SHA256 is invalid")
        expected_hashes = {
            "feature_provenance_hash": self.feature_provenance,
            "feature_source_coverage_hash": self.feature_source_coverage,
            "feature_unavailable_counts_hash": self.feature_unavailable_counts,
        }
        for name, payload in expected_hashes.items():
            expected = getattr(self.run_identity, name, None)
            if expected != _canonical_hash(payload):
                raise ValueError(f"phase evidence {name} is inconsistent")

    def canonical_payload(self) -> dict[str, object]:
        ordered_rows = sorted(
            self.rows,
            key=lambda row: (row.outcome_start_at, row.candidate_id),
        )
        archives = list(self.archive_descriptors)
        vectors = list(self.vector_provenance)
        feature_provenance = dict(self.feature_provenance)
        source_coverage = dict(self.feature_source_coverage)
        unavailable_counts = dict(self.feature_unavailable_counts)
        return {
            "phase": self.phase,
            "run_identity": self.run_identity.canonical_payload(),
            "run_identity_hash": self.run_identity.digest,
            "ledger_path": self.ledger_path.as_posix(),
            "ledger_hash": self.ledger_hash,
            "archive_descriptors": archives,
            "archive_descriptor_hash": _canonical_hash(archives),
            "vector_provenance": vectors,
            "vector_provenance_hash": _canonical_hash(vectors),
            "feature_provenance": feature_provenance,
            "feature_provenance_hash": _canonical_hash(feature_provenance),
            "feature_source_coverage": source_coverage,
            "feature_source_coverage_hash": _canonical_hash(source_coverage),
            "feature_unavailable_counts": unavailable_counts,
            "feature_unavailable_counts_hash": _canonical_hash(unavailable_counts),
            "row_count": len(self.rows),
            "calendar_count": len(self.calendar),
            "assignment_hash": _canonical_hash(list(self.assignments)),
            "calendar_rows": [
                {
                    "outcome_start_at": day.isoformat().replace("+00:00", "Z"),
                    "component_fingerprint": component,
                    "role": self.phase,
                }
                for day, component in zip(self.calendar, self.assignments)
            ],
            "component_assignments": list(self.assignments),
            "daily_evidence_rows": [row.canonical_payload() for row in ordered_rows],
            "unavailable_row_count": sum(
                row.availability_status == "unavailable" for row in ordered_rows
            ),
            "available_row_count": sum(
                row.availability_status == "available" for row in ordered_rows
            ),
        }


class ThreeDayModelGateFailure(RuntimeError):
    def __init__(self, outcome: ThreeDayK4FitOutcome):
        super().__init__("three-day K4 model gates failed")
        self.outcome = outcome


def verify_three_day_experiment_sources(args: argparse.Namespace) -> dict[str, object]:
    if args.symbol != "BTCUSDT":
        raise ValueError("three-day profile supports BTCUSDT only")
    if args.evidence_rows_path is None and not (args.dry_run or args.manifest_only):
        raise ValueError("normal three-day execution requires --evidence-rows-path")
    return {
        "profile": ThreeDayDailyResearchProfile().canonical_payload(),
        "candidate_factory_registry": "canonical-eight-groups-v1",
        "raw_kline_root": Path(args.raw_kline_root).as_posix(),
        "feature_cache_root": None if args.feature_cache_root is None else Path(args.feature_cache_root).as_posix(),
    }


def _phase_ledger_path(base: Path, phase: str) -> Path:
    label = phase.replace("_", "-")
    return base.with_name(f"{base.stem}-{label}{base.suffix or '.jsonl'}")


def _single_archive_member_name(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = tuple(name for name in archive.namelist() if not name.endswith("/"))
    if len(names) != 1:
        raise ValueError(f"archive must contain exactly one data member: {path.name}")
    return names[0]


def _load_exact_minute_market(
    *, symbol: str, raw_kline_root: Path, start_at: datetime, end_at: datetime
) -> tuple[MarketSnapshot, list[dict[str, object]]]:
    candles = []
    archives = []
    expected = start_at
    for month in _month_starts(start_at, end_at):
        url = _archive_url(symbol, month)
        path = raw_kline_root / symbol / Path(url).name
        sha256, expected_sha256, checksum_url = _ensure_archive(path, url)
        archives.append({
            "path": path.as_posix(), "source_url": url, "sha256": sha256,
            "expected_sha256": expected_sha256, "checksum_url": checksum_url,
            "size": path.stat().st_size,
            "byte_count": path.stat().st_size,
            "member_name": _single_archive_member_name(path),
        })
        for candle in _archive_candles(path, symbol, start_at=start_at, end_at=end_at):
            if candle.opened_at != expected:
                raise ValueError("three-day phase OHLCV contains a gap, duplicate, or reversal")
            expected = candle.closed_at
            candles.append(candle)
    if expected != end_at:
        raise ValueError("three-day phase OHLCV coverage is incomplete")
    return MarketSnapshot(tuple(candles)), archives


def load_three_day_phase_evidence(
    args: argparse.Namespace,
    *,
    phase: str,
    model: ThreeDayK4ModelArtifact,
    candidate_manifest: object,
) -> ThreeDayPhaseEvidence:
    profile = ThreeDayDailyResearchProfile()
    interval = getattr(profile.fold, phase)
    vectors, vector_provenance = load_three_day_feature_history(
        symbol=args.symbol,
        start=interval.start_at - timedelta(days=3),
        end=interval.end_at,
        raw_root=Path(args.raw_kline_root),
        expected_anchor_count=(interval.end_at - interval.start_at).days,
    )
    assignments = tuple(model.assign(vector).fingerprint for vector in vectors)
    calendar = tuple(vector.anchor_at for vector in vectors)
    candidates = tuple(entry.candidate for entry in candidate_manifest.entries)
    warmup = required_warmup_candles(candidates, None)
    market_start = interval.start_at - timedelta(minutes=warmup)
    market, archives = _load_exact_minute_market(
        symbol=args.symbol, raw_kline_root=Path(args.raw_kline_root),
        start_at=market_start, end_at=interval.end_at,
    )
    provider, cache_provenance = _select_feature_cache(
        args.feature_cache_root, required_start=market_start,
        required_end=interval.end_at, verify_full_file=True,
    )
    provider_provenance = getattr(provider, "feature_provenance", cache_provenance)
    provider_coverage = getattr(provider, "feature_source_coverage", {})
    unavailable = getattr(provider, "feature_unavailable_counts", {})
    identity = DailyEvidenceRunIdentity(
        profile_id=profile.profile_id,
        feature_schema_version=vectors[0].schema_version,
        phase=phase,
        phase_start_at=interval.start_at,
        phase_end_at=interval.end_at,
        model_artifact_hash=model.artifact_hash,
        candidate_manifest_hash=candidate_manifest.manifest_hash,
        candidate_universe_hash=candidate_manifest.candidate_universe_hash,
        ordered_candidate_definition_hashes=candidate_manifest.ordered_definition_hashes,
        market_data_hash=market_snapshot_hash(market),
        feature_cache_hash=getattr(provider, "feature_cache_hash", None),
        feature_config_hash=feature_provider_config_hash(provider),
        feature_cache_schema_version=str(getattr(provider, "feature_schema_version", "none-v1")),
        feature_provenance_hash=_canonical_hash(provider_provenance),
        feature_source_coverage_hash=_canonical_hash(provider_coverage),
        feature_unavailable_counts_hash=_canonical_hash(unavailable),
        engine_version=BACKTEST_ENGINE_VERSION,
        cost_model=canonical_daily_evidence_replay_contract().cost_model,
        symbol=args.symbol, timeframe="1m", initial_equity=Decimal("10000"),
        code_version=DAILY_EVIDENCE_CODE_VERSION,
        evidence_schema_version=DAILY_EVIDENCE_SCHEMA_VERSION,
    )
    ledger_path = _phase_ledger_path(Path(args.evidence_rows_path), phase)
    if ledger_path.exists() and not args.resume:
        raise ValueError(f"evidence ledger exists; use --resume: {ledger_path}")
    ledger = AppendOnlyEvidenceLedger(ledger_path, DAILY_EVIDENCE_KEY_FIELDS)
    rows = []
    for day, component in zip(calendar, assignments):
        rows.extend(run_daily_strategy_evidence(
            manifest=candidate_manifest, phase=phase,
            outcome_start_at=day, component_fingerprint=component,
            market=market, market_feature_provider=provider,
            run_identity=identity, ledger=ledger,
        ))
    ledger_hash = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    close = getattr(provider, "close", None)
    if callable(close):
        close()
    return ThreeDayPhaseEvidence(
        phase, tuple(rows), calendar, assignments, identity, ledger_path, ledger_hash,
        tuple(archives), tuple(vector_provenance), dict(provider_provenance),
        dict(provider_coverage), dict(unavailable),
    )


def load_three_day_mapping_evidence(args, *, model, candidate_manifest):
    return load_three_day_phase_evidence(
        args, phase="mapping_fit", model=model, candidate_manifest=candidate_manifest
    )


def load_three_day_validation_evidence(args, *, model, candidate_manifest):
    return load_three_day_phase_evidence(
        args, phase="validation", model=model, candidate_manifest=candidate_manifest
    )


def _mapping_command(model, manifest, *bundles: ThreeDayPhaseEvidence):
    phases = {bundle.phase for bundle in bundles}
    if phases == {"validation"}:
        plan = tuple(
            item for item in build_daily_statistical_calendar(include_validation=True)
            if item.role == "validation"
        )
    else:
        plan = build_daily_statistical_calendar(
            include_validation="validation" in phases
        )
    assignment_by_day = {
        day: assignment
        for bundle in bundles
        for day, assignment in zip(bundle.calendar, bundle.assignments)
    }
    return BuildDailyStrategyMappingCommand(
        model_artifact_hash=model.artifact_hash,
        candidate_manifest=manifest.ordered_definition_hashes,
        frozen_component_fingerprints=tuple(model.component_fingerprints),
        calendar=tuple(item.day for item in plan),
        component_assignments=tuple(
            None if item.role == "purge" else assignment_by_day[item.day]
            for item in plan
        ),
        evidence_rows=tuple(row for bundle in bundles for row in bundle.rows),
        calendar_roles=tuple(item.role for item in plan),
        evidence_intervals=tuple(
            (
                bundle.phase,
                getattr(ThreeDayDailyResearchProfile().fold, bundle.phase),
            )
            for bundle in sorted(bundles, key=lambda item: item.phase)
        ),
        evidence_ledger_identities=tuple(
            (bundle.phase, bundle.ledger_hash, bundle.run_identity.digest)
            for bundle in sorted(bundles, key=lambda item: item.phase)
        ),
    )


def build_three_day_strict_mapping(*, model, candidate_manifest, evidence, risk_policy):
    if risk_policy != STRICT_RISK_POLICY:
        raise ValueError("canonical mapping build requires strict policy")
    return BuildDailyStrategyMappingUseCase().execute(
        _mapping_command(model, candidate_manifest, evidence)
    ).artifact


def rebuild_three_day_final_mapping(
    *, model, candidate_manifest, mapping_evidence, validation_evidence, risk_policy
):
    if risk_policy != STRICT_RISK_POLICY:
        raise ValueError("final mapping rebuild requires strict policy")
    return BuildDailyStrategyMappingUseCase().execute(
        _mapping_command(model, candidate_manifest, mapping_evidence, validation_evidence)
    ).artifact


def report_three_day_validation_sensitivity(
    *, frozen_mapping, model, candidate_manifest, mapping_evidence,
    validation_evidence, strict_policy, sensitivity_policies
):
    validation_mapping = BuildDailyStrategyMappingUseCase().execute(
        _mapping_command(model, candidate_manifest, validation_evidence)
    ).artifact
    combined_mapping = BuildDailyStrategyMappingUseCase().execute(
        _mapping_command(model, candidate_manifest, mapping_evidence, validation_evidence)
    ).artifact
    policies = {"strict": strict_policy, **dict(sensitivity_policies)}
    scopes = {
        "mapping_fit": frozen_mapping,
        "validation": validation_mapping,
        "combined": combined_mapping,
    }
    frozen_validation = []
    validation_assessments = {
        (item.component_fingerprint, item.candidate_id): item
        for item in validation_mapping.candidate_assessments
    }
    for entry in frozen_mapping.entries:
        item = (
            None if entry.strategy_candidate_id is None else
            validation_assessments.get((entry.component_fingerprint, entry.strategy_candidate_id))
        )
        frozen_validation.append({
            "component_fingerprint": entry.component_fingerprint,
            "frozen_candidate_id": entry.strategy_candidate_id,
            "validation_status": "cash" if item is None else "assessed",
            "validation_corrected_lower_bound_ratio": None if item is None else str(item.corrected_lower_bound_ratio),
            "validation_maximum_drawdown_ratio": None if item is None else str(item.maximum_drawdown_ratio),
            "validation_rejection_reasons": [] if item is None else list(item.rejection_reasons),
        })
    return {
        "policies": {
            name: {
                scope: reassess_daily_mapping_policy(artifact, policy)
                for scope, artifact in scopes.items()
            }
            for name, policy in sorted(policies.items())
        },
        "mapping_fit_frozen_entries_on_validation": frozen_validation,
        "selection_effect": "descriptive_only_final_and_test_remain_combined_strict",
    }


def select_three_day_global_baseline(
    *, candidate_manifest, mapping_evidence, validation_evidence, risk_policy
):
    return select_global_fixed_daily_candidate(
        candidate_manifest=candidate_manifest.ordered_definition_hashes,
        evidence_rows=mapping_evidence.rows + validation_evidence.rows,
        risk_policy=risk_policy,
    )


def load_three_day_test_inputs(args, freeze: PreTestFreeze):
    if not isinstance(freeze, PreTestFreeze):
        raise RuntimeError("validated freeze is required for Test inputs")
    profile = ThreeDayDailyResearchProfile()
    interval = profile.fold.test
    context_start = interval.start_at - timedelta(days=3)
    market, archives = _load_exact_minute_market(
        symbol=args.symbol, raw_kline_root=Path(args.raw_kline_root),
        start_at=context_start, end_at=interval.end_at,
    )
    provider, cache = _select_feature_cache(
        args.feature_cache_root, required_start=context_start,
        required_end=interval.end_at, verify_full_file=True,
    )
    provenance = {
        "archives": archives,
        "archive_set_hash": _canonical_hash(archives),
        "coverage": {
            "start_at": context_start.isoformat(), "end_at": interval.end_at.isoformat(),
            "gaps": [],
        },
        "feature_cache": cache,
        "classification_context_days": 3,
        "pre_test_freeze_hash": freeze.pre_test_freeze_hash,
        "model_artifact_hash": freeze.canonical_payload["model"].get("artifact_hash"),
        "candidate_manifest_hash": freeze.canonical_payload["candidate_manifest"].get("manifest_hash"),
        "candidate_universe_hash": freeze.canonical_payload["candidate_manifest"].get("candidate_universe_hash"),
        "mapping_artifact_hash": freeze.canonical_payload["mapping"].get("artifact_hash"),
        "profile_id": freeze.canonical_payload["profile"].get("profile_id"),
    }
    return TestReplayInputs(market, provenance, provider)


def _three_day_cash_result(**kwargs) -> dict[str, object]:
    initial = kwargs["initial_equity"]
    return {
        "status": "completed", "candidate_id": "cash",
        "initial_equity": str(initial), "final_equity": str(initial),
        "return_ratio": "0", "max_drawdown_ratio": "0", "trade_count": 0,
        "trades": [], "equity_curve": [],
    }


def _three_day_static_result(**kwargs):
    inputs = kwargs["test_inputs"]
    interval = ThreeDayDailyResearchProfile().fold.test
    return run_scheduler_driven_backtest(
        inputs.market,
        context_start_at=interval.start_at - timedelta(days=3),
        start_at=interval.start_at, end_at=interval.end_at,
        candidate=kwargs["candidate"], market_feature_provider=inputs.market_feature_provider,
        initial_equity=kwargs["initial_equity"], include_trade_details=True,
        force_close_at_end=True, include_deferred=True,
    )


def _three_day_dynamic_result(**kwargs):
    inputs = kwargs["test_inputs"]
    interval = ThreeDayDailyResearchProfile().fold.test
    return run_scheduler_driven_daily_regime_backtest(
        inputs.market, start_at=interval.start_at, end_at=interval.end_at,
        candidates=kwargs["candidates"], model_artifact=kwargs["model"],
        mapping_artifact=kwargs["mapping"],
        position_exit_policy=kwargs["position_exit_policy"],
        candidate_manifest=kwargs["candidate_manifest"],
        market_feature_provider=inputs.market_feature_provider,
        initial_equity=kwargs["initial_equity"], include_deferred=True,
        force_close_at_end=True,
    )


def _three_day_manual_result(**kwargs):
    return _three_day_static_result(**kwargs, candidate=_manual_router_candidate())


def run_concrete_three_day_test_comparisons(
    *, test_inputs, model, mapping, global_fixed_baseline, risk_policy,
    candidate_manifest,
):
    if risk_policy != STRICT_RISK_POLICY:
        raise ValueError("untouched Test requires strict policy")
    candidates = tuple(entry.candidate for entry in candidate_manifest.entries)
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    global_candidate = (
        None if global_fixed_baseline.decision == "cash"
        else by_id[global_fixed_baseline.candidate_id]
    )
    return run_six_three_day_test_comparisons(
        test_inputs=test_inputs, model=model, mapping=mapping,
        candidate_manifest=candidate_manifest,
        global_fixed_candidate=global_candidate, candidates=candidates,
        resolve_current_adopted=default_candidate,
        cash_runner=_three_day_cash_result, static_runner=_three_day_static_result,
        dynamic_runner=_three_day_dynamic_result,
        manual_router_runner=_three_day_manual_result,
        cost_config=canonical_daily_evidence_replay_contract().cost_model,
        initial_equity=Decimal("10000"),
    )


def _canonical_daily_mapping_bytes(mapping) -> bytes:
    payload = dict(mapping.canonical_payload())
    payload["artifact_hash"] = daily_mapping_artifact_hash(mapping)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def publish_three_day_outputs(args, *, report, model, mapping) -> dict[str, str]:
    rendered = render_three_day_publication(
        report=report, model_json=model.to_json().encode("utf-8"),
        mapping_json=_canonical_daily_mapping_bytes(mapping),
    )
    write_three_day_publication_atomic(
        report_json=rendered.report_json, report_markdown=rendered.report_markdown,
        model_json=rendered.model_json, mapping_json=rendered.mapping_json,
        output_json=args.output_json, output_markdown=args.output_markdown,
        output_model=args.output_model, output_mapping=args.output_mapping,
    )
    return {
        "report_file_hash": rendered.report_file_hash,
        "model_file_hash": hashlib.sha256(rendered.model_json).hexdigest(),
        "mapping_file_hash": hashlib.sha256(rendered.mapping_json).hexdigest(),
        "markdown_file_hash": hashlib.sha256(rendered.report_markdown).hexdigest(),
    }


def build_three_day_experiment_dependencies(args) -> ThreeDayExperimentDependencies:
    sources: dict[str, object] = {}
    manifest_holder: dict[str, object] = {}

    def verify():
        result = verify_three_day_experiment_sources(args)
        sources.update(result)
        return result

    def fit(verified):
        outcome = load_and_fit_fold_local_three_day_k4_model(
            raw_root=Path(args.raw_kline_root),
            code_provenance_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        )
        if outcome.artifact is None:
            raise ThreeDayModelGateFailure(outcome)
        return outcome.artifact

    def manifest():
        value = build_three_day_daily_candidate_manifest(expected_count=459)
        if len(value.entries) != 459:
            raise ValueError("three-day candidate manifest must contain exactly 459 candidates")
        manifest_holder["value"] = value
        return manifest_holder["value"]

    def publish(**kwargs):
        return publish_three_day_outputs(args, **kwargs)

    return ThreeDayExperimentDependencies(
        verify_sources=verify,
        fit_and_freeze_model=fit,
        freeze_candidates=manifest,
        load_mapping_evidence=lambda **kw: load_three_day_mapping_evidence(args, **kw),
        build_strict_mapping=build_three_day_strict_mapping,
        load_validation_evidence=lambda **kw: load_three_day_validation_evidence(args, **kw),
        report_validation_sensitivity=report_three_day_validation_sensitivity,
        rebuild_final_strict_mapping=rebuild_three_day_final_mapping,
        select_global_fixed_baseline=select_three_day_global_baseline,
        load_test=lambda freeze: load_three_day_test_inputs(args, freeze),
        run_test_comparisons=lambda **kw: run_concrete_three_day_test_comparisons(
            **kw, candidate_manifest=manifest_holder["value"]
        ),
        publish=publish,
    )


def _publish_model_failure(args, failure: ThreeDayModelGateFailure) -> None:
    reason = list(failure.outcome.rejection_reasons) or ["fixed-k4-model-gates"]
    report = {
        "schema_version": "three-day-daily-k4-report-v1",
        "status": "failed-model-cash", "rejection_reasons": reason,
        "test_comparisons": {},
        "leakage_audit": {"test_loader_called": False, "adoption_status": "inconclusive"},
    }
    model = (json.dumps({"kind": "cash_only", "reason": reason}, sort_keys=True) + "\n").encode()
    mapping = (json.dumps({"kind": "cash_only", "reason": reason}, sort_keys=True) + "\n").encode()
    rendered = render_three_day_publication(report=report, model_json=model, mapping_json=mapping)
    write_three_day_publication_atomic(
        report_json=rendered.report_json, report_markdown=rendered.report_markdown,
        model_json=model, mapping_json=mapping,
        output_json=args.output_json, output_markdown=args.output_markdown,
        output_model=args.output_model, output_mapping=args.output_mapping,
    )


def run_three_day_profile_main(args) -> int:
    if args.dry_run or args.manifest_only:
        plan = verify_three_day_experiment_sources(args)
        manifest = build_three_day_daily_candidate_manifest(expected_count=459)
        print(json.dumps({
            "profile": THREE_DAY_PROFILE_ID,
            "candidate_count": len(manifest.entries),
            "candidate_manifest_hash": manifest.manifest_hash,
            "mode": "manifest" if args.manifest_only else "dry-run",
        }, sort_keys=True))
        return 0
    try:
        report = run_three_day_daily_k4_experiment(
            dependencies=build_three_day_experiment_dependencies(args)
        )
    except ThreeDayModelGateFailure as failure:
        _publish_model_failure(args, failure)
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        print(f"three-day experiment failed: {error}")
        return 1
    print(json.dumps({
        "output_json": str(args.output_json),
        "output_markdown": str(args.output_markdown),
        "output_model": str(args.output_model),
        "output_mapping": str(args.output_mapping),
        "pre_test_freeze_hash": report["pre_test_freeze_hash"],
        "report_file_hash": hashlib.sha256(Path(args.output_json).read_bytes()).hexdigest(),
    }, sort_keys=True))
    return 0


def _freeze_boundary_payload(value: object) -> Mapping[str, object]:
    canonical = getattr(value, "canonical_payload", None)
    if callable(canonical):
        payload = canonical()
    elif all(
        hasattr(value, name)
        for name in (
            "entries", "candidate_ids", "ordered_definition_hashes",
            "candidate_universe_hash", "manifest_hash",
        )
    ):
        payload = {
            "candidate_count": len(value.entries),
            "candidate_ids": list(value.candidate_ids),
            "ordered_definition_hashes": [list(item) for item in value.ordered_definition_hashes],
            "candidate_universe_hash": value.candidate_universe_hash,
            "manifest_hash": value.manifest_hash,
            "entries": [
                {
                    "candidate_id": entry.candidate_id,
                    "definition_hash": entry.definition_hash,
                    "canonical_candidate_payload": dict(entry.canonical_candidate_payload),
                    "required_feature_alternatives": entry.required_feature_alternatives,
                    "deferred_groups": entry.deferred_groups,
                    "deferred_pattern_provenance": entry.deferred_pattern_provenance,
                }
                for entry in value.entries
            ],
        }
    elif isinstance(value, Mapping):
        payload = value
    else:
        payload = {
            "type": type(value).__name__,
            "artifact_hash": getattr(value, "artifact_hash", None),
        }
    if not isinstance(payload, Mapping):
        raise ValueError("freeze boundary must supply a canonical mapping")
    return payload


def run_three_day_daily_k4_experiment(
    *,
    dependencies: ThreeDayExperimentDependencies,
    state: ThreeDayExperimentState | None = None,
) -> dict[str, object]:
    """Execute the explicit K4 research profile across a hard pre-Test barrier.

    The dependency surface deliberately separates pre-Test functions from the
    Test loader and comparison runner: no pre-Test callable accepts Test data.
    """

    if not isinstance(dependencies, ThreeDayExperimentDependencies):
        raise ValueError("three-day experiment dependencies are required")
    current = state or ThreeDayExperimentState()
    sources = dependencies.verify_sources()
    current.advance(
        ThreeDayExperimentStage.INITIAL,
        ThreeDayExperimentStage.SOURCES_VERIFIED,
        "sources_verified",
    )
    model = dependencies.fit_and_freeze_model(sources)
    current.advance(
        ThreeDayExperimentStage.SOURCES_VERIFIED,
        ThreeDayExperimentStage.MODEL_FROZEN,
        "model_frozen",
    )
    manifest = dependencies.freeze_candidates()
    current.advance(
        ThreeDayExperimentStage.MODEL_FROZEN,
        ThreeDayExperimentStage.CANDIDATES_FROZEN,
        "candidate_manifest_frozen",
    )
    mapping_evidence = dependencies.load_mapping_evidence(
        model=model, candidate_manifest=manifest
    )
    current.advance(
        ThreeDayExperimentStage.CANDIDATES_FROZEN,
        ThreeDayExperimentStage.MAPPING_EVIDENCE_LOADED,
        "mapping_evidence_loaded",
    )
    initial_mapping = dependencies.build_strict_mapping(
        model=model,
        candidate_manifest=manifest,
        evidence=mapping_evidence,
        risk_policy=STRICT_RISK_POLICY,
    )
    current.advance(
        ThreeDayExperimentStage.MAPPING_EVIDENCE_LOADED,
        ThreeDayExperimentStage.INITIAL_STRICT_MAPPING_BUILT,
        "initial_strict_mapping_built",
    )
    validation_evidence = dependencies.load_validation_evidence(
        model=model, candidate_manifest=manifest
    )
    sensitivity = dependencies.report_validation_sensitivity(
        frozen_mapping=initial_mapping,
        model=model,
        candidate_manifest=manifest,
        mapping_evidence=mapping_evidence,
        validation_evidence=validation_evidence,
        strict_policy=STRICT_RISK_POLICY,
        sensitivity_policies=ThreeDayDailyResearchProfile().sensitivity_policies,
    )
    current.advance(
        ThreeDayExperimentStage.INITIAL_STRICT_MAPPING_BUILT,
        ThreeDayExperimentStage.VALIDATION_REPORTED,
        "validation_sensitivity_reported",
    )
    final_mapping = dependencies.rebuild_final_strict_mapping(
        model=model,
        candidate_manifest=manifest,
        mapping_evidence=mapping_evidence,
        validation_evidence=validation_evidence,
        risk_policy=STRICT_RISK_POLICY,
    )
    current.advance(
        ThreeDayExperimentStage.VALIDATION_REPORTED,
        ThreeDayExperimentStage.FINAL_MAPPING_FROZEN,
        "final_strict_mapping_frozen",
    )
    global_baseline = dependencies.select_global_fixed_baseline(
        candidate_manifest=manifest,
        mapping_evidence=mapping_evidence,
        validation_evidence=validation_evidence,
        risk_policy=STRICT_RISK_POLICY,
    )
    current.advance(
        ThreeDayExperimentStage.FINAL_MAPPING_FROZEN,
        ThreeDayExperimentStage.GLOBAL_BASELINE_FROZEN,
        "global_fixed_baseline_frozen",
    )
    profile = ThreeDayDailyResearchProfile()
    profile_payload = profile.canonical_payload()
    pretest_profile_payload = dict(profile_payload)
    pretest_profile_payload["fold"] = {
        name: value
        for name, value in profile_payload["fold"].items()
        if name != "test"
    }
    freeze_mapping_payload = dict(_freeze_boundary_payload(final_mapping))
    if hasattr(final_mapping, "candidate_assessments"):
        freeze_mapping_payload["artifact_hash"] = daily_mapping_artifact_hash(final_mapping)
    freeze = create_pre_test_freeze(
        model=_freeze_boundary_payload(model),
        candidate_manifest=_freeze_boundary_payload(manifest),
        evidence={
            "mapping": _freeze_boundary_payload(mapping_evidence),
            "validation": _freeze_boundary_payload(validation_evidence),
        },
        mapping=freeze_mapping_payload,
        global_fixed_baseline=_freeze_boundary_payload(global_baseline),
        profile=pretest_profile_payload,
        chronology=pretest_profile_payload["fold"],
    )
    current.advance(
        ThreeDayExperimentStage.GLOBAL_BASELINE_FROZEN,
        ThreeDayExperimentStage.PRE_TEST_FROZEN,
        "pre_test_freeze_created",
    )
    test_inputs = load_test_after_freeze(
        state=current,
        freeze=freeze,
        loader=lambda: dependencies.load_test(freeze),
    )
    comparisons = dependencies.run_test_comparisons(
        test_inputs=test_inputs,
        model=model,
        mapping=final_mapping,
        global_fixed_baseline=global_baseline,
        risk_policy=STRICT_RISK_POLICY,
    )
    current.advance(
        ThreeDayExperimentStage.TEST_LOADED,
        ThreeDayExperimentStage.COMPARISONS_RUN,
        "test_comparisons_run",
    )
    concentration_audit, active_exit_effect = build_three_day_comparison_audits(
        comparisons
    )
    test_provenance = getattr(test_inputs, "data_provenance", None)
    if test_provenance is None and isinstance(test_inputs, Mapping):
        test_provenance = test_inputs.get("provenance", {})
    final_mapping_payload = _freeze_boundary_payload(final_mapping)
    final_mapping_hash = (
        daily_mapping_artifact_hash(final_mapping)
        if hasattr(final_mapping, "candidate_assessments")
        else final_mapping_payload.get("artifact_hash")
    )
    fold_payload = profile_payload["fold"]
    assignment_by_day = {}
    for bundle in (mapping_evidence, validation_evidence):
        if isinstance(bundle, ThreeDayPhaseEvidence):
            assignment_by_day.update(zip(bundle.calendar, bundle.assignments))
    statistical_calendar = [
        {
            "day": item.day.isoformat().replace("+00:00", "Z"),
            "role": item.role,
            "component_fingerprint": assignment_by_day.get(item.day),
        }
        for item in build_daily_statistical_calendar(include_validation=True)
    ]
    report = {
        "schema_version": "three-day-daily-k4-report-v1",
        "profile": profile_payload,
        "intervals": fold_payload,
        "purges": [
            {"start_at": "2025-06-30T00:00:00Z", "end_at": "2025-07-07T00:00:00Z", "days": 7},
            {"start_at": "2026-01-01T00:00:00Z", "end_at": "2026-01-04T00:00:00Z", "days": 3},
            {"start_at": "2026-04-01T00:00:00Z", "end_at": "2026-04-04T00:00:00Z", "days": 3},
        ],
        "statistical_calendar": statistical_calendar,
        "source_verification": _freeze_boundary_payload(sources),
        "candidate_manifest": _freeze_boundary_payload(manifest),
        "model_artifact": _freeze_boundary_payload(model),
        "evidence": {
            "mapping_fit": _freeze_boundary_payload(mapping_evidence),
            "validation": _freeze_boundary_payload(validation_evidence),
        },
        "pre_test_freeze_hash": freeze.pre_test_freeze_hash,
        "strict_mapping": final_mapping_payload,
        "strict_mapping_artifact_hash": final_mapping_hash,
        "global_fixed_baseline": _freeze_boundary_payload(global_baseline),
        "validation_sensitivity": sensitivity,
        "test_provenance": _canonicalize_report(test_provenance or {}),
        "test_comparisons": comparisons,
        "adoption_assessment": assess_three_day_adoption(
            comparisons, concentration_audit
        ),
        "concentration_audit": concentration_audit,
        "active_exit_effect": active_exit_effect,
        "selection_and_exit_audits": {
            "preserved_in_full_dynamic_comparisons": True,
            "policies": ["entry_owner_only", "active_strategy_opposite"],
        },
        "safety": {
            "runtime_config_mutated": False,
            "registry_mutated": False,
            "automatic_promotion": False,
            "test_policy": "strict",
        },
        "leakage_audit": {
            "test_loaded_after_freeze": True,
            "test_policy": "strict",
            "test_excluded_from_freeze": True,
        },
        "events": tuple(current.events),
        "publication_plan": {
            "artifact_count": 4,
            "transaction": "atomic-four-file-v1",
        },
        "limitations": [
            "Research-only evidence; no live adoption or runtime mutation.",
            "Sensitivity policies are descriptive and never select the Test policy.",
            "Test observations are excluded from the pre-Test freeze identity.",
        ],
    }
    dependencies.publish(
        report=report,
        model=model,
        mapping=final_mapping,
    )
    current.advance(
        ThreeDayExperimentStage.COMPARISONS_RUN,
        ThreeDayExperimentStage.PUBLISHED,
        "published",
    )
    return report


def _canonical_daily_candidate_groups():
    return {
        "all": build_scheduler_candidates(),
        "alpha": alpha_entry_candidates(),
        "counter": counter_microstructure_candidates(),
        "discovered": discovered_metrics_candidates(),
        "exact": exact_historical_candidates(),
        "metrics": metrics_positioning_candidates(),
        "microstructure": microstructure_alpha_candidates(),
        "multi": multi_frequency_candidates(),
    }


def build_three_day_daily_candidate_manifest(*, candidate_groups=None, expected_count=459):
    groups = _canonical_daily_candidate_groups() if candidate_groups is None else candidate_groups
    catalog = DailyCandidateCatalog(
        candidate_groups=groups,
        deferred_registry=load_deferred_strategy_registry(),
        candidate_id_validator=lambda ids: ensure_candidate_ids_allowed(ids, include_deferred=True),
        candidate_payload_builder=candidate_payload,
    )
    return _build_daily_candidate_manifest(catalog=catalog, expected_count=expected_count)


def canonical_daily_evidence_replay_contract(*, replay_callable=None):
    return DailyEvidenceReplayContract(
        replay=replay_callable or run_scheduler_driven_backtest,
        engine_name="scheduler_driven",
        engine_version=BACKTEST_ENGINE_VERSION,
        cost_model={
            "venue": "binance_usd_m_futures",
            "fee_rate_per_side": str(FEE_RATE),
            "slippage_rate_per_side": str(SLIPPAGE_RATE),
            "funding_fee": "excluded",
        },
        timeframe=TIMEFRAME,
        timeframe_label="1m",
        warmup_resolver=required_warmup_candles,
    )


def run_daily_strategy_evidence(*, replay_callable=None, **kwargs):
    return _run_daily_strategy_evidence(
        replay_contract=canonical_daily_evidence_replay_contract(replay_callable=replay_callable),
        **kwargs,
    )
_SUMMARY_DECIMAL_FIELDS = (
    "initial_equity",
    "final_equity",
    "trades_per_day",
    "gross_pnl",
    "net_pnl",
    "fee_paid",
    "return_ratio",
    "daily_return_ratio",
    "max_drawdown_ratio",
    "net_win_rate",
    "average_net_trade_roe",
    "average_net_trade_expectancy_ratio",
)
_TRADE_DECIMAL_FIELDS = (
    "entry_price",
    "exit_price",
    "quantity",
    "margin",
    "gross_pnl",
    "net_pnl",
    "fee_paid",
)
_CANDIDATE_FACTORIES = {
    "all": build_scheduler_candidates,
    "exact": exact_historical_candidates,
    "alpha": alpha_entry_candidates,
    "multi": multi_frequency_candidates,
    "microstructure": microstructure_alpha_candidates,
    "counter": counter_microstructure_candidates,
    "metrics": metrics_positioning_candidates,
    "discovered": discovered_metrics_candidates,
}


def run_mapping_episodes(
    market: MarketSnapshot,
    *,
    episodes: Sequence[WeeklyEpisode],
    assignments: Mapping[datetime, str],
    candidate_groups: Sequence[str] = (),
    candidate_ids: Sequence[str] = (),
    include_deferred_groups: Sequence[str] = (),
    candidates: Sequence[SchedulerBacktestCandidate] | None = None,
    initial_equity: Decimal = Decimal("10000"),
    symbol: Symbol | None = None,
    market_feature_provider=None,
) -> list[dict[str, object]]:
    """Collect independent weekly candidate evidence through the real scheduler simulator."""
    normalized_episodes = _validate_episodes(episodes)
    cluster_by_anchor = _validate_assignments(normalized_episodes, assignments)
    resolved, allow_deferred = _resolve_candidates(
        candidates=candidates,
        candidate_groups=candidate_groups,
        candidate_ids=candidate_ids,
        include_deferred_groups=include_deferred_groups,
    )
    if not isinstance(initial_equity, Decimal) or not initial_equity.is_finite() or initial_equity <= 0:
        raise ValueError("initial_equity must be a finite positive Decimal")
    selected_symbol = symbol or market.symbol
    if selected_symbol != market.symbol:
        raise ValueError("symbol must match the execution market symbol")
    if market.timeframe != TIMEFRAME:
        raise ValueError("execution market timeframe must be exactly 1m")

    warmup_candles = required_warmup_candles(resolved, market_feature_provider)
    candidate_hashes = {
        candidate.candidate_id: _canonical_hash(
            {
                "engine_version": BACKTEST_ENGINE_VERSION,
                "symbol": selected_symbol.pair,
                "initial_equity": initial_equity,
                "fee_rate_per_side": FEE_RATE,
                "slippage_rate_per_side": SLIPPAGE_RATE,
                "account_risk": {
                    "base_risk_ratio": Decimal("0.02"),
                    "max_total_exposure_ratio": Decimal("1"),
                    "max_symbol_exposure_ratio": Decimal("1"),
                },
                "candidate": _candidate_behavior_payload(candidate),
            }
        )
        for candidate in resolved
    }

    rows: list[dict[str, object]] = []
    for episode in normalized_episodes:
        context_start_at = episode.start_at - timedelta(minutes=warmup_candles)
        sliced = _slice_episode(market, episode, context_start_at=context_start_at)
        market_payload_hash = _canonical_hash(
            {
                "context_start_at": context_start_at.isoformat(),
                "execution_start_at": episode.start_at.isoformat(),
                "execution_end_at": episode.end_at.isoformat(),
                "market": _market_payload(sliced),
            }
        )
        for candidate in resolved:
            result = run_scheduler_driven_backtest(
                sliced,
                context_start_at=context_start_at,
                start_at=episode.start_at,
                end_at=episode.end_at,
                candidate=candidate,
                symbol=selected_symbol,
                market_feature_provider=market_feature_provider,
                include_deferred=allow_deferred,
                initial_equity=initial_equity,
                include_trade_details=True,
                force_close_at_end=True,
            )
            validated = _validate_backtest_evidence(
                result,
                candidate=candidate,
                initial_equity=initial_equity,
                market_feature_provider=market_feature_provider,
                episode=episode,
            )
            feature_identity = {
                "feature_cache_hash": validated["feature_cache_hash"],
                "feature_config_hash": validated["feature_config_hash"],
                "feature_provenance": validated["feature_provenance"],
            }
            data_hash = _canonical_hash(
                {"market_payload_hash": market_payload_hash, "feature_identity": feature_identity}
            )
            row = {
                "context_start_at": context_start_at.isoformat(),
                "episode_start_at": episode.start_at.isoformat(),
                "episode_end_at": episode.end_at.isoformat(),
                "cluster_fingerprint": cluster_by_anchor[episode.anchor_at],
                "candidate_id": candidate.candidate_id,
                "market_context_hash": market_payload_hash,
                "data_hash": data_hash,
                "candidate_hash": candidate_hashes[candidate.candidate_id],
            }
            row.update(validated)
            rows.append(row)
    return rows


def _resolve_candidates(
    *,
    candidates: Sequence[SchedulerBacktestCandidate] | None,
    candidate_groups: Sequence[str],
    candidate_ids: Sequence[str],
    include_deferred_groups: Sequence[str],
) -> tuple[tuple[SchedulerBacktestCandidate, ...], bool]:
    if candidates is not None:
        if candidate_groups or candidate_ids or include_deferred_groups:
            raise ValueError("direct candidates cannot be combined with factory selection")
        resolved = validate_unique_candidate_ids(tuple(candidates))
        ensure_candidate_ids_allowed(tuple(item.candidate_id for item in resolved))
        allow_deferred = False
    else:
        groups = tuple(candidate_groups)
        if not groups:
            raise ValueError("candidate_groups must be explicitly selected")
        if len(set(groups)) != len(groups):
            raise ValueError("duplicate candidate group")
        opted_in = tuple(include_deferred_groups)
        if len(set(opted_in)) != len(opted_in) or any(group not in groups for group in opted_in):
            raise ValueError("deferred opt-ins must uniquely reference selected groups")
        unknown_groups = sorted(set(groups) - set(_CANDIDATE_FACTORIES))
        if unknown_groups:
            raise ValueError(f"unknown candidate group: {', '.join(unknown_groups)}")
        built = []
        for group in groups:
            ensure_candidate_group_allowed(group, include_deferred=group in opted_in)
            built.extend(_CANDIDATE_FACTORIES[group]())
        resolved = validate_unique_candidate_ids(tuple(built))
        allow_deferred = bool(opted_in)

    requested_ids = tuple(candidate_ids)
    if len(set(requested_ids)) != len(requested_ids):
        raise ValueError("duplicate candidate_id selection")
    if requested_ids:
        by_id = {candidate.candidate_id: candidate for candidate in resolved}
        unknown_ids = sorted(set(requested_ids) - set(by_id))
        if unknown_ids:
            raise ValueError(f"unknown candidate_id: {', '.join(unknown_ids)}")
        resolved = tuple(by_id[candidate_id] for candidate_id in requested_ids)
    if not resolved:
        raise ValueError("at least one candidate is required")
    return tuple(sorted(resolved, key=lambda item: item.candidate_id)), allow_deferred


def _validate_episodes(episodes: Sequence[WeeklyEpisode]) -> tuple[WeeklyEpisode, ...]:
    normalized = tuple(episodes)
    if not normalized:
        raise ValueError("at least one weekly episode is required")
    for index, episode in enumerate(normalized):
        if not all(_is_canonical_utc(value) for value in (
            episode.anchor_at, episode.feature_start_at, episode.start_at, episode.end_at
        )):
            raise ValueError("episode timestamps must use canonical UTC")
        if not _is_monday_midnight(episode.start_at):
            raise ValueError("episode must start Monday 00:00 UTC")
        if episode.anchor_at != episode.start_at:
            raise ValueError("episode anchor must equal episode start")
        if episode.feature_start_at != episode.start_at - _WEEK:
            raise ValueError("episode feature window must be the preceding seven days")
        if episode.end_at != episode.start_at + _WEEK:
            raise ValueError("episode must span exactly seven days")
        if index and normalized[index - 1].end_at != episode.start_at:
            raise ValueError("weekly episodes must be consecutive and non-overlapping")
    return normalized


def _validate_assignments(
    episodes: tuple[WeeklyEpisode, ...], assignments: Mapping[datetime, str]
) -> dict[datetime, str]:
    expected = {episode.anchor_at for episode in episodes}
    if set(assignments) != expected:
        raise ValueError("assignments must cover exactly every episode anchor")
    result = dict(assignments)
    if any(not isinstance(value, str) or not value.strip() for value in result.values()):
        raise ValueError("cluster fingerprint must be nonempty")
    return result


def _slice_episode(
    market: MarketSnapshot,
    episode: WeeklyEpisode,
    *,
    context_start_at: datetime,
) -> MarketSnapshot:
    candles = tuple(
        candle for candle in market.candles
        if context_start_at <= candle.opened_at and candle.closed_at <= episode.end_at
    )
    if not candles or candles[0].opened_at != context_start_at or candles[-1].closed_at != episode.end_at:
        raise ValueError("episode market context or execution data is absent or incomplete")
    if any(left.closed_at != right.opened_at for left, right in zip(candles, candles[1:])):
        raise ValueError("episode market data contains a gap")
    if any(not _is_canonical_utc(value) for candle in candles for value in (candle.opened_at, candle.closed_at)):
        raise ValueError("market timestamps must use canonical UTC")
    return MarketSnapshot(candles)


def _market_payload(market: MarketSnapshot) -> dict[str, object]:
    return {
        "symbol": market.symbol.pair,
        "timeframe": market.timeframe.label,
        "candles": [
            {
                "opened_at": candle.opened_at.isoformat(),
                "closed_at": candle.closed_at.isoformat(),
                "open": candle.open_price,
                "high": candle.high_price,
                "low": candle.low_price,
                "close": candle.close_price,
                "volume": candle.volume,
            }
            for candle in market.candles
        ],
    }


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonicalize(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical hash decimals must be finite")
        normalized = "0" if value == 0 else format(value.normalize(), "f")
        return {"$decimal": normalized}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("canonical hash mapping keys must be strings")
        return {key: _canonicalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical hash floats must be finite")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported canonical hash value: {type(value).__name__}")


def _candidate_behavior_payload(candidate: SchedulerBacktestCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "take_profit_ratio": candidate.take_profit_ratio,
        "stop_loss_ratio": candidate.stop_loss_ratio,
        "equity_ratio": candidate.equity_ratio,
        "leverage": candidate.leverage,
        "candle_limit": candidate.candle_limit,
        "max_holding_bars": candidate.max_holding_bars,
        "strategies": [
            {"kind": spec.kind, "params": spec.params} for spec in candidate.strategies
        ],
        "guard": {
            "min_minutes_between_entries": candidate.guard.min_minutes_between_entries,
            "pause_minutes_after_loss": candidate.guard.pause_minutes_after_loss,
            "max_daily_loss_ratio": candidate.guard.max_daily_loss_ratio,
            "max_daily_trades": candidate.guard.max_daily_trades,
            "max_consecutive_losses": candidate.guard.max_consecutive_losses,
            "max_peak_drawdown_ratio": candidate.guard.max_peak_drawdown_ratio,
            "min_signal_confidence": candidate.guard.min_signal_confidence,
            "min_1m_range_ratio": candidate.guard.min_1m_range_ratio,
            "max_1m_range_ratio": candidate.guard.max_1m_range_ratio,
        },
    }


def _validate_backtest_evidence(
    result: object,
    *,
    candidate: SchedulerBacktestCandidate,
    initial_equity: Decimal,
    market_feature_provider,
    episode: WeeklyEpisode,
) -> dict[str, object]:
    if not isinstance(result, Mapping):
        raise ValueError("backtest evidence must be a mapping")
    required = {
        "candidate_id",
        "trade_count",
        "trades",
        "feature_cache_hash",
        "feature_provenance",
        "feature_config_hash",
        *_SUMMARY_DECIMAL_FIELDS,
    }
    missing = sorted(required - set(result))
    if missing:
        raise ValueError(f"backtest evidence missing required fields: {', '.join(missing)}")
    if result["candidate_id"] != candidate.candidate_id:
        raise ValueError("backtest evidence candidate_id mismatch")

    decimals = {
        field: _finite_decimal(result[field], field) for field in _SUMMARY_DECIMAL_FIELDS
    }
    if decimals["initial_equity"] != initial_equity:
        raise ValueError("backtest evidence initial_equity mismatch")
    if decimals["final_equity"] != decimals["initial_equity"] + decimals["net_pnl"]:
        raise ValueError("backtest evidence final_equity is inconsistent with net_pnl")
    trade_count = result["trade_count"]
    if not isinstance(trade_count, int) or isinstance(trade_count, bool) or trade_count < 0:
        raise ValueError("backtest evidence trade_count must be a nonnegative integer")
    trades = result["trades"]
    if not isinstance(trades, list):
        raise ValueError("backtest evidence trades must be a list")
    validated_trades = [
        _validate_trade(item, index, episode=episode, candidate=candidate)
        for index, item in enumerate(trades)
    ]
    if trade_count != len(validated_trades):
        raise ValueError("backtest evidence trade_count does not match trades")
    for previous, current in zip(validated_trades, validated_trades[1:]):
        if current["entry_at_value"] < previous["exit_at_value"]:
            raise ValueError(
                "backtest evidence trades must be chronological and non-overlapping"
            )
    total_gross = sum((item["gross_pnl"] for item in validated_trades), Decimal("0"))
    total_net = sum((item["net_pnl"] for item in validated_trades), Decimal("0"))
    total_fees = sum((item["fee_paid"] for item in validated_trades), Decimal("0"))
    _require_decimal_match("gross_pnl", decimals["gross_pnl"], total_gross)
    _require_decimal_match("net_pnl", decimals["net_pnl"], total_net)
    _require_decimal_match("fee_paid", decimals["fee_paid"], total_fees)
    _require_decimal_match(
        "final_equity", decimals["final_equity"], initial_equity + total_net
    )
    expected_return = total_net / initial_equity
    _require_decimal_match("return_ratio", decimals["return_ratio"], expected_return)
    _require_decimal_match(
        "daily_return_ratio",
        decimals["daily_return_ratio"],
        expected_return / Decimal("7"),
    )
    _require_decimal_match(
        "trades_per_day",
        decimals["trades_per_day"],
        Decimal(trade_count) / Decimal("7"),
    )
    wins = sum(1 for item in validated_trades if item["net_pnl"] > 0)
    expected_win_rate = Decimal(wins) / Decimal(trade_count) if trade_count else Decimal("0")
    if not Decimal("0") <= decimals["net_win_rate"] <= Decimal("1"):
        raise ValueError("backtest evidence net_win_rate must be between zero and one")
    _require_decimal_match("net_win_rate", decimals["net_win_rate"], expected_win_rate)
    expected_average_roe = (
        sum((item["net_pnl"] / item["margin"] for item in validated_trades), Decimal("0"))
        / Decimal(trade_count)
        if trade_count
        else Decimal("0")
    )
    _require_decimal_match(
        "average_net_trade_roe",
        decimals["average_net_trade_roe"],
        expected_average_roe,
    )
    expected_expectancy = (
        (total_net / Decimal(trade_count)) / initial_equity
        if trade_count
        else Decimal("0")
    )
    _require_decimal_match(
        "average_net_trade_expectancy_ratio",
        decimals["average_net_trade_expectancy_ratio"],
        expected_expectancy,
    )
    equity = initial_equity
    peak = initial_equity
    reconstructed_drawdown = Decimal("0")
    for item in validated_trades:
        equity += item["net_pnl"]
        peak, reconstructed_drawdown = _update_drawdown(
            equity=equity,
            peak=peak,
            max_drawdown=reconstructed_drawdown,
        )
    if decimals["max_drawdown_ratio"] < 0:
        raise ValueError("backtest evidence max_drawdown_ratio must be nonnegative")
    _require_decimal_match(
        "max_drawdown_ratio",
        decimals["max_drawdown_ratio"],
        reconstructed_drawdown,
    )
    profit_factor = None
    if "profit_factor" in result:
        profit_factor = _finite_decimal(result["profit_factor"], "profit_factor")
        gross_profit = sum(
            (item["gross_pnl"] for item in validated_trades if item["gross_pnl"] > 0),
            Decimal("0"),
        )
        gross_loss = -sum(
            (item["gross_pnl"] for item in validated_trades if item["gross_pnl"] < 0),
            Decimal("0"),
        )
        if gross_loss == 0 and gross_profit > 0:
            raise ValueError("backtest evidence profit_factor is unbounded without losing trades")
        expected_profit_factor = gross_profit / gross_loss if gross_loss else Decimal("0")
        _require_decimal_match("profit_factor", profit_factor, expected_profit_factor)

    feature_cache_hash = result["feature_cache_hash"]
    feature_config_hash = result["feature_config_hash"]
    feature_provenance = result["feature_provenance"]
    if not isinstance(feature_provenance, Mapping):
        raise ValueError("backtest evidence feature_provenance must be a mapping")
    if market_feature_provider is None:
        if feature_cache_hash is not None or feature_config_hash is not None or feature_provenance:
            raise ValueError("backtest evidence without a feature provider must use null feature identity")
    else:
        if not isinstance(feature_cache_hash, str) or not feature_cache_hash.strip():
            raise ValueError("backtest evidence feature_cache_hash is required")
        if feature_cache_hash != getattr(market_feature_provider, "feature_cache_hash", None):
            raise ValueError("backtest evidence feature_cache_hash mismatch")
        if not isinstance(feature_config_hash, str) or not feature_config_hash.strip():
            raise ValueError("backtest evidence feature_config_hash is required")
        if feature_config_hash != feature_provider_config_hash(market_feature_provider):
            raise ValueError("backtest evidence feature_config_hash mismatch")
        declared_provenance = getattr(market_feature_provider, "feature_provenance", None)
        if declared_provenance is not None and dict(feature_provenance) != dict(declared_provenance):
            raise ValueError("backtest evidence feature_provenance mismatch")

    validated_result = {
        "initial_equity": _decimal_text(initial_equity),
        "final_equity": _decimal_text(initial_equity + total_net),
        "trade_count": trade_count,
        "trades_per_day": _decimal_text(Decimal(trade_count) / Decimal("7")),
        "gross_pnl": _decimal_text(total_gross),
        "net_pnl": _decimal_text(total_net),
        "fee_paid": _decimal_text(total_fees),
        "return_ratio": _decimal_text(expected_return),
        "daily_return_ratio": _decimal_text(expected_return / Decimal("7")),
        "max_drawdown_ratio": _decimal_text(reconstructed_drawdown),
        "net_win_rate": _decimal_text(expected_win_rate),
        "average_net_trade_roe": _decimal_text(expected_average_roe),
        "average_net_trade_expectancy_ratio": _decimal_text(expected_expectancy),
        "trades": [item["payload"] for item in validated_trades],
        "feature_cache_hash": feature_cache_hash,
        "feature_provenance": dict(feature_provenance),
        "feature_config_hash": feature_config_hash,
    }
    if profit_factor is not None:
        validated_result["profit_factor"] = _decimal_text(profit_factor)
    return validated_result


def _validate_trade(
    value: object,
    index: int,
    *,
    episode: WeeklyEpisode,
    candidate: SchedulerBacktestCandidate,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"trade {index} must be a mapping")
    required = {
        "entry_at", "exit_at", "direction", "exit_reason", "holding_bars", *_TRADE_DECIMAL_FIELDS
    }
    missing = sorted(required - set(value))
    if missing:
        raise ValueError(f"trade {index} missing required fields: {', '.join(missing)}")
    entry_at = _parse_canonical_utc(value["entry_at"], f"trade {index} entry_at")
    exit_at = _parse_canonical_utc(value["exit_at"], f"trade {index} exit_at")
    if not episode.start_at <= entry_at < exit_at <= episode.end_at:
        raise ValueError(f"trade {index} entry_at/exit_at must stay within the episode")
    if value["direction"] not in {"long", "short"}:
        raise ValueError(f"trade {index} direction is invalid")
    if not isinstance(value["exit_reason"], str) or not value["exit_reason"].strip():
        raise ValueError(f"trade {index} exit_reason is required")
    holding_bars = value["holding_bars"]
    if not isinstance(holding_bars, int) or isinstance(holding_bars, bool) or holding_bars < 0:
        raise ValueError(f"trade {index} holding_bars must be a nonnegative integer")
    elapsed_minutes = Decimal(str((exit_at - entry_at).total_seconds())) / Decimal("60")
    if elapsed_minutes != Decimal(holding_bars):
        raise ValueError(f"trade {index} holding_bars must match its positive 1m duration")
    decimals = {
        field: _finite_decimal(value[field], f"trade {index} {field}")
        for field in _TRADE_DECIMAL_FIELDS
    }
    for field in ("entry_price", "exit_price", "quantity", "margin"):
        if decimals[field] <= 0:
            raise ValueError(f"trade {index} {field} must be positive")
    if decimals["fee_paid"] < 0:
        raise ValueError(f"trade {index} fee_paid must be nonnegative")
    expected_gross = (
        (decimals["exit_price"] - decimals["entry_price"]) * decimals["quantity"]
        if value["direction"] == "long"
        else (decimals["entry_price"] - decimals["exit_price"]) * decimals["quantity"]
    )
    _require_decimal_match(
        f"trade {index} gross_pnl",
        decimals["gross_pnl"],
        expected_gross,
    )
    expected_fee = (
        decimals["entry_price"] * decimals["quantity"]
        + decimals["exit_price"] * decimals["quantity"]
    ) * FEE_RATE
    _require_decimal_match(
        f"trade {index} fee_paid",
        decimals["fee_paid"],
        expected_fee,
    )
    expected_margin = (
        decimals["entry_price"] * decimals["quantity"] / candidate.leverage
    )
    _require_decimal_match(
        f"trade {index} margin",
        decimals["margin"],
        expected_margin,
    )
    _require_decimal_match(
        f"trade {index} net_pnl",
        decimals["net_pnl"],
        decimals["gross_pnl"] - decimals["fee_paid"],
    )
    return {
        **decimals,
        "entry_at_value": entry_at,
        "exit_at_value": exit_at,
        "payload": {
            "entry_at": entry_at.isoformat(),
            "exit_at": exit_at.isoformat(),
            "entry_price": _decimal_text(decimals["entry_price"]),
            "exit_price": _decimal_text(decimals["exit_price"]),
            "direction": value["direction"],
            "quantity": _decimal_text(decimals["quantity"]),
            "margin": _decimal_text(decimals["margin"]),
            "gross_pnl": _decimal_text(decimals["gross_pnl"]),
            "net_pnl": _decimal_text(decimals["net_pnl"]),
            "fee_paid": _decimal_text(decimals["fee_paid"]),
            "exit_reason": value["exit_reason"],
            "holding_bars": holding_bars,
        },
    }


def _require_decimal_match(field: str, actual: Decimal, expected: Decimal) -> None:
    tolerance = Decimal("1e-24")
    if abs(actual - expected) > tolerance:
        raise ValueError(f"backtest evidence {field} is inconsistent")


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _finite_decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"backtest evidence {field} must be a serialized Decimal")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"backtest evidence {field} is not a Decimal") from error
    if not parsed.is_finite():
        raise ValueError(f"backtest evidence {field} must be finite")
    return parsed


def _parse_canonical_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO UTC timestamp") from error
    if parsed.tzinfo is not timezone.utc:
        raise ValueError(f"{field} must use canonical UTC")
    return parsed


def _is_canonical_utc(value: datetime) -> bool:
    return value.tzinfo is timezone.utc


def _is_monday_midnight(value: datetime) -> bool:
    return value.weekday() == 0 and value.time() == datetime.min.time()


# The production search space is declared at import time.  Validation may select
# from it, but neither validation nor Test is allowed to alter it.
@dataclass(frozen=True)
class WalkForwardGrid:
    cluster_counts: tuple[int, ...] = (3, 4, 5, 6, 7, 8)
    model_types: tuple[str, ...] = ("kmeans", "gmm")
    gmm_covariance_types: tuple[str, ...] = ("diag", "tied")
    seeds: tuple[int, ...] = (20260714, 20260715, 20260716)
    spearman_threshold: float = 0.95
    bootstrap_resamples: tuple[int, ...] = (2000, 5000)
    confidence_levels: tuple[float, ...] = (0.90, 0.95)
    gmm_probability_mins: tuple[float, ...] = (0.55, 0.65, 0.75)
    gmm_margin_mins: tuple[float, ...] = (0.05, 0.10, 0.20)
    kmeans_distance_multipliers: tuple[float, ...] = (0.90, 1.00, 1.10)


PRODUCTION_WALK_FORWARD_GRID = WalkForwardGrid()
MAPPING_GATE_THRESHOLDS = {
    "minimum_weekly_episodes": 8,
    "minimum_distinct_months": 3,
    "minimum_trade_count": 30,
}
MODEL_GATE_THRESHOLDS = {
    "minimum_cluster_episodes": 8,
    "minimum_cluster_months": 3,
    "minimum_seed_ari": 0.8,
    "minimum_seed_nmi": 0.8,
    "maximum_matched_centroid_distance": 0.5,
    "maximum_prevalence_drift": 0.2,
    "maximum_low_confidence_rate": 0.25,
    "maximum_distance_exceedance_rate": MAXIMUM_DISTANCE_EXCEEDANCE_RATE,
}


@dataclass(frozen=True)
class ThreeDayK4FitOutcome:
    """Leakage-safe boundary consumed by later daily research stages."""

    status: str
    artifact: ThreeDayK4ModelArtifact | None
    rejection_reasons: tuple[str, ...] = ()


def _three_day_vector_hash(vectors: tuple[ThreeDayChartFeatureVector, ...]) -> str:
    return _canonical_hash(
        {
            "schema_version": vectors[0].schema_version if vectors else None,
            "registry_names": [spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1],
            "vectors": [
                {
                    "symbol": vector.symbol,
                    "anchor_at": vector.anchor_at.isoformat(),
                    "window_start_at": vector.window_start_at.isoformat(),
                    "values": list(vector.values.items()),
                }
                for vector in vectors
            ],
        }
    )


def _validate_three_day_fit_provenance(
    provenance: Sequence[Mapping[str, object]], code_provenance_hash: str
) -> tuple[Mapping[str, object], ...]:
    rows = validate_three_day_k4_source_provenance(tuple(provenance))
    if (
        not isinstance(code_provenance_hash, str)
        or len(code_provenance_hash) != 64
        or code_provenance_hash != code_provenance_hash.lower()
        or any(character not in "0123456789abcdef" for character in code_provenance_hash)
    ):
        raise ValueError("code provenance hash is invalid")
    return rows


def fit_fold_local_three_day_k4_model(
    vectors: Sequence[ThreeDayChartFeatureVector],
    *,
    source_provenance: Sequence[Mapping[str, object]],
    code_provenance_hash: str,
    diagnostic: SklearnClusterDiagnostic | None = None,
) -> ThreeDayK4FitOutcome:
    """Fit and freeze the normative K4 model using Cluster Fit anchors only.

    The callable deliberately has no strategy outcomes or later-phase loader. A
    caller may supply a history containing the three context days and later fold
    phases; only exact anchors in the frozen half-open Cluster Fit are retained.
    """
    profile = ThreeDayDailyResearchProfile()
    interval = profile.fold.cluster_fit
    history = tuple(vectors)
    if not history or any(not isinstance(vector, ThreeDayChartFeatureVector) for vector in history):
        raise ValueError("audited three-day feature history is required")
    anchors = tuple(vector.anchor_at for vector in history)
    if any(current <= previous for previous, current in zip(anchors, anchors[1:])):
        raise ValueError("feature history contains a gap, duplicate, or out-of-order anchor")
    fit_vectors = tuple(vector for vector in history if interval.start_at <= vector.anchor_at < interval.end_at)
    expected_count = (interval.end_at - interval.start_at).days
    expected_anchors = tuple(interval.start_at + timedelta(days=index) for index in range(expected_count))
    if tuple(vector.anchor_at for vector in fit_vectors) != expected_anchors:
        raise ValueError("Cluster Fit feature history has a gap or incorrect half-open coverage")
    if any(vector.window_start_at != vector.anchor_at - timedelta(days=3) for vector in fit_vectors):
        raise ValueError("Cluster Fit feature windows must exclude the anchor")
    if any(tuple(vector.values) != tuple(spec.name for spec in THREE_DAY_CHART_FEATURE_REGISTRY_V1) for vector in fit_vectors):
        raise ValueError("feature history registry is incompatible")
    validated_provenance = _validate_three_day_fit_provenance(
        source_provenance, code_provenance_hash
    )

    engine = diagnostic or SklearnClusterDiagnostic()
    config = RegimeModelConfig("gmm", 4, profile.random_seed, "diag", profile.regularization)
    try:
        primary = engine.fit(config, fit_vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
        assignments = engine.assign(primary, fit_vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
        labels = tuple(item.fingerprint for item in assignments)
        represented = set(labels) == set(primary.fingerprints)
        midpoint = len(fit_vectors) // 2
        blocks = (fit_vectors[:midpoint], fit_vectors[midpoint:])
        block_represented = all(
            set(item.fingerprint for item in engine.assign(primary, block, THREE_DAY_CHART_FEATURE_REGISTRY_V1))
            == set(primary.fingerprints)
            for block in blocks
        )
        seed_scores = []
        for seed in (profile.random_seed + 1, profile.random_seed + 2):
            refit = engine.fit(
                replace(config, random_seed=seed),
                fit_vectors,
                THREE_DAY_CHART_FEATURE_REGISTRY_V1,
                retained_feature_names=primary.feature_names,
            )
            comparison = engine.assign(refit, fit_vectors, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
            comparison_labels = tuple(item.fingerprint for item in comparison)
            seed_scores.append((
                float(adjusted_rand_score(labels, comparison_labels)),
                float(normalized_mutual_info_score(labels, comparison_labels)),
            ))
        minimum_ari = min(score[0] for score in seed_scores)
        minimum_nmi = min(score[1] for score in seed_scores)

        block_fits = tuple(
            engine.fit(
                config, block, THREE_DAY_CHART_FEATURE_REGISTRY_V1,
                retained_feature_names=primary.feature_names,
            )
            for block in blocks
        )
        maximum_centroid_distance = 0.0
        block_shares = []
        for block, block_fit in zip(blocks, block_fits):
            projected = _project_centroids_to_primary_coordinates(block_fit, primary)
            distances = np.linalg.norm(np.asarray(primary.means)[:, None, :] - projected[None, :, :], axis=2)
            rows, columns = linear_sum_assignment(distances)
            maximum_centroid_distance = max(
                maximum_centroid_distance,
                max(float(distances[row, column]) for row, column in zip(rows, columns)),
            )
            mapping = {block_fit.fingerprints[column]: primary.fingerprints[row] for row, column in zip(rows, columns)}
            block_labels = tuple(
                mapping[item.fingerprint]
                for item in engine.assign(block_fit, block, THREE_DAY_CHART_FEATURE_REGISTRY_V1)
            )
            block_shares.append({fingerprint: block_labels.count(fingerprint) / len(block_labels) for fingerprint in primary.fingerprints})
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
        distance_result = (
            distance_exceedance_rate
            <= MODEL_GATE_THRESHOLDS["maximum_distance_exceedance_rate"]
        )
        nondegenerate_confidence = low_confidence_rate <= MODEL_GATE_THRESHOLDS["maximum_low_confidence_rate"]
        passed = (
            represented and block_represented
            and minimum_ari >= MODEL_GATE_THRESHOLDS["minimum_seed_ari"]
            and minimum_nmi >= MODEL_GATE_THRESHOLDS["minimum_seed_nmi"]
            and maximum_centroid_distance <= MODEL_GATE_THRESHOLDS["maximum_matched_centroid_distance"]
            and maximum_prevalence_drift <= MODEL_GATE_THRESHOLDS["maximum_prevalence_drift"]
            and nondegenerate_confidence
            and distance_result
        )
        gates = {
            "convergence_required": True,
            "converged": primary.converged,
            "iterations": primary.iterations,
            "lower_bound": primary.lower_bound,
            "finite_scaler_required": True,
            "finite_scaler": all(math.isfinite(value) for values in (primary.lower_bounds, primary.upper_bounds, primary.medians, primary.scales) for value in values),
            "finite_model_parameters_required": True,
            "finite_model_parameters": all(math.isfinite(value) for values in (*primary.means, primary.weights, *primary.covariances) for value in values),
            "positive_weights_required": True,
            "minimum_weight": min(primary.weights),
            "weight_sum_expected": 1.0,
            "weight_sum_tolerance": 1e-8,
            "weight_sum": math.fsum(primary.weights),
            "covariance_floor_threshold": profile.regularization,
            "minimum_covariance": min(value for row in primary.covariances for value in row),
            "component_count_expected": 4,
            "component_count": len(primary.fingerprints),
            "all_components_represented_required": True,
            "minimum_adjusted_rand_index": minimum_ari,
            "minimum_adjusted_rand_index_threshold": MODEL_GATE_THRESHOLDS["minimum_seed_ari"],
            "minimum_normalized_mutual_information": minimum_nmi,
            "minimum_normalized_mutual_information_threshold": MODEL_GATE_THRESHOLDS["minimum_seed_nmi"],
            "maximum_matched_centroid_distance": maximum_centroid_distance,
            "maximum_matched_centroid_distance_threshold": MODEL_GATE_THRESHOLDS["maximum_matched_centroid_distance"],
            "maximum_prevalence_drift": maximum_prevalence_drift,
            "maximum_prevalence_drift_threshold": MODEL_GATE_THRESHOLDS["maximum_prevalence_drift"],
            "low_confidence_rate": low_confidence_rate,
            "maximum_low_confidence_rate_threshold": MODEL_GATE_THRESHOLDS["maximum_low_confidence_rate"],
            "gmm_probability_threshold": 0.65,
            "gmm_margin_threshold": 0.10,
            "minimum_observed_dominant_probability": min(item.dominant_probability for item in assignments),
            "minimum_observed_probability_margin": min(item.dominant_probability - item.second_probability for item in assignments),
            "distance_threshold": distance_threshold,
            "distance_result": distance_result,
            "distance_threshold_policy": DISTANCE_THRESHOLD_POLICY,
            "distance_exceedance_rate": distance_exceedance_rate,
            "maximum_distance_exceedance_rate_threshold": MODEL_GATE_THRESHOLDS[
                "maximum_distance_exceedance_rate"
            ],
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
            "nondegenerate_confidence": nondegenerate_confidence,
            "passed": passed,
        }
        if not passed:
            return ThreeDayK4FitOutcome("failed-model-cash", None, ("fixed-k4-model-gates",))
        vector_hash = _three_day_vector_hash(fit_vectors)
        artifact = ThreeDayK4ModelArtifact.from_fit(
            primary,
            training_start_at=interval.start_at,
            training_end_at=interval.end_at,
            first_usable_anchor_at=fit_vectors[0].anchor_at,
            last_usable_anchor_at=fit_vectors[-1].anchor_at,
            usable_anchor_count=len(fit_vectors),
            source_provenance=validated_provenance,
            feature_history_hash=vector_hash,
            fit_input_vector_hash=vector_hash,
            code_provenance_hash=code_provenance_hash,
            model_gates=gates,
        )
    except (TypeError, ValueError) as error:
        return ThreeDayK4FitOutcome("failed-model-cash", None, (str(error),))
    return ThreeDayK4FitOutcome("model-fit", artifact)


def load_and_fit_fold_local_three_day_k4_model(
    *,
    raw_root: Path,
    code_provenance_hash: str,
    symbol: str = "BTCUSDT",
    downloader=None,
    request_factory=None,
    row_reader=None,
    diagnostic: SklearnClusterDiagnostic | None = None,
) -> ThreeDayK4FitOutcome:
    """Load only the audited Cluster Fit archive span, then fit frozen K4.

    Archive reads begin three days before the first fit anchor. The loader's
    canonical episode contract therefore emits 2021-01-01 as its first vector;
    2020-12-29..31 exist solely as pre-anchor feature context.
    """
    profile = ThreeDayDailyResearchProfile()
    interval = profile.fold.cluster_fit
    kwargs = {
        "symbol": symbol,
        "start": interval.start_at - timedelta(days=3),
        "end": interval.end_at,
        "raw_root": raw_root,
        "expected_anchor_count": (interval.end_at - interval.start_at).days,
    }
    if downloader is not None:
        kwargs["downloader"] = downloader
    if request_factory is not None:
        kwargs["request_factory"] = request_factory
    if row_reader is not None:
        kwargs["row_reader"] = row_reader
    vectors, provenance = load_three_day_feature_history(**kwargs)
    return fit_fold_local_three_day_k4_model(
        vectors,
        source_provenance=provenance,
        code_provenance_hash=code_provenance_hash,
        diagnostic=diagnostic,
    )
COMPARISON_NAMES = (
    "cash",
    "adopted_fixed",
    "train_selected_fixed",
    "manual_regime_router",
    "kmeans_dynamic",
    "gmm_dynamic",
)
MANUAL_ROUTER_CANDIDATE_ID = "range-first-p2-tp0060-sl0045-e0035-l3-guard-a"


def _manual_router_candidate() -> SchedulerBacktestCandidate:
    matches = tuple(
        candidate for candidate in build_scheduler_candidates()
        if candidate.candidate_id == MANUAL_ROUTER_CANDIDATE_ID
    )
    if len(matches) != 1 or tuple(spec.kind for spec in matches[0].strategies) != ("regime_router",):
        raise ValueError("predeclared manual regime-router candidate is unavailable")
    return matches[0]


def _manual_router_for_replay(
    *, include_deferred: bool,
) -> tuple[SchedulerBacktestCandidate | None, str | None]:
    candidate = _manual_router_candidate()
    try:
        ensure_candidate_ids_allowed(
            (candidate.candidate_id,), include_deferred=include_deferred
        )
    except ValueError as error:
        return None, str(error)
    return candidate, None


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


BTCUSDT_FIRST_FOLD = RegimeWalkForwardFold(
    cluster_fit=UtcInterval(_utc("2021-01-01T00:00:00"), _utc("2025-06-30T00:00:00")),
    mapping_fit=UtcInterval(_utc("2025-07-07T00:00:00"), _utc("2026-01-05T00:00:00")),
    validation=UtcInterval(_utc("2026-01-12T00:00:00"), _utc("2026-03-30T00:00:00")),
    test=UtcInterval(_utc("2026-04-06T00:00:00"), _utc("2026-07-01T00:00:00")),
)


@dataclass(frozen=True)
class WalkForwardDependencies:
    """Stage boundary used by both production and deterministic fixture runs."""

    prepare_data: Callable[[Mapping[str, object]], Mapping[str, object]]
    build_cluster_features: Callable[[Mapping[str, object], Mapping[str, object]], Mapping[str, object]]
    evaluate_models: Callable[[Mapping[str, object], Mapping[str, object]], Mapping[str, object]]
    build_mappings: Callable[[Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object]], Mapping[str, object]]
    validate: Callable[[Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object]], Mapping[str, object]]
    replay_test: Callable[[Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object], Mapping[str, object]], Mapping[str, object]]


@dataclass(frozen=True)
class WalkForwardInputs:
    """Validated, compact boundary between archive IO and statistical stages."""

    market: MarketSnapshot
    cluster_fit_vectors: tuple[object, ...]
    mapping_vectors: tuple[object, ...]
    validation_vectors: tuple[object, ...]
    data_provenance: Mapping[str, object]
    market_feature_provider: object | None = None


@dataclass(frozen=True)
class TestReplayInputs:
    """Test-only inputs whose loader may not run before artifact freeze."""

    market: MarketSnapshot
    data_provenance: Mapping[str, object]
    market_feature_provider: object | None = None


def _default_prepare_data(context: Mapping[str, object]) -> Mapping[str, object]:
    inputs = context.get("inputs")
    if not isinstance(inputs, WalkForwardInputs):
        raise RuntimeError(
            "validated WalkForwardInputs are required; CLI archive loading did not complete"
        )
    market = inputs.market
    if market.timeframe != TIMEFRAME or market.symbol.pair != context["symbol"]:
        raise ValueError("walk-forward input market identity mismatch")
    validation: UtcInterval = context["validation"]  # type: ignore[assignment]
    pretest_candles = tuple(candle for candle in market.candles if candle.closed_at <= validation.end_at)
    if not pretest_candles:
        raise ValueError("walk-forward market does not cover pre-Test intervals")
    return {
        "market": MarketSnapshot(pretest_candles),
        "provenance": dict(inputs.data_provenance),
        "provider": inputs.market_feature_provider,
        "cluster_fit_vectors": inputs.cluster_fit_vectors,
        "mapping_vectors": inputs.mapping_vectors,
        "validation_vectors": inputs.validation_vectors,
    }


def _default_build_cluster_features(
    context: Mapping[str, object], prepared: Mapping[str, object]
) -> Mapping[str, object]:
    cluster = tuple(prepared.get("cluster_fit_vectors", ()))
    mapping = tuple(prepared.get("mapping_vectors", ()))
    validation = tuple(prepared.get("validation_vectors", ()))
    if not cluster or not mapping or not validation:
        raise ValueError("cluster, mapping, and validation feature vectors are required")
    return {
        "schema": CHART_FEATURE_SCHEMA_VERSION,
        "cluster_fit": cluster,
        "mapping_fit": mapping,
        "validation": validation,
    }


def _model_report(artifact, config_id: str, *, eligible: bool, reasons=()):
    return {
        "config_id": config_id,
        "model_type": artifact.config.model_type if artifact is not None else config_id.split(":", 1)[0],
        "cluster_count": artifact.config.cluster_count if artifact is not None else None,
        "eligible": eligible,
        "artifact_hash": model_artifact_hash(artifact) if artifact is not None else None,
        "rejection_reasons": list(reasons),
    }


def _gmm_parameter_count(cluster_count: int, dimensions: int, covariance_type: str) -> int:
    if cluster_count < 1 or dimensions < 1:
        raise ValueError("GMM parameter dimensions must be positive")
    if covariance_type == "diag":
        covariance_parameters = cluster_count * dimensions
    elif covariance_type == "tied":
        covariance_parameters = dimensions * (dimensions + 1) // 2
    else:
        raise ValueError("GMM covariance type must be diag or tied")
    return (cluster_count - 1) + cluster_count * dimensions + covariance_parameters


def _gmm_bic(log_likelihood: float, sample_count: int, parameter_count: int) -> float:
    if not math.isfinite(log_likelihood) or sample_count < 1 or parameter_count < 1:
        raise ValueError("BIC inputs must be finite and positive")
    return float(-2 * log_likelihood + parameter_count * math.log(sample_count))


def _normalize_bounded_metric(
    value: float,
    name: str,
    minimum: float,
    maximum: float,
    *,
    tolerance: float = 1e-12,
) -> tuple[float, dict[str, object]]:
    raw = float(value)
    if not math.isfinite(raw):
        raise ValueError(f"{name} must be finite")
    if raw < minimum - tolerance or raw > maximum + tolerance:
        raise ValueError(
            f"{name}={raw!r} is outside [{minimum}, {maximum}] beyond tolerance {tolerance}"
        )
    normalized = min(max(raw, minimum), maximum)
    return normalized, {
        "raw": raw,
        "normalized": normalized,
        "clamped": normalized != raw,
    }


def _chronological_block_stability(
    engine: SklearnRegimeModel,
    primary,
    cluster_fit_vectors: tuple[object, ...],
    mapping_vectors: tuple[object, ...],
) -> tuple[float, float, list[dict[str, object]]]:
    """Refit disjoint chronological halves and compare standardized profiles."""
    midpoint = len(cluster_fit_vectors) // 2
    blocks = (cluster_fit_vectors[:midpoint], cluster_fit_vectors[midpoint:])
    if any(len(block) < primary.config.cluster_count for block in blocks):
        raise ValueError("chronological blocks are too small for requested clusters")
    block_artifacts = tuple(
        engine.fit(
            primary.config,
            tuple(block),
            retained_feature_names=primary.feature_names,
        )
        for block in blocks
    )
    profiles = []
    primary_means = np.asarray(primary.means)
    matched_label_series = []
    max_distance = 0.0
    for index, artifact in enumerate(block_artifacts):
        block_means = _project_centroids_to_primary_coordinates(artifact, primary)
        distances = np.linalg.norm(primary_means[:, None, :] - block_means[None, :, :], axis=2)
        rows, columns = linear_sum_assignment(distances)
        component_to_primary = {
            artifact.fingerprints[column]: primary.fingerprints[row]
            for row, column in zip(rows, columns)
        }
        matched = [float(distances[row, column]) for row, column in zip(rows, columns)]
        max_distance = max(max_distance, max(matched))
        assignments = engine.assign(artifact, mapping_vectors)
        matched_labels = [component_to_primary[item.fingerprint] for item in assignments]
        matched_label_series.append(matched_labels)
        profiles.append({
            "block_index": index,
            "start_at": blocks[index][0].anchor_at.isoformat(),
            "end_at": blocks[index][-1].anchor_at.isoformat(),
            "matched_standardized_centroid_distances": matched,
        })
    prevalence_drift = max(
        abs(
            matched_label_series[0].count(fingerprint) / len(mapping_vectors)
            - matched_label_series[1].count(fingerprint) / len(mapping_vectors)
        )
        for fingerprint in primary.fingerprints
    )
    return max_distance, prevalence_drift, profiles


def _project_centroids_to_primary_coordinates(block_artifact, primary_artifact) -> np.ndarray:
    if block_artifact.feature_names != primary_artifact.feature_names:
        raise ValueError("centroid projection requires identical feature profiles")
    block_standardized = np.asarray(block_artifact.means, dtype=float)
    raw_feature_units = (
        block_standardized * np.asarray(block_artifact.scales, dtype=float)
        + np.asarray(block_artifact.medians, dtype=float)
    )
    clipped_to_primary = np.clip(
        raw_feature_units,
        np.asarray(primary_artifact.lower_bounds, dtype=float),
        np.asarray(primary_artifact.upper_bounds, dtype=float),
    )
    return (
        clipped_to_primary - np.asarray(primary_artifact.medians, dtype=float)
    ) / np.asarray(primary_artifact.scales, dtype=float)


def _default_evaluate_models(
    context: Mapping[str, object], features: Mapping[str, object]
) -> Mapping[str, object]:
    grid: WalkForwardGrid = context["configuration_grid"]  # type: ignore[assignment]
    engine = SklearnRegimeModel()
    vectors = tuple(features["cluster_fit"])
    failed_reports = []
    structural = {}
    for model_type in grid.model_types:
        covariance_types = (None,) if model_type == "kmeans" else grid.gmm_covariance_types
        for cluster_count in grid.cluster_counts:
            for covariance_type in covariance_types:
                fitted = []
                config_prefix = f"{model_type}:{cluster_count}:{covariance_type or 'none'}"
                for seed in grid.seeds:
                    config_id = f"{config_prefix}:{seed}"
                    try:
                        artifact = engine.fit(
                            RegimeModelConfig(
                                model_type=model_type,
                                cluster_count=cluster_count,
                                random_seed=seed,
                                covariance_type=covariance_type,
                            ),
                            vectors,
                        )
                    except (TypeError, ValueError) as error:
                        failed_reports.append(_model_report(None, config_id, eligible=False, reasons=(str(error),)))
                        continue
                    fitted.append(artifact)
                if len(fitted) == len(grid.seeds):
                    structural[config_prefix] = tuple(fitted)
    mapping_vectors = tuple(
        vector for vector in features["mapping_fit"]
        if vector.anchor_at.weekday() == 0 and vector.anchor_at.hour == 0
    )
    if not mapping_vectors:
        raise ValueError("weekly Mapping Fit feature vectors are required")
    evidences = []
    evidence_by_id = {}
    chronological_profiles_by_id = {}
    seed_metric_audits_by_id = {}
    for config_id, seed_artifacts in sorted(structural.items()):
        primary = seed_artifacts[0]
        seed_assignments = [engine.assign(artifact, mapping_vectors) for artifact in seed_artifacts]
        primary_labels = [item.fingerprint for item in seed_assignments[0]]
        weekly_counts = tuple(primary_labels.count(fp) for fp in primary.fingerprints)
        month_sets = {fp: set() for fp in primary.fingerprints}
        for vector, label in zip(mapping_vectors, primary_labels):
            month_sets[label].add((vector.anchor_at.year, vector.anchor_at.month))
        month_counts = tuple(len(month_sets[fp]) for fp in primary.fingerprints)
        aris = []
        nmis = []
        metric_audits = []
        primary_label_hash = _canonical_hash(primary_labels)
        for seed_index, values in enumerate(seed_assignments[1:], start=1):
            comparison_labels = [item.fingerprint for item in values]
            comparison_hash = _canonical_hash(comparison_labels)
            try:
                ari, ari_audit = _normalize_bounded_metric(
                    adjusted_rand_score(primary_labels, comparison_labels),
                    "seed_ari", -1.0, 1.0,
                )
                nmi, nmi_audit = _normalize_bounded_metric(
                    normalized_mutual_info_score(primary_labels, comparison_labels),
                    "seed_nmi", 0.0, 1.0,
                )
            except ValueError as error:
                raise ValueError(
                    f"{config_id} seed_index={seed_index} primary_labels={primary_label_hash} "
                    f"comparison_labels={comparison_hash}: {error}"
                ) from error
            aris.append(ari)
            nmis.append(nmi)
            metric_audits.append({
                "seed_index": seed_index,
                "primary_label_hash": primary_label_hash,
                "comparison_label_hash": comparison_hash,
                "ari": ari_audit,
                "nmi": nmi_audit,
            })
        try:
            matched_centroid_distance, prevalence_drift, chronological_profiles = (
                _chronological_block_stability(
                    engine, primary, vectors, mapping_vectors
                )
            )
        except ValueError as error:
            failed_reports.append(
                _model_report(primary, config_id, eligible=False, reasons=(str(error),))
            )
            continue
        chronological_profiles_by_id[config_id] = chronological_profiles
        seed_metric_audits_by_id[config_id] = metric_audits
        low_confidence = sum(
            1
            for item in seed_assignments[0]
            if (
                item.distance is not None
                and item.distance > dict(zip(primary.fingerprints, primary.distance_thresholds))[item.fingerprint]
            )
            or (
                item.distance is None
                and (item.dominant_probability < 0.65 or item.dominant_probability - item.second_probability < 0.10)
            )
        ) / len(seed_assignments[0])
        names = tuple(spec.name for spec in CHART_FEATURE_REGISTRY_V1)
        indices = [names.index(name) for name in primary.feature_names]
        raw = np.asarray([[float(vector.values[name]) for name in names] for vector in mapping_vectors])[:, indices]
        scaled = (np.clip(raw, primary.lower_bounds, primary.upper_bounds) - np.asarray(primary.medians)) / np.asarray(primary.scales)
        labels_as_int = [primary.fingerprints.index(label) for label in primary_labels]
        silhouette = float(silhouette_score(scaled, labels_as_int)) if primary.config.model_type == "kmeans" and len(set(labels_as_int)) > 1 else None
        # Frozen artifact arrays are sufficient for deterministic family ranking;
        # BIC uses the standard -2 log-likelihood + p log(n) form with diagonal
        # Gaussian density (tied covariances are expanded in the artifact).
        bic = None
        if primary.config.model_type == "gmm":
            log_terms = []
            dimensions = scaled.shape[1]
            for row in scaled:
                components = []
                for weight, mean, covariance in zip(primary.weights, primary.means, primary.covariances):
                    cov = np.asarray(covariance)
                    matrix = np.diag(cov) if cov.size == dimensions else cov.reshape(dimensions, dimensions)
                    sign, logdet = np.linalg.slogdet(matrix)
                    delta = row - np.asarray(mean)
                    components.append(math.log(weight) - 0.5 * (dimensions * math.log(2 * math.pi) + logdet + delta @ np.linalg.solve(matrix, delta)))
                maximum = max(components)
                log_terms.append(maximum + math.log(sum(math.exp(value - maximum) for value in components)))
            parameter_count = _gmm_parameter_count(
                primary.config.cluster_count,
                dimensions,
                primary.config.covariance_type,
            )
            bic = _gmm_bic(sum(log_terms), len(scaled), parameter_count)
        evidence = RegimeModelEvidence(
            artifact_id=config_id, model_type=primary.config.model_type,
            cluster_fingerprints=primary.fingerprints,
            weekly_episode_counts=weekly_counts,
            distinct_calendar_month_counts=month_counts,
            seed_ari=min(aris), seed_nmi=min(nmis),
            matched_centroid_distance=matched_centroid_distance,
            prevalence_drift=prevalence_drift, low_confidence_rate=low_confidence,
            silhouette=silhouette, bic=bic,
        )
        evidences.append(evidence)
        evidence_by_id[config_id] = evidence
    selection = SelectRegimeModelUseCase().execute(SelectRegimeModelCommand(candidates=tuple(evidences)))
    decisions = {item.artifact_id: item for item in selection.decisions}
    candidates = failed_reports + [
        {
            **_model_report(structural[item.artifact_id][0], item.artifact_id, eligible=item.eligible, reasons=item.rejection_reasons),
            "evidence": {
                "weekly_episode_counts": list(evidence_by_id[item.artifact_id].weekly_episode_counts),
                "distinct_calendar_month_counts": list(evidence_by_id[item.artifact_id].distinct_calendar_month_counts),
                "seed_ari": evidence_by_id[item.artifact_id].seed_ari,
                "seed_nmi": evidence_by_id[item.artifact_id].seed_nmi,
                "seed_metric_normalization": seed_metric_audits_by_id[item.artifact_id],
                "matched_centroid_distance": evidence_by_id[item.artifact_id].matched_centroid_distance,
                "prevalence_drift": evidence_by_id[item.artifact_id].prevalence_drift,
                "low_confidence_rate": evidence_by_id[item.artifact_id].low_confidence_rate,
                "silhouette": evidence_by_id[item.artifact_id].silhouette,
                "bic": evidence_by_id[item.artifact_id].bic,
                "chronological_block_refits": chronological_profiles_by_id[item.artifact_id],
            },
        }
        for item in selection.decisions
    ]
    selected_artifacts = {
        winner.model_family: structural[winner.artifact_id][0]
        for winner in selection.family_winners
    }
    selected = {
        family: {
            "config_id": next(key for key, value in structural.items() if value[0] is artifact),
            "artifact_hash": model_artifact_hash(artifact),
            "fingerprint_hash": model_fingerprint_hash(artifact),
            "fingerprints": list(artifact.fingerprints),
        }
        for family, artifact in sorted(selected_artifacts.items())
    }
    return {"selected": selected, "candidates": candidates, "_artifacts": selected_artifacts}


def _selection_policy(artifact) -> SelectionConfidenceThresholds:
    if artifact.config.model_type == "kmeans":
        return SelectionConfidenceThresholds(
            model_type="kmeans",
            kmeans_max_standardized_distances=dict(
                zip(artifact.fingerprints, artifact.distance_thresholds)
            ),
        )
    return SelectionConfidenceThresholds(
        model_type="gmm", gmm_probability_min=0.65, gmm_margin_min=0.10
    )


def _mapping_report(artifact) -> dict[str, object]:
    return {
        "artifact_hash": mapping_artifact_hash(artifact),
        "bootstrap": {
            "resamples": artifact.bootstrap.resamples,
            "confidence": artifact.bootstrap.confidence,
            "block_length_weeks": artifact.bootstrap.block_length_weeks,
        },
        "entries": {
            fingerprint: {
                "decision": entry.decision,
                "strategy_profile_id": entry.strategy_profile_id,
                "weekly_episode_count": entry.weekly_episode_count,
                "distinct_month_count": entry.distinct_month_count,
                "closed_trade_count": entry.closed_trade_count,
                "corrected_lower_bound": entry.corrected_lower_bound,
                "metrics": dict(entry.metrics),
                "rejection_reasons": list(entry.rejection_reasons),
            }
            for fingerprint, entry in sorted(artifact.entries.items())
        },
        "candidate_assessments": {
            fingerprint: {
                candidate_id: {
                    "candidate_hash": assessment.candidate_hash,
                    "eligible": assessment.eligible,
                    "weekly_episode_count": assessment.weekly_episode_count,
                    "distinct_month_count": assessment.distinct_month_count,
                    "closed_trade_count": assessment.closed_trade_count,
                    "corrected_lower_bound": assessment.corrected_lower_bound,
                    "observed_mean": assessment.observed_mean,
                    "metrics": dict(assessment.metrics),
                    "rejection_reasons": list(assessment.rejection_reasons),
                }
                for candidate_id, assessment in sorted(assessments.items())
            }
            for fingerprint, assessments in sorted(artifact.candidate_assessments.items())
        },
    }


def _candidate_feature_requirements(
    candidate: SchedulerBacktestCandidate,
) -> tuple[dict[str, tuple[str, ...]], ...]:
    return candidate_feature_requirements(candidate)


def _mapping_feature_coverage(
    market: MarketSnapshot,
    episodes: tuple[WeeklyEpisode, ...],
    candidates: tuple[SchedulerBacktestCandidate, ...],
    provider: object | None,
) -> tuple[dict[str, set[datetime]], dict[str, object]]:
    valid: dict[str, set[datetime]] = {}
    reports = {}
    cache = {}
    for candidate in candidates:
        alternatives = _candidate_feature_requirements(candidate)
        signature = tuple(
            tuple((name, sources) for name, sources in sorted(requirements.items()))
            for requirements in alternatives
        )
        valid[candidate.candidate_id] = set()
        episode_reports = []
        for episode in episodes:
            key = (signature, episode.start_at)
            if key not in cache:
                expected = 7 * 24 * 60
                if alternatives == ({},):
                    cache[key] = (True, expected, None)
                elif provider is None:
                    cache[key] = (False, 0, "market feature provider unavailable")
                else:
                    available = 0
                    missing_reason = None
                    for candle in market.candles:
                        if not episode.start_at <= candle.opened_at < episode.end_at:
                            continue
                        as_of = candle.closed_at
                        feature_set = provider.load_features(market.symbol, market.timeframe, as_of)
                        missing_by_alternative = []
                        for requirements in alternatives:
                            missing = []
                            for feature_name, allowed_sources in requirements.items():
                                value = feature_set.get(feature_name)
                                if (
                                    value is None
                                    or value.source not in allowed_sources
                                    or value.available_at > as_of
                                ):
                                    missing.append(feature_name)
                            missing_by_alternative.append(missing)
                        if all(missing_by_alternative):
                            missing_reason = (
                                f"missing point-in-time alternatives at {as_of.isoformat()}: "
                                + " OR ".join(
                                    ",".join(sorted(missing))
                                    for missing in missing_by_alternative
                                )
                            )
                            break
                        available += 1
                    cache[key] = (available == expected, available, missing_reason)
            is_valid, available_minutes, reason = cache[key]
            if is_valid:
                valid[candidate.candidate_id].add(episode.start_at)
            episode_reports.append({
                "episode_start_at": episode.start_at.isoformat(),
                "expected_minutes": 7 * 24 * 60,
                "available_minutes": available_minutes,
                "eligible": is_valid,
                "rejection_reason": reason,
            })
        reports[candidate.candidate_id] = {
            "required_alternatives": [
                {name: list(sources) for name, sources in requirements.items()}
                for requirements in alternatives
            ],
            "eligible_episode_count": len(valid[candidate.candidate_id]),
            "rejected_episode_count": len(episodes) - len(valid[candidate.candidate_id]),
            "episodes": episode_reports,
        }
    return valid, reports


def _run_mapping_coverage_filtered_evidence(
    market: MarketSnapshot,
    *,
    episodes: tuple[WeeklyEpisode, ...],
    assignments: Mapping[datetime, str],
    candidates: tuple[SchedulerBacktestCandidate, ...],
    valid_episodes: Mapping[str, set[datetime]],
    market_feature_provider: object | None,
) -> list[dict[str, object]]:
    rows = []
    for episode in episodes:
        eligible = tuple(
            candidate for candidate in candidates
            if episode.start_at in valid_episodes[candidate.candidate_id]
        )
        if not eligible:
            continue
        rows.extend(
            run_mapping_episodes(
                market,
                episodes=(episode,),
                assignments={episode.anchor_at: assignments[episode.anchor_at]},
                candidates=eligible,
                market_feature_provider=market_feature_provider,
            )
        )
    return rows


def _default_build_mappings(
    context: Mapping[str, object],
    prepared: Mapping[str, object],
    features: Mapping[str, object],
    models: Mapping[str, object],
) -> Mapping[str, object]:
    artifacts = dict(models.get("_artifacts", {}))
    if not artifacts:
        return {"selected": {}, "_artifacts": {}, "mapping_metrics": {"status": "cash_only"}}
    mapping_interval: UtcInterval = context["mapping_fit"]  # type: ignore[assignment]
    episodes = tuple(build_weekly_episodes(mapping_interval.start_at, mapping_interval.end_at))
    engine = SklearnRegimeModel()
    mapping_vectors = {vector.anchor_at: vector for vector in features["mapping_fit"]}
    assignments_by_family = {}
    for family, artifact in artifacts.items():
        episode_vectors = tuple(mapping_vectors[episode.anchor_at] for episode in episodes)
        assigned = engine.assign(artifact, episode_vectors)
        assignments_by_family[family] = {
            episode.anchor_at: assignment.fingerprint
            for episode, assignment in zip(episodes, assigned)
        }
    # Candidate evidence is independent of cluster/model. Execute it once, then
    # replace only the assignment label for each frozen model family.
    reference = next(iter(assignments_by_family.values()))
    resolved_candidates = tuple(context["candidates"])
    valid_episodes, feature_coverage = _mapping_feature_coverage(
        prepared["market"], episodes, resolved_candidates, prepared.get("provider")
    )
    evidence = _run_mapping_coverage_filtered_evidence(
        prepared["market"], episodes=episodes, assignments=reference,
        candidates=resolved_candidates, valid_episodes=valid_episodes,
        market_feature_provider=prepared.get("provider"),
    )
    if not evidence:
        return {
            "selected": {}, "_artifacts": {},
            "feature_coverage": feature_coverage,
            "mapping_metrics": {"status": "cash_only", "evidence_rows": 0},
        }
    by_key = {(row["episode_start_at"], row["candidate_id"]): row for row in evidence}
    mapping_artifacts = {}
    reports = {}
    grid: WalkForwardGrid = context["configuration_grid"]  # type: ignore[assignment]
    for family, model_artifact in artifacts.items():
        family_rows = []
        assignment = assignments_by_family[family]
        for episode in episodes:
            for candidate in context["candidates"]:
                key = (episode.start_at.isoformat(), candidate.candidate_id)
                if key not in by_key:
                    continue
                row = dict(by_key[key])
                row["cluster_fingerprint"] = assignment[episode.anchor_at]
                family_rows.append(row)
        family_artifacts = {}
        family_reports = {}
        for resamples in grid.bootstrap_resamples:
            for confidence in grid.confidence_levels:
                mapping_config_id = f"bootstrap:{resamples}:confidence:{confidence}"
                result = BuildStrategyMappingUseCase().execute(
                    BuildStrategyMappingCommand(
                        evidence_rows=tuple(family_rows),
                        regime_model_artifact_hash=model_artifact_hash(model_artifact),
                        regime_model_fingerprint_hash=model_fingerprint_hash(model_artifact),
                        selection_confidence_thresholds=_selection_policy(model_artifact),
                        bootstrap_resamples=resamples,
                        confidence=Decimal(str(confidence)),
                    )
                )
                family_artifacts[mapping_config_id] = result.artifact
                family_reports[mapping_config_id] = _mapping_report(result.artifact)
        mapping_artifacts[family] = family_artifacts
        reports[family] = family_reports
    global_rows = [dict(row, cluster_fingerprint="all") for row in evidence]
    global_mapping = BuildStrategyMappingUseCase().execute(
        BuildStrategyMappingCommand(
            evidence_rows=tuple(global_rows),
            regime_model_artifact_hash="0" * 64,
            regime_model_fingerprint_hash="1" * 64,
            selection_confidence_thresholds=SelectionConfidenceThresholds(
                model_type="gmm", gmm_probability_min=0.65, gmm_margin_min=0.10
            ),
            bootstrap_resamples=grid.bootstrap_resamples[0],
            confidence=Decimal(str(grid.confidence_levels[-1])),
        )
    ).artifact
    global_entry = global_mapping.entries["all"]
    return {
        "selected": reports,
        "_artifacts": mapping_artifacts,
        "train_selected_candidate_id": global_entry.strategy_profile_id,
        "train_selected_decision": global_entry.decision,
        "feature_coverage": feature_coverage,
        "mapping_metrics": {"weekly_episode_count": len(episodes), "evidence_rows": len(evidence)},
    }


def _validation_replay_metrics(
    replay: Mapping[str, object],
) -> tuple[Decimal, Decimal, Decimal]:
    values = []
    for field, nonnegative in (
        ("return_ratio", False),
        ("portfolio_max_drawdown_ratio", True),
        ("actual_turnover_notional", True),
    ):
        if field not in replay:
            raise ValueError(f"validation replay is missing required field {field}")
        try:
            value = Decimal(str(replay[field]))
        except (InvalidOperation, ValueError) as error:
            raise ValueError(f"validation replay field {field} must be a Decimal") from error
        if not value.is_finite():
            raise ValueError(f"validation replay field {field} must be finite")
        if nonnegative and value < 0:
            raise ValueError(f"validation replay field {field} must be nonnegative")
        values.append(value)
    return values[0], values[1], values[2]


def _default_validate(
    context: Mapping[str, object], prepared: Mapping[str, object], features: Mapping[str, object],
    models: Mapping[str, object], mappings: Mapping[str, object],
) -> Mapping[str, object]:
    model_objects = dict(models.get("_artifacts", {}))
    mapping_objects = dict(mappings.get("_artifacts", {}))
    available = sorted(set(model_objects) & set(mapping_objects))
    if not available:
        return {"status": "cash_only", "selected_family": None, "candidates": [], "_mapping_artifacts": {}}
    interval: UtcInterval = context["validation"]  # type: ignore[assignment]
    grid: WalkForwardGrid = context["configuration_grid"]  # type: ignore[assignment]
    candidates = tuple(context["candidates"])
    provider = prepared.get("provider")
    scored = []
    selected_by_family = {}
    selected_models = {}
    for family in available:
        model_artifact = model_objects[family]
        policies = []
        if family == "gmm":
            for probability in grid.gmm_probability_mins:
                for margin in grid.gmm_margin_mins:
                    policies.append((f"gmm:p{probability}:m{margin}", model_artifact, SelectionConfidenceThresholds(model_type="gmm", gmm_probability_min=probability, gmm_margin_min=margin)))
        else:
            for multiplier in grid.kmeans_distance_multipliers:
                distance_model = replace(
                    model_artifact,
                    distance_thresholds=tuple(value * multiplier for value in model_artifact.distance_thresholds),
                )
                policies.append((
                    f"kmeans:d{multiplier}",
                    distance_model,
                    SelectionConfidenceThresholds(
                        model_type="kmeans",
                        kmeans_max_standardized_distances={
                            fingerprint: threshold
                            for fingerprint, threshold in zip(distance_model.fingerprints, distance_model.distance_thresholds)
                        },
                    ),
                ))
        family_scores = []
        for mapping_config_id, base_mapping in sorted(mapping_objects[family].items()):
            audited_candidates = tuple(
                candidate for candidate in candidates
                if candidate.candidate_id in base_mapping.candidate_hashes
            )
            for policy_config_id, candidate_model, policy in policies:
                config_id = f"{mapping_config_id}:{policy_config_id}"
                candidate_mapping = replace(
                    base_mapping,
                    regime_model_artifact_hash=model_artifact_hash(candidate_model),
                    regime_model_fingerprint_hash=model_fingerprint_hash(candidate_model),
                    selection_confidence_thresholds=policy,
                )
                replay = run_scheduler_driven_regime_backtest(
                    prepared["market"], start_at=interval.start_at, end_at=interval.end_at,
                    candidates=audited_candidates, model_artifact=candidate_model,
                    mapping_artifact=candidate_mapping, market_feature_provider=provider,
                    include_deferred=bool(context["include_deferred"]),
                )
                continuous_return, drawdown, turnover = _validation_replay_metrics(replay)
                record = {
                    "family": family, "config_id": config_id,
                    "mapping_config_id": mapping_config_id,
                    "policy_config_id": policy_config_id,
                    "return_ratio": _decimal_text(continuous_return),
                    "portfolio_max_drawdown_ratio": _decimal_text(drawdown),
                    "actual_turnover_notional": _decimal_text(turnover),
                    "mapping_artifact_hash": mapping_artifact_hash(candidate_mapping),
                    "_artifact": candidate_mapping,
                    "_model_artifact": candidate_model,
                }
                scored.append(record)
                family_scores.append(record)
        winner = min(
            family_scores,
            key=lambda item: (
                -Decimal(item["return_ratio"]), Decimal(item["portfolio_max_drawdown_ratio"]),
                Decimal(item["actual_turnover_notional"]), item["config_id"],
            ),
        )
        selected_by_family[family] = winner["_artifact"]
        selected_models[family] = winner["_model_artifact"]
    overall = min(
        (item for item in scored if selected_by_family[item["family"]] is item["_artifact"]),
        key=lambda item: (
            -Decimal(item["return_ratio"]),
            Decimal(item["portfolio_max_drawdown_ratio"]),
            Decimal(item["actual_turnover_notional"]),
            item["config_id"],
        ),
    )
    return {
        "status": "selected", "selected_family": overall["family"],
        "selected_config_id": overall["config_id"],
        "score_order": "return_ratio_desc,portfolio_max_drawdown_ratio_asc,actual_turnover_notional_asc,config_id_asc",
        "candidates": [{key: value for key, value in item.items() if not key.startswith("_artifact") and key != "_model_artifact"} for item in scored],
        "_mapping_artifacts": selected_by_family,
        "_model_artifacts": selected_models,
    }


def _cash_comparison(reason: str | None = None) -> dict[str, object]:
    result = {
        "status": "cash",
        "continuous_metrics": {"return_ratio": "0", "max_drawdown_ratio": "0", "trade_count": 0},
    }
    if reason:
        result["rejection_reasons"] = [reason]
    return result


def _continuous_diagnostics(
    comparisons: Mapping[str, object], *, test_minutes: int
) -> dict[str, object]:
    if test_minutes <= 0:
        raise ValueError("Test diagnostic minutes must be positive")
    report = {}
    for name in COMPARISON_NAMES:
        comparison = comparisons.get(name, {})
        metrics = comparison.get("continuous_metrics", {}) if isinstance(comparison, Mapping) else {}
        if not isinstance(metrics, Mapping):
            metrics = {}
        status = comparison.get("status", "missing") if isinstance(comparison, Mapping) else "missing"
        reasons = comparison.get("rejection_reasons", ()) if isinstance(comparison, Mapping) else ()
        reason = "; ".join(str(item) for item in reasons) or None
        trades = metrics.get("trades", ())
        trades = trades if isinstance(trades, (tuple, list)) else ()
        comparison_type = (
            "cash_baseline" if name == "cash"
            else "dynamic_selector" if name.endswith("_dynamic")
            else "fixed_scheduler"
        )
        if name != "cash" and status != "ok":
            report[name] = {
                "comparison_type": comparison_type,
                "status": status,
                "availability": "not_evaluated",
                "reason": reason or "comparison was not evaluated",
                "cash_contribution": {
                    "availability": "not_evaluated", "cash_bars": None,
                    "cash_bar_share": None, "entries_while_cash": None,
                },
                "confidence": {
                    "availability": "not_evaluated", "assignment_count": None,
                    "diagnostics": None,
                },
                "transitions": {"availability": "not_evaluated", "counts": None},
                "actual_turnover_notional": {
                    "availability": "not_evaluated", "value": None,
                    "source": None, "convention": None,
                },
                "signal_discontinuity_count": None,
                "concentration": {"availability": "not_evaluated", "value": None},
            }
            continue
        positive = sorted(
            (Decimal(str(item.get("net_pnl", "0"))) for item in trades if Decimal(str(item.get("net_pnl", "0"))) > 0),
            reverse=True,
        )
        positive_total = sum(positive, Decimal(0))
        owners = {}
        for trade in trades:
            owner = trade.get("owner_strategy_profile_id") or comparison.get("candidate_id") or "unknown"
            owners[owner] = owners.get(owner, 0) + 1
        total_bars = int(metrics.get("cash_bars", 0)) + sum(
            int(value) for value in metrics.get("time_in_cluster_bars", {}).values()
        ) if isinstance(metrics.get("time_in_cluster_bars", {}), Mapping) else int(metrics.get("cash_bars", 0))
        concentration = {
            "availability": "measured",
            "top_5_positive_trade_pnl_share": (
                str(sum(positive[:5], Decimal(0)) / positive_total) if positive_total else "0"
            ),
            "strategy_trade_shares": {
                owner: str(Decimal(count) / Decimal(len(trades)))
                for owner, count in sorted(owners.items())
            } if trades else {},
            "single_fold_return_share": "1" if trades else "0",
        }
        if comparison_type == "cash_baseline":
            report[name] = {
                "comparison_type": comparison_type, "status": status,
                "availability": "measured", "reason": None,
                "cash_contribution": {
                    "availability": "measured", "cash_bars": test_minutes,
                    "cash_bar_share": "1", "entries_while_cash": 0,
                },
                "confidence": {"availability": "not_applicable", "assignment_count": None, "diagnostics": None},
                "transitions": {"availability": "not_applicable", "counts": None},
                "actual_turnover_notional": {
                    "availability": "measured", "value": "0",
                    "source": "explicit_cash_baseline",
                    "convention": "sum(quantity * (entry_price + exit_price))",
                },
                "signal_discontinuity_count": None,
                "concentration": concentration,
            }
            continue
        if comparison_type == "fixed_scheduler":
            declared_trade_count = int(metrics.get("trade_count", len(trades)))
            if declared_trade_count != len(trades):
                raise ValueError(
                    f"{name} trade_count does not match the available trade ledger"
                )
            turnover = Decimal("0")
            fees = Decimal("0")
            for trade in trades:
                if not isinstance(trade, Mapping):
                    raise ValueError(f"{name} trade diagnostics must be mappings")
                try:
                    quantity = Decimal(str(trade["quantity"]))
                    entry_price = Decimal(str(trade["entry_price"]))
                    exit_price = Decimal(str(trade["exit_price"]))
                    fee_paid = Decimal(str(trade["fee_paid"]))
                except (KeyError, InvalidOperation) as error:
                    raise ValueError(f"{name} trade lacks turnover accounting fields") from error
                if any(not value.is_finite() for value in (quantity, entry_price, exit_price, fee_paid)):
                    raise ValueError(f"{name} trade turnover accounting must be finite")
                if quantity < 0 or entry_price <= 0 or exit_price <= 0 or fee_paid < 0:
                    raise ValueError(f"{name} trade turnover accounting is outside its valid domain")
                turnover += quantity * (entry_price + exit_price)
                fees += fee_paid
            expected_fees = turnover * FEE_RATE
            tolerance = max(Decimal("1e-8"), abs(expected_fees) * Decimal("1e-10"))
            if abs(fees - expected_fees) > tolerance:
                raise ValueError(
                    f"{name} fee_paid does not reconcile with reconstructed turnover"
                )
            report[name] = {
                "comparison_type": comparison_type, "status": status,
                "availability": "measured", "reason": None,
                "cash_contribution": {
                    "availability": "not_applicable", "cash_bars": None,
                    "cash_bar_share": None, "entries_while_cash": None,
                },
                "confidence": {"availability": "not_applicable", "assignment_count": None, "diagnostics": None},
                "transitions": {"availability": "not_applicable", "counts": None},
                "actual_turnover_notional": {
                    "availability": "measured", "value": _decimal_text(turnover),
                    "source": "reconstructed_trade_legs",
                    "convention": "sum(quantity * (entry_price + exit_price))",
                },
                "signal_discontinuity_count": None,
                "concentration": concentration,
            }
            continue
        report[name] = {
            "comparison_type": comparison_type, "status": status,
            "availability": "measured", "reason": None,
            "cash_contribution": {
                "availability": "measured",
                "cash_bars": int(metrics.get("cash_bars", 0)),
                "cash_bar_share": (
                    str(Decimal(int(metrics.get("cash_bars", 0))) / Decimal(total_bars))
                    if total_bars else "0"
                ),
                "entries_while_cash": int(metrics.get("entries_while_cash", 0)),
            },
            "confidence": {
                "availability": "measured",
                "assignment_count": len(metrics.get("confidence_diagnostics", ())),
                "diagnostics": metrics.get("confidence_diagnostics", ()),
            },
            "transitions": {"availability": "measured", "counts": metrics.get("transition_counts", {})},
            "actual_turnover_notional": {
                "availability": "measured",
                "value": str(metrics.get("actual_turnover_notional", "0")),
                "source": "dynamic_engine_report",
                "convention": "engine-reported executed notional",
            },
            "signal_discontinuity_count": metrics.get("signal_discontinuity_count", 0),
            "concentration": concentration,
        }
    return report


def _default_replay_test(
    context: Mapping[str, object], prepared: Mapping[str, object], features: Mapping[str, object],
    models: Mapping[str, object], mappings: Mapping[str, object], validation: Mapping[str, object],
) -> Mapping[str, object]:
    test: UtcInterval = context["test"]  # type: ignore[assignment]
    market = prepared["market"]
    candidates = tuple(context["candidates"])
    provider = prepared.get("provider")
    results = {name: _cash_comparison() for name in COMPARISON_NAMES}
    adopted = default_candidate()
    adopted_result = run_scheduler_driven_backtest(
        market,
        context_start_at=test.start_at - timedelta(
            minutes=required_warmup_candles((adopted,), provider)
        ),
        start_at=test.start_at,
        end_at=test.end_at,
        candidate=adopted,
        market_feature_provider=provider,
        include_deferred=bool(context["include_deferred"]),
        include_trade_details=True,
        force_close_at_end=True,
    )
    results["adopted_fixed"] = {
        "status": "ok",
        "candidate_id": adopted.candidate_id,
        "continuous_metrics": adopted_result,
    }
    mapping_objects = dict(mappings.get("_artifacts", {}))
    model_objects = dict(models.get("_artifacts", {}))
    train_selected_id = mappings.get("train_selected_candidate_id")
    if train_selected_id is not None:
        selected = next(item for item in candidates if item.candidate_id == train_selected_id)
        fixed = run_scheduler_driven_backtest(
            market,
            context_start_at=test.start_at - timedelta(
                minutes=required_warmup_candles((selected,), provider)
            ),
            start_at=test.start_at,
            end_at=test.end_at,
            candidate=selected,
            market_feature_provider=provider,
            include_deferred=bool(context["include_deferred"]),
            include_trade_details=True,
            force_close_at_end=True,
        )
        results["train_selected_fixed"] = {
            "status": "ok",
            "candidate_id": selected.candidate_id,
            "continuous_metrics": fixed,
        }
    else:
        results["train_selected_fixed"] = _cash_comparison(
            mappings.get("skipped_reason", "mapping-fit statistical gate selected cash")
        )
    manual_router, manual_unavailable = _manual_router_for_replay(
        include_deferred=bool(context["include_deferred"])
    )
    if manual_router is None:
        results["manual_regime_router"] = _cash_comparison(manual_unavailable)
        results["manual_regime_router"]["status"] = "unavailable"
        results["manual_regime_router"]["router_rule"] = (
            "existing_hand_authored_regime_router"
        )
    else:
        manual_result = run_scheduler_driven_backtest(
            market,
            context_start_at=test.start_at - timedelta(
                minutes=required_warmup_candles((manual_router,), provider)
            ),
            start_at=test.start_at, end_at=test.end_at, candidate=manual_router,
            market_feature_provider=provider,
            include_deferred=bool(context["include_deferred"]),
            include_trade_details=True,
            force_close_at_end=True,
        )
        results["manual_regime_router"] = {
            "status": "ok",
            "router_rule": "existing_hand_authored_regime_router",
            "candidate_id": manual_router.candidate_id,
            "continuous_metrics": manual_result,
        }
    for family in ("kmeans", "gmm"):
        if family not in mapping_objects or family not in model_objects:
            results[f"{family}_dynamic"] = _cash_comparison("no frozen eligible artifact")
            continue
        selector_callback = context.get("on_test_selector_invoked")
        if callable(selector_callback):
            selector_callback(family)
        replay = run_scheduler_driven_regime_backtest(
            market,
            start_at=test.start_at,
            end_at=test.end_at,
            candidates=tuple(
                candidate for candidate in candidates
                if candidate.candidate_id in mapping_objects[family].candidate_hashes
            ),
            model_artifact=model_objects[family],
            mapping_artifact=mapping_objects[family],
            market_feature_provider=provider,
            include_deferred=bool(context["include_deferred"]),
        )
        results[f"{family}_dynamic"] = {
            "status": "ok",
            "continuous_metrics": replay,
        }
    return results


DEFAULT_WALK_FORWARD_DEPENDENCIES = WalkForwardDependencies(
    _default_prepare_data,
    _default_build_cluster_features,
    _default_evaluate_models,
    _default_build_mappings,
    _default_validate,
    _default_replay_test,
)


def _fold_payload(fold: RegimeWalkForwardFold) -> dict[str, object]:
    intervals = {}
    for name in ("cluster_fit", "mapping_fit", "validation", "test"):
        interval = getattr(fold, name)
        intervals[name] = {"start_at": interval.start_at.isoformat(), "end_at": interval.end_at.isoformat()}
    intervals["purges"] = [
        {
            "start_at": earlier.end_at.isoformat(),
            "end_at": later.start_at.isoformat(),
            "days": (later.start_at - earlier.end_at).days,
        }
        for earlier, later in zip(
            (fold.cluster_fit, fold.mapping_fit, fold.validation),
            (fold.mapping_fit, fold.validation, fold.test),
        )
    ]
    return intervals


def _grid_payload(grid: WalkForwardGrid) -> dict[str, object]:
    return {
        "cluster_counts": list(grid.cluster_counts),
        "model_types": list(grid.model_types),
        "gmm_covariance_types": list(grid.gmm_covariance_types),
        "seeds": list(grid.seeds),
        "spearman_threshold": grid.spearman_threshold,
        "bootstrap_resamples": list(grid.bootstrap_resamples),
        "confidence_levels": list(grid.confidence_levels),
        "gmm_probability_mins": list(grid.gmm_probability_mins),
        "gmm_margin_mins": list(grid.gmm_margin_mins),
        "kmeans_distance_multipliers": list(grid.kmeans_distance_multipliers),
    }


def _resolve_walk_forward_candidates(
    *,
    candidates: Sequence[SchedulerBacktestCandidate] | None,
    candidate_groups: Sequence[str],
    include_deferred: bool,
) -> tuple[tuple[SchedulerBacktestCandidate, ...], dict[str, str]]:
    built: list[SchedulerBacktestCandidate] = []
    if candidates is not None:
        if candidate_groups:
            raise ValueError("direct candidates cannot be combined with candidate groups")
        built.extend(candidates)
    else:
        if not candidate_groups:
            raise ValueError("at least one candidate group is required")
        for group in candidate_groups:
            if group not in _CANDIDATE_FACTORIES:
                raise ValueError(f"unknown candidate group: {group}")
            ensure_candidate_group_allowed(group, include_deferred=include_deferred)
            built.extend(_CANDIDATE_FACTORIES[group]())
    if not built:
        raise ValueError("candidate set cannot be empty")
    by_id: dict[str, SchedulerBacktestCandidate] = {}
    hashes: dict[str, str] = {}
    for candidate in built:
        behavior_hash = _canonical_hash(_candidate_behavior_payload(candidate))
        previous = hashes.get(candidate.candidate_id)
        if previous is not None and previous != behavior_hash:
            raise ValueError(f"conflicting candidate definition: {candidate.candidate_id}")
        hashes[candidate.candidate_id] = behavior_hash
        by_id.setdefault(candidate.candidate_id, candidate)
    ordered = tuple(by_id[key] for key in sorted(by_id))
    ensure_candidate_ids_allowed(tuple(item.candidate_id for item in ordered), include_deferred=include_deferred)
    return ordered, dict(sorted(hashes.items()))


def run_chart_regime_walk_forward(
    fold: RegimeWalkForwardFold,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    candidate_groups: Sequence[str] = (),
    include_deferred: bool = False,
    candidates: Sequence[SchedulerBacktestCandidate] | None = None,
    dependencies: WalkForwardDependencies = DEFAULT_WALK_FORWARD_DEPENDENCIES,
    inputs: WalkForwardInputs | None = None,
    test_input_loader: Callable[[], TestReplayInputs] | None = None,
    progress: Callable[[str], None] | None = None,
    fixture_grid: WalkForwardGrid | None = None,
    output_json: Path | None = None,
    output_markdown: Path | None = None,
    output_model: Path | None = None,
    output_mapping: Path | None = None,
    test_claim_status: str = "untouched",
    test_claim_reason: str | None = None,
    prior_run_timestamp: str | None = None,
    prior_run_hash: str | None = None,
) -> dict[str, object]:
    """Run one leakage-guarded four-interval pipeline.

    Test access exists in exactly one stage and is structurally after both freeze
    events.  Stage dependencies receive the same context in production and tests.
    """
    if symbol != "BTCUSDT" or timeframe != "1m":
        raise ValueError("the first walk-forward pipeline supports BTCUSDT 1m only")
    if test_claim_status not in {"untouched", "diagnostic_after_pipeline_defect"}:
        raise ValueError("unknown Test claim status")
    prior_fields = (test_claim_reason, prior_run_timestamp, prior_run_hash)
    if test_claim_status == "diagnostic_after_pipeline_defect":
        if any(not value for value in prior_fields):
            raise ValueError("diagnostic Test claim requires reason, prior timestamp, and prior hash")
        _parse_canonical_utc(prior_run_timestamp, "prior run timestamp")
        if len(prior_run_hash) != 64 or any(char not in "0123456789abcdef" for char in prior_run_hash):
            raise ValueError("prior run hash must be lowercase SHA-256")
    elif any(value is not None for value in prior_fields):
        raise ValueError("prior exposure audit fields require diagnostic Test claim status")
    if not isinstance(fold, RegimeWalkForwardFold):
        raise ValueError("fold must be a RegimeWalkForwardFold")
    purges = (
        fold.mapping_fit.start_at - fold.cluster_fit.end_at,
        fold.validation.start_at - fold.mapping_fit.end_at,
        fold.test.start_at - fold.validation.end_at,
    )
    if any(value != _WEEK for value in purges):
        raise ValueError("every fold boundary purge must be exactly seven days")
    selected_candidates, candidate_hashes = _resolve_walk_forward_candidates(
        candidates=candidates,
        candidate_groups=candidate_groups,
        include_deferred=include_deferred,
    )
    grid = fixture_grid or PRODUCTION_WALK_FORWARD_GRID
    events: list[str] = []
    access_audit: list[dict[str, str]] = []

    def emit(name: str) -> None:
        events.append(name)
        if progress is not None:
            progress(name)

    # Deliberately omit the Test interval from every fit/scoring dependency.
    # Merely asking a data loader for that slice early is leakage, even when the
    # caller promises not to inspect the returned candles.
    context = {
        "symbol": symbol,
        "timeframe": timeframe,
        "cluster_fit": fold.cluster_fit,
        "mapping_fit": fold.mapping_fit,
        "validation": fold.validation,
        "configuration_grid": grid,
        "candidates": selected_candidates,
        "candidate_hashes": candidate_hashes,
        "include_deferred": include_deferred,
        "data_access_audit": access_audit,
        "inputs": inputs,
    }
    prepared = dict(dependencies.prepare_data(context))
    access_audit.extend({"interval": name, "stage": "data_prepared"} for name in ("cluster_fit", "mapping_fit", "validation"))
    emit("data_prepared")
    features = dict(dependencies.build_cluster_features(context, prepared))
    emit("cluster_features_ready")
    models = dict(dependencies.evaluate_models(context, features))
    for candidate in models.get("candidates", ()):
        emit(f"model_candidate:{candidate.get('config_id', 'unknown')}")
    if models.get("selected"):
        mappings = dict(dependencies.build_mappings(context, prepared, features, models))
        emit("mapping_evidence_ready")
    else:
        mappings = {
            "selected": {},
            "_artifacts": {},
            "mapping_metrics": {"status": "not_evaluated_no_eligible_model"},
            "skipped_reason": "not evaluated: no eligible model",
        }
        emit("mapping_skipped_no_eligible_model")
    validation = dict(dependencies.validate(context, prepared, features, models, mappings))
    frozen_policy_artifacts = validation.pop("_mapping_artifacts", None)
    frozen_policy_models = validation.pop("_model_artifacts", None)
    if frozen_policy_models is not None:
        models["_artifacts"] = frozen_policy_models
        models["selected"] = {
            family: {
                "config_id": f"validation:{family}",
                "artifact_hash": model_artifact_hash(artifact),
                "fingerprint_hash": model_fingerprint_hash(artifact),
                "fingerprints": list(artifact.fingerprints),
            }
            for family, artifact in sorted(frozen_policy_models.items())
        }
    if frozen_policy_artifacts is not None:
        mappings["_artifacts"] = frozen_policy_artifacts
        mappings["selected"] = {
            family: _mapping_report(artifact)
            for family, artifact in sorted(frozen_policy_artifacts.items())
        }
    emit("validation_result")
    model_frozen = _canonical_hash(models.get("selected", {}))
    emit("model_frozen")
    mapping_frozen = _canonical_hash({"selected": mappings.get("selected", {}), "validation": validation})
    emit("mapping_frozen")

    if any(item["interval"] == "test" for item in access_audit):
        raise RuntimeError("Test interval was accessed before artifacts were frozen")
    test_inputs = test_input_loader() if test_input_loader is not None else None
    if test_inputs is not None:
        access_audit.append({"interval": "test", "stage": "test_data_loaded"})
        emit("test_data_prepared")
    selector_invoked = False
    selector_family = None

    def mark_test_selector_invoked(family: str) -> None:
        nonlocal selector_invoked, selector_family
        if selector_invoked:
            return
        selector_invoked = True
        selector_family = family
        access_audit.append({"interval": "test", "stage": "test_selector_invoked"})
        emit("first_test_classification")

    test_context = {
        **context,
        "test": fold.test,
        "on_test_selector_invoked": mark_test_selector_invoked,
    }
    test_prepared = dict(prepared)
    if test_inputs is not None:
        test_prepared["market"] = test_inputs.market
        test_prepared["provider"] = test_inputs.market_feature_provider
    elif inputs is not None:
        test_prepared["market"] = inputs.market
    try:
        raw_comparisons = dict(
            dependencies.replay_test(test_context, test_prepared, features, models, mappings, validation)
        )
    finally:
        if test_inputs is not None:
            close = getattr(test_inputs.market_feature_provider, "close", None)
            if callable(close):
                close()
    selector_not_reached_reason = None
    if not selector_invoked:
        selector_not_reached_reason = "no frozen eligible dynamic model/mapping selector was invoked"
        emit("test_selector_not_reached")
    access_audit.append({"interval": "test", "stage": "test_result"})
    unknown = set(raw_comparisons) - set(COMPARISON_NAMES)
    if unknown:
        raise ValueError(f"unknown comparison result: {', '.join(sorted(unknown))}")
    comparisons = {
        name: raw_comparisons.get(
            name,
            {"status": "cash", "rejection_reasons": ["no frozen eligible artifact"], "continuous_metrics": {}},
        )
        for name in COMPARISON_NAMES
    }
    emit("test_result")
    rejected = [
        item for item in models.get("candidates", ())
        if not item.get("eligible", False)
    ]
    data_provenance = {
        "pretest": prepared.get("provenance", {}),
        "test": test_inputs.data_provenance if test_inputs is not None else {},
    }
    payload = {
        "report_schema_version": 1,
        "artifact_schema_versions": {"feature": CHART_FEATURE_SCHEMA_VERSION},
        "symbol": symbol,
        "timeframe": timeframe,
        "fold": _fold_payload(fold),
        "configuration_grid": _grid_payload(grid),
        "gate_thresholds": {"model": MODEL_GATE_THRESHOLDS, "mapping": MAPPING_GATE_THRESHOLDS},
        "selection_score": "return_ratio_desc,portfolio_max_drawdown_ratio_asc,actual_turnover_notional_asc,config_id_asc",
        "feature_schema_version": CHART_FEATURE_SCHEMA_VERSION,
        "candidate_ids": [item.candidate_id for item in selected_candidates],
        "candidate_behavior_hash_algorithm": "sha256(canonical-json-sort-keys,compact-separators,decimal-tag:$decimal)",
        "candidate_behavior_hashes": candidate_hashes,
        "candidate_behaviors": {
            item.candidate_id: _canonicalize(_candidate_behavior_payload(item))
            for item in selected_candidates
        },
        "candidate_universe_hash": candidate_universe_hash(tuple(candidate_hashes)),
        "candidate_definition_hash": candidate_definition_hash(candidate_hashes),
        "include_deferred": include_deferred,
        "data_provenance": data_provenance,
        "data_provenance_hash": _canonical_hash(data_provenance),
        "model_candidates": list(models.get("candidates", ())),
        "rejected_model_configurations": rejected,
        "selected_models": models.get("selected", {}),
        "mapping_artifacts": mappings.get("selected", {}),
        "mapping_metrics": mappings.get("mapping_metrics", {}),
        "candidate_feature_coverage": mappings.get("feature_coverage", {}),
        "validation": validation,
        "frozen_artifact_hashes": {"model": model_frozen, "mapping": mapping_frozen},
        "comparisons": comparisons,
        "continuous_diagnostics": _continuous_diagnostics(
            comparisons,
            test_minutes=int((fold.test.end_at - fold.test.start_at).total_seconds() // 60),
        ),
        "pipeline_events": events,
        "data_access_audit": access_audit,
        "leakage_audit": {
            "frozen_before_test": (
                not selector_invoked
                or events.index("mapping_frozen") < events.index("first_test_classification")
            ),
            "test_selector_reached": selector_invoked,
            "test_selector_family": selector_family,
            "test_selector_not_reached_reason": selector_not_reached_reason,
            "confirmatory_status": test_claim_status,
            "claim_reason": test_claim_reason,
            "prior_run_timestamp": prior_run_timestamp,
            "prior_run_hash": prior_run_hash,
            "thresholds_changed_after_prior_exposure": False,
            "configuration_grid_changed_after_prior_exposure": False,
            "gate_thresholds_hash": _canonical_hash({"model": MODEL_GATE_THRESHOLDS, "mapping": MAPPING_GATE_THRESHOLDS}),
            "configuration_grid_hash": _canonical_hash(_grid_payload(grid)),
        },
        "cost_model": {"fee_rate_per_side": _decimal_text(FEE_RATE), "slippage_rate_per_side": _decimal_text(SLIPPAGE_RATE)},
    }
    output_paths = (output_json, output_markdown, output_model, output_mapping)
    if any(path is not None for path in output_paths):
        if any(path is None for path in output_paths):
            raise ValueError("all report and artifact output paths must be supplied together")
        family = validation.get("selected_family")
        model_objects = dict(models.get("_artifacts", {}))
        mapping_objects = dict(mappings.get("_artifacts", {}))
        if family in model_objects and family in mapping_objects:
            with tempfile.TemporaryDirectory(prefix="regime-artifacts-") as directory:
                repository = JsonRegimeArtifactRepository(directory)
                repository.save_model(model_objects[family])
                repository.save_mapping(
                    mapping_objects[family],
                    expected_model_artifact_hash=model_artifact_hash(model_objects[family]),
                    expected_model_fingerprint_hash=model_fingerprint_hash(model_objects[family]),
                )
                _atomic_write(Path(output_model), (Path(directory) / "model.json").read_bytes())
                _atomic_write(Path(output_mapping), (Path(directory) / "mapping.json").read_bytes())
            payload["artifact_outputs"] = {"status": "written", "selected_family": family}
        else:
            reason = "no validation-frozen eligible model/mapping pair"
            for kind, destination in (("model", output_model), ("mapping", output_mapping)):
                body = {
                    "schema_version": 1, "kind": "cash_only", "artifact_type": kind,
                    "symbol": symbol, "timeframe": timeframe, "reason": reason,
                    "frozen_artifact_hashes": {"model": model_frozen, "mapping": mapping_frozen},
                }
                envelope = {**body, "artifact_hash": _canonical_hash(body)}
                _atomic_write(
                    Path(destination),
                    (json.dumps(envelope, sort_keys=True, indent=2) + "\n").encode("utf-8"),
                )
            payload["artifact_outputs"] = {"status": "cash_only", "reason": reason}
        emit("reports_written")
        normalized = _canonicalize_report(payload)
        write_walk_forward_reports(normalized, Path(output_json), Path(output_markdown))
        return normalized
    return _canonicalize_report(payload)


def _canonicalize_report(value: object) -> object:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, datetime):
        if value.tzinfo is not timezone.utc:
            raise ValueError("report datetimes must use canonical UTC")
        return value.isoformat()
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("report object keys must be strings")
        normalized = {
            key: _canonicalize_report(item) for key, item in value.items()
        }
        if all(normalized[key] is item for key, item in value.items()):
            return value
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (tuple, list)):
        normalized = [_canonicalize_report(item) for item in value]
        if all(left is right for left, right in zip(normalized, value)):
            return value
        return normalized
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("report floats must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported report value: {type(value).__name__}")


def render_walk_forward_markdown(payload: Mapping[str, object]) -> str:
    comparisons = payload.get("comparisons", {})
    lines = [
        "# BTCUSDT chart-regime strategy mapping",
        "",
        "This is walk-forward research evidence, not a promotion or live-trading claim.",
        "",
        f"- Symbol/timeframe: {payload.get('symbol', 'unknown')} {payload.get('timeframe', 'unknown')}",
        f"- Frozen before Test: {payload.get('leakage_audit', {}).get('frozen_before_test', False)}",
        f"- Test claim status: {payload.get('leakage_audit', {}).get('confirmatory_status', 'unknown')}",
        f"- Prior exposure reason: {payload.get('leakage_audit', {}).get('claim_reason') or 'none'}",
        f"- Candidate universe: {payload.get('candidate_universe_hash', 'unknown')}",
        "",
        "## Test comparisons",
        "",
    ]
    for name in COMPARISON_NAMES:
        result = comparisons.get(name, {}) if isinstance(comparisons, Mapping) else {}
        metrics = result.get("continuous_metrics", {})
        lines.append(
            f"- {name}: {result.get('status', 'missing')}; "
            f"return={metrics.get('return_ratio', 'n/a')}; "
            f"MDD={metrics.get('portfolio_max_drawdown_ratio', metrics.get('max_drawdown_ratio', 'n/a'))}; "
            f"trades={metrics.get('trade_count', 0)}"
        )
    lines.extend(("", "## Frozen models and mappings", ""))
    for family, model in payload.get("selected_models", {}).items():
        lines.append(f"- {family}: model `{model.get('artifact_hash')}`, mapping `{payload.get('mapping_artifacts', {}).get(family, {}).get('artifact_hash')}`")
        entries = payload.get("mapping_artifacts", {}).get(family, {}).get("entries", {})
        for fingerprint, entry in entries.items():
            destination = entry.get("strategy_profile_id") or "cash"
            lines.append(
                f"  - `{fingerprint}` -> `{destination}` "
                f"(episodes={entry.get('weekly_episode_count', 0)}, trades={entry.get('closed_trade_count', 0)}, LCB={entry.get('corrected_lower_bound', '0')})"
            )
    lines.extend(("", "## Evidence coverage and diagnostics", ""))
    coverage = payload.get("candidate_feature_coverage", {})
    lines.append(f"- Candidate coverage records: {len(coverage)}")
    lines.append(f"- Rejected model configurations: {len(payload.get('rejected_model_configurations', ())) }")
    for item in payload.get("rejected_model_configurations", ()):
        reasons = item.get("rejection_reasons", ()) if isinstance(item, Mapping) else ()
        if reasons:
            lines.append(
                f"  - `{item.get('config_id', 'unknown')}`: "
                + "; ".join(str(reason) for reason in reasons)
            )
    lines.append(f"- Mapping metrics: `{json.dumps(payload.get('mapping_metrics', {}), sort_keys=True)}`")
    lines.extend(("", "## Costs and provenance", "", f"- Cost model: `{json.dumps(payload.get('cost_model', {}), sort_keys=True)}`", f"- Data provenance hash: `{payload.get('data_provenance_hash', 'unknown')}`", ""))
    return "\n".join(lines)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
    except BaseException:
        try:
            Path(temporary).unlink(missing_ok=True)
        finally:
            raise


def write_walk_forward_reports(payload: Mapping[str, object], json_path: Path | str, markdown_path: Path | str) -> None:
    normalized = _canonicalize_report(payload)
    json_bytes = (json.dumps(normalized, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    markdown_bytes = render_walk_forward_markdown(normalized).encode("utf-8")
    # Render both before replacing either destination.
    _atomic_write(Path(json_path), json_bytes)
    _atomic_write(Path(markdown_path), markdown_bytes)


def _date_argument(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error
    return parsed.replace(tzinfo=timezone.utc)


def _timestamp_argument(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timestamp must use canonical ISO-8601 UTC") from error
    if parsed.tzinfo is not timezone.utc or parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("timestamp must use canonical ISO-8601 UTC")
    return value


def _sha256_argument(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise argparse.ArgumentTypeError("hash must be lowercase SHA-256")
    return value


def _month_starts(start_at: datetime, end_at: datetime):
    cursor = datetime(start_at.year, start_at.month, 1, tzinfo=timezone.utc)
    while cursor < end_at:
        yield cursor
        cursor = (
            datetime(cursor.year + 1, 1, 1, tzinfo=timezone.utc)
            if cursor.month == 12
            else datetime(cursor.year, cursor.month + 1, 1, tzinfo=timezone.utc)
        )


def _archive_url(symbol: str, month: datetime) -> str:
    filename = f"{symbol}-1m-{month.year}-{month.month:02d}.zip"
    return f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/1m/{filename}"


def _remote_checksum(url: str) -> tuple[str, str]:
    checksum_url = f"{url}.CHECKSUM"
    try:
        with urlopen(checksum_url, timeout=30) as response:
            text = response.read().decode("ascii").strip()
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"failed to fetch archive checksum: {checksum_url}") from error
    expected = text.split()[0].lower() if text else ""
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ValueError(f"invalid archive checksum response: {checksum_url}")
    return expected, checksum_url


def _ensure_archive(path: Path, url: str) -> tuple[str, str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    expected, checksum_url = _remote_checksum(url)
    if not path.exists():
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            digest = hashlib.sha256()
            with os.fdopen(fd, "wb") as stream, urlopen(url, timeout=60) as response:
                while block := response.read(1024 * 1024):
                    digest.update(block)
                    stream.write(block)
                stream.flush()
                os.fsync(stream.fileno())
            actual = digest.hexdigest()
            if actual != expected:
                raise ValueError(f"downloaded archive checksum mismatch: {path.name}")
            Path(temporary).replace(path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(f"cached archive checksum mismatch: {path.name}")
    return actual, expected, checksum_url


def _archive_candles(
    path: Path,
    symbol: str,
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    parsed_symbol = Symbol("BTC", "USDT")
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            if len(names) != 1:
                raise ValueError(f"archive must contain exactly one CSV: {path.name}")
            with archive.open(names[0]) as raw:
                reader = csv.reader(TextIOWrapper(raw, encoding="utf-8"))
                for row in reader:
                    if not row or row[0] == "open_time":
                        continue
                    if len(row) < 6:
                        raise ValueError(f"malformed kline row in {path.name}")
                    opened_at = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc)
                    if end_at is not None and opened_at >= end_at:
                        break
                    if start_at is not None and opened_at < start_at:
                        continue
                    yield Candle(
                        symbol=parsed_symbol,
                        timeframe=TIMEFRAME,
                        opened_at=opened_at,
                        closed_at=opened_at + timedelta(minutes=1),
                        open_price=Decimal(row[1]), high_price=Decimal(row[2]),
                        low_price=Decimal(row[3]), close_price=Decimal(row[4]),
                        volume=Decimal(row[5]),
                    )
    except (OSError, UnicodeError, zipfile.BadZipFile, ValueError, InvalidOperation) as error:
        raise ValueError(f"invalid Binance archive {path.name}: {error}") from error


@dataclass(frozen=True)
class FeatureCacheShardPlan:
    cache_path: Path
    manifest_path: Path
    start_at: datetime
    end_at: datetime
    row_count: int
    output_hash: str
    manifest_hash: str
    cache_identity_hash: str
    input_hashes: Mapping[str, object]
    raw_hashes: Mapping[str, object]
    sources: tuple[str, ...]
    source_coverage: Mapping[str, object]
    provenance: Mapping[str, object]


@dataclass(frozen=True)
class FeatureCachePlan:
    shards: tuple[FeatureCacheShardPlan, ...]
    required_start: datetime
    required_end: datetime
    verify_full_file: bool = False


def _parse_cache_manifest(manifest_path: Path) -> FeatureCacheShardPlan:
    try:
        manifest_bytes = manifest_path.read_bytes()
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid feature cache manifest: {manifest_path.name}") from error
    identity = payload.get("cache_identity")
    if not isinstance(identity, Mapping) or identity.get("schema_version") != "binance-usdm-market-features-v1":
        raise ValueError("feature cache manifest schema mismatch")
    if payload.get("symbol") != "BTCUSDT" or payload.get("timeframe") != "1m":
        raise ValueError("feature cache manifest identity mismatch")
    start_at = _parse_canonical_utc(identity.get("start"), "cache start")
    end_at = _parse_canonical_utc(identity.get("end"), "cache end")
    sources = tuple(identity.get("sources", ()))
    coverage = payload.get("source_coverage")
    output_hash = payload.get("output_hash")
    cache_identity_hash = payload.get("cache_identity_hash")
    input_hashes = payload.get("input_hashes", {})
    raw_hashes = payload.get("raw_hashes", {})
    provenance = payload.get("provenance", {})
    row_count = payload.get("row_count")
    if (
        not sources or len(set(sources)) != len(sources)
        or not isinstance(coverage, Mapping) or set(coverage) != set(sources)
        or not isinstance(output_hash, str) or len(output_hash) != 64
        or any(character not in "0123456789abcdef" for character in output_hash)
        or not isinstance(cache_identity_hash, str) or len(cache_identity_hash) != 64
        or not isinstance(input_hashes, Mapping) or not isinstance(raw_hashes, Mapping)
        or not isinstance(provenance, Mapping)
        or any(not isinstance(item, Mapping) for item in coverage.values())
        or not isinstance(row_count, int) or isinstance(row_count, bool) or row_count < 1
        or row_count != int((end_at - start_at).total_seconds() // 60)
    ):
        raise ValueError("feature cache manifest metadata is inconsistent")
    cache_path = manifest_path.with_name(
        manifest_path.name.removesuffix(".manifest.json") + ".jsonl"
    )
    if not cache_path.is_file():
        raise ValueError("feature cache data file is missing")
    return FeatureCacheShardPlan(
        cache_path=cache_path, manifest_path=manifest_path,
        start_at=start_at, end_at=end_at, row_count=row_count,
        output_hash=output_hash, manifest_hash=hashlib.sha256(manifest_bytes).hexdigest(),
        cache_identity_hash=cache_identity_hash,
        input_hashes=dict(input_hashes), raw_hashes=dict(raw_hashes),
        sources=tuple(sorted(sources)),
        source_coverage=dict(coverage), provenance=dict(provenance),
    )


def plan_feature_caches(
    root: Path | None, *, required_start: datetime, required_end: datetime,
    verify_full_file: bool = False,
) -> FeatureCachePlan | None:
    if root is None:
        return None
    candidates = []
    for manifest in sorted(root.rglob("*.manifest.json"), key=lambda path: path.as_posix()):
        try:
            shard = _parse_cache_manifest(manifest)
        except ValueError:
            continue
        if shard.start_at <= required_start and shard.end_at >= required_end:
            candidates.append(shard)
    if not candidates:
        return None
    widest_start = min(item.start_at for item in candidates)
    widest_end = max(
        item.end_at for item in candidates if item.start_at == widest_start
    )
    exact = tuple(
        item for item in candidates
        if item.start_at == widest_start and item.end_at == widest_end
    )
    # Same-coverage shards are intentionally complementary.  Deterministic
    # path/hash ordering makes the merge plan independent of mtime.
    selected = tuple(sorted(exact, key=lambda item: (item.cache_path.as_posix(), item.output_hash)))
    return FeatureCachePlan(selected, required_start, required_end, verify_full_file)


class _IndexedJsonlShard:
    def __init__(
        self,
        plan: FeatureCacheShardPlan,
        *,
        required_start: datetime,
        required_end: datetime,
        verify_full_file: bool,
        progress: Callable[[str], None] | None,
        progress_label: str,
    ) -> None:
        self.plan = plan
        self._stream = plan.cache_path.open("rb")
        self._mapping = None
        self._offsets: list[tuple[int, int]] = []
        self.slice_hash = ""
        self.indexed_row_count = 0
        self.indexed_byte_count = 0
        self.full_file_verified = False
        self.source_available_counts = {source: 0 for source in plan.sources}
        self.source_unavailable_counts = {source: 0 for source in plan.sources}
        try:
            self._mapping = mmap.mmap(self._stream.fileno(), 0, access=mmap.ACCESS_READ)
            self._build_index(
                required_start=required_start,
                required_end=required_end,
                verify_full_file=verify_full_file,
                progress=progress,
                progress_label=progress_label,
            )
        except BaseException:
            self.close()
            raise

    def _build_index(
        self, *, required_start: datetime, required_end: datetime, verify_full_file: bool,
        progress: Callable[[str], None] | None, progress_label: str,
    ) -> None:
        indexed_end = min(required_end, self.plan.end_at)
        target_count = (
            self.plan.row_count
            if verify_full_file
            else int((indexed_end - self.plan.start_at).total_seconds() // 60)
        )
        if target_count < 1 or target_count > self.plan.row_count:
            raise ValueError("feature cache indexed coverage is invalid")
        if progress is not None:
            progress(f"feature_cache_index_started:{progress_label}:{target_count}")
        raw_hasher = hashlib.sha256()
        slice_hasher = hashlib.sha256()
        cursor = 0
        for index in range(target_count):
            newline = self._mapping.find(b"\n", cursor)
            if newline < 0:
                raise ValueError("feature cache row count does not match manifest")
            raw_line = self._mapping[cursor:newline + 1]
            raw_hasher.update(raw_line)
            try:
                row = json.loads(raw_line[:-1])
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("feature cache contains invalid JSONL") from error
            if not isinstance(row, Mapping):
                raise ValueError("feature cache row schema mismatch")
            expected_at = self.plan.start_at + timedelta(minutes=index + 1)
            measured_at = _parse_canonical_utc(row.get("measured_at"), "measured_at")
            if measured_at != expected_at:
                raise ValueError("feature cache timestamps must be strict increasing one-minute UTC")
            if row.get("symbol") != "BTCUSDT" or row.get("timeframe") != "1m":
                raise ValueError("feature cache row identity mismatch")
            features = row.get("features")
            unavailable = row.get("unavailable_sources", ())
            if (
                not isinstance(features, Mapping) or not isinstance(unavailable, list)
                or any(not isinstance(source, str) for source in unavailable)
            ):
                raise ValueError("feature cache row schema mismatch")
            filtered_features = {}
            available_sources = set()
            for name, item in features.items():
                if not isinstance(name, str) or not isinstance(item, Mapping):
                    raise ValueError("feature cache feature schema mismatch")
                source = item.get("source")
                if source not in self.plan.sources:
                    raise ValueError("feature cache feature source is not declared")
                observed_at = _parse_canonical_utc(item.get("observed_at"), "observed_at")
                available_at = _parse_canonical_utc(item.get("available_at"), "available_at")
                if observed_at > measured_at or available_at > measured_at:
                    raise ValueError("feature cache row is not point-in-time safe")
                try:
                    parsed_value = Decimal(str(item.get("value")))
                except InvalidOperation as error:
                    raise ValueError("feature cache value is not decimal") from error
                if not parsed_value.is_finite():
                    raise ValueError("feature cache value must be finite")
                filtered_features[name] = {
                    "value": str(item.get("value")),
                    "source": source,
                    "observed_at": observed_at.isoformat(),
                    "available_at": available_at.isoformat(),
                }
                available_sources.add(source)
            if any(source not in self.plan.sources for source in unavailable):
                raise ValueError("feature cache unavailable source is not declared")
            self._offsets.append((cursor, newline))
            if required_start <= measured_at <= required_end:
                canonical_slice_row = {
                    "features": filtered_features,
                    "measured_at": measured_at.isoformat(),
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "unavailable_sources": sorted(unavailable),
                }
                slice_hasher.update(
                    (json.dumps(canonical_slice_row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                )
                for source in self.plan.sources:
                    if source in available_sources:
                        self.source_available_counts[source] += 1
                    if source in unavailable:
                        self.source_unavailable_counts[source] += 1
            cursor = newline + 1
            if progress is not None and ((index + 1) % 50_000 == 0 or index + 1 == target_count):
                progress(f"feature_cache_index_progress:{progress_label}:{index + 1}/{target_count}")
        self.indexed_row_count = target_count
        self.indexed_byte_count = cursor
        self.slice_hash = slice_hasher.hexdigest()
        if target_count == self.plan.row_count:
            if cursor != len(self._mapping):
                raise ValueError("feature cache row count does not match manifest")
            if raw_hasher.hexdigest() != self.plan.output_hash:
                raise ValueError("feature cache output hash mismatch")
            self.full_file_verified = True
        if progress is not None:
            progress(f"feature_cache_index_completed:{progress_label}:{target_count}")

    def row_at(self, as_of: datetime) -> Mapping[str, object] | None:
        index = int((as_of - self.plan.start_at).total_seconds() // 60) - 1
        if index < 0 or index >= self.plan.row_count:
            return None
        if self._mapping is None:
            raise RuntimeError("feature cache provider is closed")
        if index >= len(self._offsets):
            return None
        start, end = self._offsets[index]
        row = json.loads(self._mapping[start:end])
        measured_at = _parse_canonical_utc(row.get("measured_at"), "measured_at")
        if measured_at > as_of:
            raise ValueError("feature cache row is not point-in-time safe")
        return row

    def close(self) -> None:
        mapping, self._mapping = self._mapping, None
        if mapping is not None:
            mapping.close()
        stream, self._stream = getattr(self, "_stream", None), None
        if stream is not None:
            stream.close()


class IndexedCompositeFeatureProvider:
    required_warmup_candles = 0

    def __init__(
        self, plan: FeatureCachePlan, *, progress: Callable[[str], None] | None = None
    ) -> None:
        self._plan = plan
        built = []
        try:
            for index, item in enumerate(plan.shards):
                built.append(_IndexedJsonlShard(
                    item, required_start=plan.required_start, required_end=plan.required_end,
                    verify_full_file=plan.verify_full_file,
                    progress=progress, progress_label=f"shard_{index:02d}",
                ))
        except BaseException:
            for shard in built:
                shard.close()
            raise
        self._shards = tuple(built)
        definitions = [
            {
                "schema_version": "binance-usdm-market-features-v1",
                "sources": list(shard.plan.sources),
                "slice_hash": shard.slice_hash,
            }
            for shard in self._shards
        ]
        slice_identity = {
            "symbol": "BTCUSDT", "timeframe": "1m",
            "required_start": plan.required_start.isoformat(),
            "required_end": plan.required_end.isoformat(),
            "shards": definitions,
        }
        self.feature_cache_hash = _canonical_hash(slice_identity)
        self.feature_config_hash = _canonical_hash({
            **slice_identity,
            "provider": "indexed-composite-jsonl-v2",
        })
        self.feature_source_coverage = {
            source: max(
                shard.source_available_counts.get(source, 0)
                for shard in self._shards
            )
            for source in sorted({source for shard in self._shards for source in shard.plan.sources})
        }
        self.feature_unavailable_counts = {
            source: max(
                shard.source_unavailable_counts.get(source, 0)
                for shard in self._shards
            )
            for source in self.feature_source_coverage
        }
        self.feature_provenance = {
            f"shard_{index:02d}": {
                "schema_version": "binance-usdm-market-features-v1",
                "slice_hash": shard.slice_hash,
                "sources": list(shard.plan.sources),
                "required_start": plan.required_start.isoformat(),
                "required_end": plan.required_end.isoformat(),
            }
            for index, shard in enumerate(self._shards)
        }
        self.feature_read_audit = {
            f"shard_{index:02d}": {
                "indexed_row_count": shard.indexed_row_count,
                "indexed_byte_count": shard.indexed_byte_count,
                "full_file_verified": shard.full_file_verified,
            }
            for index, shard in enumerate(self._shards)
        }
        interval_minutes = int((plan.required_end - plan.required_start).total_seconds() // 60) + 1
        # A merged set is conservatively budgeted at 6 KiB.  131,072 entries
        # keep a complete 77-day Validation or 86-day Test replay hot while
        # bounding the worst-case cache estimate at 768 MiB.  Weekly mapping
        # episodes always retain at least their complete 10,080-row working set.
        self._cache_capacity = max(7 * 24 * 60, min(interval_minutes, 131_072))
        self._merged_cache = OrderedDict()
        self._closed = False

    def load_features(self, symbol: Symbol, timeframe: Timeframe, as_of: datetime) -> MarketFeatureSet:
        if self._closed:
            raise RuntimeError("feature cache provider is closed")
        if as_of < self._plan.required_start or as_of > self._plan.required_end:
            raise ValueError("feature request is outside the provider's frozen access boundary")
        key = (symbol.pair, timeframe.label, as_of)
        cached = self._merged_cache.get(key)
        if cached is not None:
            self._merged_cache.move_to_end(key)
            return cached
        merged = {}
        unavailable = set()
        for shard in self._shards:
            row = shard.row_at(as_of)
            if row is None:
                unavailable.update(shard.plan.sources)
                continue
            for name, value in row.get("features", {}).items():
                canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
                if name in merged and merged[name][0] != canonical:
                    raise ValueError(f"conflicting feature cache value: {name}")
                merged[name] = (canonical, value)
            unavailable.update(row.get("unavailable_sources", ()))
        values = tuple(
            MarketFeatureValue(
                name=name, value=Decimal(str(item["value"])), source=item["source"],
                observed_at=_parse_canonical_utc(item["observed_at"], "observed_at"),
                available_at=_parse_canonical_utc(item["available_at"], "available_at"),
            )
            for name, (_, item) in sorted(merged.items())
        )
        available_sources = {item.source for item in values}
        result = MarketFeatureSet(
            symbol=symbol, timeframe=timeframe, measured_at=as_of, values=values,
            unavailable_sources=tuple(sorted(unavailable - available_sources)),
        )
        self._merged_cache[key] = result
        self._merged_cache.move_to_end(key)
        if len(self._merged_cache) > self._cache_capacity:
            self._merged_cache.popitem(last=False)
        return result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._merged_cache.clear()
        for shard in self._shards:
            shard.close()


def _select_feature_cache(
    root: Path | None, *, required_start: datetime, required_end: datetime,
    verify_full_file: bool = False,
    progress: Callable[[str], None] | None = None,
):
    plan = plan_feature_caches(
        root, required_start=required_start, required_end=required_end,
        verify_full_file=verify_full_file,
    )
    if plan is None:
        return None, {"selection_rule": "no covering manifest plan", "selected_shards": []}
    provider = IndexedCompositeFeatureProvider(plan, progress=progress)
    return provider, {
        "selection_rule": "manifest plan with access-bounded verified slice index",
        "slice_hash": provider.feature_cache_hash,
        "provider_config_hash": provider.feature_config_hash,
        "coverage": {"start_at": required_start.isoformat(), "end_at": required_end.isoformat()},
        "selected_shards": list(provider.feature_provenance.values()),
        "read_audit": dict(provider.feature_read_audit),
    }


def load_walk_forward_inputs(
    fold: RegimeWalkForwardFold,
    *,
    symbol: str,
    candidates: Sequence[SchedulerBacktestCandidate],
    raw_kline_root: Path,
    feature_cache_root: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> WalkForwardInputs:
    if symbol != "BTCUSDT":
        raise ValueError("archive loader supports BTCUSDT only")
    start_at = fold.cluster_fit.start_at - _WEEK
    end_at = fold.validation.end_at
    retention_start = fold.mapping_fit.start_at - max(
        _WEEK, timedelta(minutes=required_warmup_candles(tuple(candidates), None))
    )
    window = deque(maxlen=7 * 24 * 60)
    retained = []
    vectors = {"cluster_fit": [], "mapping_fit": [], "validation": []}
    archives = []
    expected = start_at
    extractor = ChartFeatureExtractor()
    for month in _month_starts(start_at, end_at):
        if progress is not None:
            progress(f"archive_scan_started:{month.year}-{month.month:02d}")
        url = _archive_url(symbol, month)
        path = raw_kline_root / symbol / Path(url).name
        sha256, expected_sha256, checksum_url = _ensure_archive(path, url)
        archives.append({
            "month": f"{month.year}-{month.month:02d}", "path": path.as_posix(),
            "source_url": url, "sha256": sha256, "expected_sha256": expected_sha256,
            "checksum_url": checksum_url, "checksum_verification": "remote_CHECKSUM_match",
            "size": path.stat().st_size,
        })
        for candle in _archive_candles(path, symbol, start_at=start_at, end_at=end_at):
            if candle.opened_at != expected:
                kind = "duplicate/out-of-order" if candle.opened_at < expected else "gap"
                raise ValueError(f"{kind} OHLCV at {candle.opened_at.isoformat()}")
            expected = candle.closed_at
            window.append(candle)
            if candle.opened_at >= retention_start:
                retained.append(candle)
            anchor = candle.closed_at
            if len(window) == window.maxlen and anchor.hour % 4 == 0 and anchor.minute == 0:
                target = None
                if fold.cluster_fit.start_at <= anchor < fold.cluster_fit.end_at:
                    target = "cluster_fit"
                elif fold.mapping_fit.start_at <= anchor < fold.mapping_fit.end_at:
                    target = "mapping_fit"
                elif fold.validation.start_at <= anchor < fold.validation.end_at:
                    target = "validation"
                if target:
                    vectors[target].append(extractor.extract(tuple(window), anchor))
        if progress is not None:
            progress(f"archive_scan_completed:{month.year}-{month.month:02d}")
    if expected != end_at:
        raise ValueError(f"OHLCV coverage ends at {expected.isoformat()}, expected {end_at.isoformat()}")
    provider, cache_provenance = _select_feature_cache(
        feature_cache_root,
        required_start=fold.mapping_fit.start_at,
        required_end=fold.validation.end_at,
        progress=progress,
    )
    provenance = {
        "archives": archives,
        "archive_set_hash": _canonical_hash(archives),
        "coverage": {"start_at": start_at.isoformat(), "end_at": end_at.isoformat(), "gaps": []},
        "feature_cache": cache_provenance,
        "retained_candle_count": len(retained),
        "maximum_classification_buffer_candles": window.maxlen,
    }
    return WalkForwardInputs(
        market=MarketSnapshot(tuple(retained)),
        cluster_fit_vectors=tuple(vectors["cluster_fit"]),
        mapping_vectors=tuple(vectors["mapping_fit"]),
        validation_vectors=tuple(vectors["validation"]),
        data_provenance=provenance,
        market_feature_provider=provider,
    )


def load_test_replay_inputs(
    fold: RegimeWalkForwardFold,
    *,
    symbol: str,
    raw_kline_root: Path,
    feature_cache_root: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> TestReplayInputs:
    """Load the seven-day classifier context and Test candles after freeze."""
    if symbol != "BTCUSDT":
        raise ValueError("archive loader supports BTCUSDT only")
    start_at = fold.test.start_at - _WEEK
    end_at = fold.test.end_at
    candles = []
    archives = []
    expected = start_at
    for month in _month_starts(start_at, end_at):
        if progress is not None:
            progress(f"test_archive_scan_started:{month.year}-{month.month:02d}")
        url = _archive_url(symbol, month)
        path = raw_kline_root / symbol / Path(url).name
        sha256, expected_sha256, checksum_url = _ensure_archive(path, url)
        archives.append({
            "month": f"{month.year}-{month.month:02d}", "path": path.as_posix(),
            "source_url": url, "sha256": sha256, "expected_sha256": expected_sha256,
            "checksum_url": checksum_url, "checksum_verification": "remote_CHECKSUM_match",
            "size": path.stat().st_size,
        })
        for candle in _archive_candles(path, symbol, start_at=start_at, end_at=end_at):
            if candle.opened_at != expected:
                kind = "duplicate/out-of-order" if candle.opened_at < expected else "gap"
                raise ValueError(f"{kind} OHLCV at {candle.opened_at.isoformat()}")
            expected = candle.closed_at
            candles.append(candle)
        if progress is not None:
            progress(f"test_archive_scan_completed:{month.year}-{month.month:02d}")
    if expected != end_at:
        raise ValueError(f"OHLCV coverage ends at {expected.isoformat()}, expected {end_at.isoformat()}")
    provider, cache_provenance = _select_feature_cache(
        feature_cache_root, required_start=start_at, required_end=end_at,
        verify_full_file=True,
        progress=progress,
    )
    provenance = {
        "archives": archives,
        "archive_set_hash": _canonical_hash(archives),
        "coverage": {"start_at": start_at.isoformat(), "end_at": end_at.isoformat(), "gaps": []},
        "feature_cache": cache_provenance,
        "retained_candle_count": len(candles),
        "classification_context_candles": 7 * 24 * 60,
    }
    return TestReplayInputs(
        market=MarketSnapshot(tuple(candles)),
        data_provenance=provenance,
        market_feature_provider=provider,
    )


def parse_walk_forward_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Leakage-safe BTCUSDT regime walk-forward")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--profile", choices=(THREE_DAY_PROFILE_ID,))
    parser.add_argument("--evidence-rows-path", type=Path)
    parser.add_argument("--resume", action="store_true")
    manifest_group = parser.add_mutually_exclusive_group()
    manifest_group.add_argument("--dry-run", action="store_true")
    manifest_group.add_argument("--manifest-only", action="store_true")
    for name in ("cluster-fit-start", "cluster-fit-end", "mapping-fit-start", "mapping-fit-end", "validation-start", "validation-end", "test-start", "test-end"):
        parser.add_argument(f"--{name}", type=_date_argument)
    parser.add_argument("--candidate-group", action="append", default=[])
    parser.add_argument("--include-deferred", action="store_true")
    parser.add_argument(
        "--test-claim-status",
        choices=("untouched", "diagnostic_after_pipeline_defect"),
        default="untouched",
    )
    parser.add_argument("--test-claim-reason")
    parser.add_argument("--prior-run-timestamp", type=_timestamp_argument)
    parser.add_argument("--prior-run-hash", type=_sha256_argument)
    parser.add_argument("--feature-cache-root", type=Path)
    parser.add_argument("--raw-kline-root", type=Path, default=Path(".research-data/binance-usdm/raw/klines"))
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-markdown", type=Path)
    parser.add_argument("--output-model", type=Path)
    parser.add_argument("--output-mapping", type=Path)
    args = parser.parse_args(argv)
    if getattr(args, "profile", None) == THREE_DAY_PROFILE_ID:
        weekly_only = (
            tuple(args.candidate_group), args.include_deferred,
            args.test_claim_status != "untouched", args.test_claim_reason,
            args.prior_run_timestamp, args.prior_run_hash,
        )
        fold_values = tuple(
            getattr(args, name)
            for name in (
                "cluster_fit_start", "cluster_fit_end", "mapping_fit_start", "mapping_fit_end",
                "validation_start", "validation_end", "test_start", "test_end",
            )
        )
        if any(weekly_only) or any(value is not None for value in fold_values):
            parser.error("three-day profile rejects weekly folds, tuning, and Test-claim arguments")
        args.output_json = args.output_json or THREE_DAY_OUTPUT_STEM.with_suffix(".json")
        args.output_markdown = args.output_markdown or THREE_DAY_OUTPUT_STEM.with_suffix(".md")
        args.output_model = args.output_model or THREE_DAY_OUTPUT_STEM.with_name(
            THREE_DAY_OUTPUT_STEM.name + "-model.json"
        )
        args.output_mapping = args.output_mapping or THREE_DAY_OUTPUT_STEM.with_name(
            THREE_DAY_OUTPUT_STEM.name + "-mapping.json"
        )
        return args
    if args.evidence_rows_path is not None or args.resume or args.dry_run or args.manifest_only:
        parser.error("three-day evidence arguments require --profile three-day-daily-k4-v1")
    if args.output_json is None or args.output_markdown is None:
        parser.error("--output-json and --output-markdown are required for seven-day mode")
    fold_dates = [
        getattr(args, name)
        for name in (
            "cluster_fit_start", "cluster_fit_end", "mapping_fit_start", "mapping_fit_end",
            "validation_start", "validation_end", "test_start", "test_end",
        )
    ]
    if any(value is None for value in fold_dates) and not all(value is None for value in fold_dates):
        parser.error("all eight fold date arguments must be supplied together")
    claim_fields = (args.test_claim_reason, args.prior_run_timestamp, args.prior_run_hash)
    if args.test_claim_status == "diagnostic_after_pipeline_defect":
        if any(not value for value in claim_fields):
            parser.error("diagnostic Test claim requires reason, prior timestamp, and prior hash")
    elif any(value is not None for value in claim_fields):
        parser.error("prior exposure audit fields require diagnostic Test claim status")
    args.output_model = args.output_model or args.output_json.with_name(f"{args.output_json.stem}-model.json")
    args.output_mapping = args.output_mapping or args.output_json.with_name(f"{args.output_json.stem}-mapping.json")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_walk_forward_args(argv)
    if getattr(args, "profile", None) == THREE_DAY_PROFILE_ID:
        try:
            validate_atomic_destinations(
                args.output_json, args.output_markdown,
                args.output_model, args.output_mapping,
            )
        except ValueError as error:
            print(f"three-day experiment failed: {error}")
            return 1
        return run_three_day_profile_main(args)
    supplied = [getattr(args, name) for name in ("cluster_fit_start", "cluster_fit_end", "mapping_fit_start", "mapping_fit_end", "validation_start", "validation_end", "test_start", "test_end")]
    if any(value is None for value in supplied):
        fold = BTCUSDT_FIRST_FOLD
    else:
        fold = RegimeWalkForwardFold(*(UtcInterval(supplied[index], supplied[index + 1]) for index in range(0, 8, 2)))
    def report_progress(event: str) -> None:
        print(event, flush=True)

    inputs = None
    try:
        resolved, _ = _resolve_walk_forward_candidates(
            candidates=None,
            candidate_groups=tuple(args.candidate_group),
            include_deferred=args.include_deferred,
        )
        inputs = load_walk_forward_inputs(
            fold,
            symbol=args.symbol,
            candidates=resolved,
            raw_kline_root=args.raw_kline_root,
            feature_cache_root=args.feature_cache_root,
            progress=report_progress,
        )
        payload = run_chart_regime_walk_forward(
            fold,
            symbol=args.symbol,
            candidates=resolved,
            include_deferred=args.include_deferred,
            inputs=inputs,
            test_input_loader=lambda: load_test_replay_inputs(
                fold,
                symbol=args.symbol,
                raw_kline_root=args.raw_kline_root,
                feature_cache_root=args.feature_cache_root,
                progress=report_progress,
            ),
            progress=report_progress,
            output_json=args.output_json,
            output_markdown=args.output_markdown,
            output_model=args.output_model,
            output_mapping=args.output_mapping,
            test_claim_status=args.test_claim_status,
            test_claim_reason=args.test_claim_reason,
            prior_run_timestamp=args.prior_run_timestamp,
            prior_run_hash=args.prior_run_hash,
        )
    except (OSError, ValueError, RuntimeError) as error:
        print(f"walk-forward failed: {error}")
        return 1
    finally:
        if inputs is not None:
            close = getattr(inputs.market_feature_provider, "close", None)
            if callable(close):
                close()
    print(f"wrote {args.output_json} and {args.output_markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
