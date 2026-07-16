"""Frozen daily candidate research universe and resumable evidence primitives."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
import re
from fnmatch import fnmatchcase
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from scripts.deferred_strategy_registry import (
    ensure_candidate_ids_allowed,
    load_deferred_strategy_registry,
)
from scripts.scheduler_driven_scalping_backtest import (
    SchedulerBacktestCandidate,
    BACKTEST_ENGINE_VERSION,
    FEE_RATE,
    SLIPPAGE_RATE,
    TIMEFRAME,
    alpha_entry_candidates,
    build_scheduler_candidates,
    build_strategies,
    candidate_definition_hash,
    candidate_payload,
    counter_microstructure_candidates,
    discovered_metrics_candidates,
    exact_historical_candidates,
    feature_provider_config_hash,
    metrics_positioning_candidates,
    microstructure_alpha_candidates,
    multi_frequency_candidates,
    required_warmup_candles,
    run_scheduler_driven_backtest,
)
from src.domain.market import MarketSnapshot, Symbol
from src.domain.regime import DailyStrategyEvidence
from src.domain.regime.three_day_chart_features import THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
from src.domain.regime.three_day_daily_profile import decimal_arithmetic_context
from src.domain.regime.three_day_daily_profile import PROFILE_ID


EXPECTED_THREE_DAY_DAILY_CANDIDATE_COUNT = 459
DAILY_EVIDENCE_CODE_VERSION = "daily-strategy-evidence-service-v1"
DAILY_EVIDENCE_SCHEMA_VERSION = "daily-strategy-evidence-v1"
DAILY_EVIDENCE_KEY_FIELDS = (
    "run_identity",
    "phase",
    "outcome_start_at",
    "component_fingerprint",
    "candidate_id",
)

_CANDIDATE_FACTORIES = MappingProxyType({
    "all": build_scheduler_candidates,
    "alpha": alpha_entry_candidates,
    "counter": counter_microstructure_candidates,
    "discovered": discovered_metrics_candidates,
    "exact": exact_historical_candidates,
    "metrics": metrics_positioning_candidates,
    "microstructure": microstructure_alpha_candidates,
    "multi": multi_frequency_candidates,
})
_EXPECTED_CANDIDATE_GROUPS = frozenset(_CANDIDATE_FACTORIES)
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _canonical_cost_model() -> dict[str, str]:
    return {
        "venue": "binance_usd_m_futures",
        "fee_rate_per_side": str(FEE_RATE),
        "slippage_rate_per_side": str(SLIPPAGE_RATE),
        "funding_fee": "excluded",
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class DailyCandidateManifestEntry:
    candidate_id: str
    candidate: SchedulerBacktestCandidate
    canonical_candidate_payload: Mapping[str, object]
    definition_hash: str
    required_feature_alternatives: tuple[tuple[tuple[str, tuple[str, ...]], ...], ...]
    deferred_groups: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ThreeDayDailyCandidateManifest:
    entries: tuple[DailyCandidateManifestEntry, ...]
    candidate_ids: tuple[str, ...]
    ordered_definition_hashes: tuple[tuple[str, str], ...]
    candidate_universe_hash: str
    manifest_hash: str


@dataclass(frozen=True)
class DailyEvidenceRunIdentity:
    profile_id: str
    feature_schema_version: str
    phase: str
    phase_start_at: datetime
    phase_end_at: datetime
    model_artifact_hash: str
    candidate_universe_hash: str
    ordered_candidate_definition_hashes: tuple[tuple[str, str], ...]
    market_data_hash: str
    feature_cache_hash: str | None
    feature_config_hash: str | None
    feature_cache_schema_version: str
    feature_provenance_hash: str
    feature_source_coverage_hash: str
    feature_unavailable_counts_hash: str
    engine_version: str
    cost_model: Mapping[str, object]
    symbol: str
    timeframe: str
    initial_equity: Decimal
    code_version: str
    evidence_schema_version: str

    def __post_init__(self) -> None:
        if self.phase_start_at.tzinfo is not timezone.utc or self.phase_end_at.tzinfo is not timezone.utc:
            raise ValueError("run identity phase bounds must be canonical UTC")
        if self.phase_start_at >= self.phase_end_at:
            raise ValueError("run identity phase interval must be increasing")
        if not isinstance(self.initial_equity, Decimal) or self.initial_equity <= 0:
            raise ValueError("run identity initial equity must be a positive Decimal")
        if self.profile_id != PROFILE_ID or self.feature_schema_version != THREE_DAY_CHART_FEATURE_SCHEMA_VERSION:
            raise ValueError("run identity research profile or feature schema is not canonical")
        if self.code_version != DAILY_EVIDENCE_CODE_VERSION or self.evidence_schema_version != DAILY_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("run identity code or evidence schema version is not canonical")
        for field in (
            "model_artifact_hash", "candidate_universe_hash", "market_data_hash",
            "feature_provenance_hash", "feature_source_coverage_hash",
            "feature_unavailable_counts_hash",
        ):
            if _SHA256.fullmatch(str(getattr(self, field))) is None:
                raise ValueError(f"run identity {field} must be a lowercase SHA256 hash")
        for field in ("feature_cache_hash", "feature_config_hash"):
            value = getattr(self, field)
            if value is not None and _SHA256.fullmatch(str(value)) is None:
                raise ValueError(f"run identity {field} must be null or a lowercase SHA256 hash")
        object.__setattr__(self, "ordered_candidate_definition_hashes",
                           tuple(self.ordered_candidate_definition_hashes))
        object.__setattr__(self, "cost_model", _freeze(dict(self.cost_model)))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "feature_schema_version": self.feature_schema_version,
            "phase": self.phase,
            "phase_interval": {
                "start_at": self.phase_start_at.isoformat(),
                "end_at": self.phase_end_at.isoformat(),
            },
            "model_artifact_hash": self.model_artifact_hash,
            "candidate_universe_hash": self.candidate_universe_hash,
            "ordered_candidate_definition_hashes": [list(item) for item in self.ordered_candidate_definition_hashes],
            "market_data_hash": self.market_data_hash,
            "feature_cache_hash": self.feature_cache_hash,
            "feature_config_hash": self.feature_config_hash,
            "feature_cache_schema_version": self.feature_cache_schema_version,
            "feature_provenance_hash": self.feature_provenance_hash,
            "feature_source_coverage_hash": self.feature_source_coverage_hash,
            "feature_unavailable_counts_hash": self.feature_unavailable_counts_hash,
            "engine_version": self.engine_version,
            "cost_model": _thaw(self.cost_model),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "initial_equity": str(self.initial_equity),
            "code_version": self.code_version,
            "evidence_schema_version": self.evidence_schema_version,
        }

    @property
    def digest(self) -> str:
        return candidate_definition_hash(self.canonical_payload())


def market_snapshot_hash(market: MarketSnapshot) -> str:
    digest = hashlib.sha256()
    for candle in market.candles:
        payload = (
            candle.opened_at.isoformat(), candle.closed_at.isoformat(),
            str(candle.open_price), str(candle.high_price), str(candle.low_price),
            str(candle.close_price), str(candle.volume),
        )
        digest.update(_canonical_json(payload).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def build_three_day_daily_candidate_manifest(
    *,
    candidate_groups: Mapping[str, Sequence[SchedulerBacktestCandidate]] | None = None,
    expected_count: int = EXPECTED_THREE_DAY_DAILY_CANDIDATE_COUNT,
) -> ThreeDayDailyCandidateManifest:
    """Freeze the explicit, opt-in three-day/daily research universe."""
    registry = load_deferred_strategy_registry()
    status_by_group = {
        str(family["candidate_group"]): str(family["status"])
        for family in registry["families"]
    }
    supplied = candidate_groups or {
        name: factory() for name, factory in _CANDIDATE_FACTORIES.items()
    }
    if set(supplied) != _EXPECTED_CANDIDATE_GROUPS:
        raise ValueError("candidate manifest requires exactly all eight public groups")
    if any(not tuple(candidates) for candidates in supplied.values()):
        raise ValueError("every public candidate group must be nonempty")
    unknown_groups = sorted(set(supplied) - set(status_by_group))
    if unknown_groups:
        raise ValueError(f"candidate groups are absent from deferred registry: {', '.join(unknown_groups)}")

    by_id: dict[str, tuple[SchedulerBacktestCandidate, dict[str, object], str]] = {}
    groups_by_id: dict[str, set[tuple[str, str]]] = {}
    for group in sorted(supplied):
        candidates = tuple(supplied[group])
        ensure_candidate_ids_allowed(
            tuple(candidate.candidate_id for candidate in candidates), include_deferred=True
        )
        for candidate in candidates:
            payload = candidate_payload(candidate)
            definition_hash = candidate_definition_hash(payload)
            existing = by_id.get(candidate.candidate_id)
            if existing is not None and (
                existing[2] != definition_hash or existing[1] != payload
            ):
                raise ValueError(
                    f"conflicting duplicate candidate_id definition: {candidate.candidate_id}"
                )
            by_id.setdefault(candidate.candidate_id, (candidate, payload, definition_hash))
            matched = {
                (str(family["candidate_group"]), str(family["status"]))
                for family in registry["families"]
                if any(fnmatchcase(candidate.candidate_id, pattern)
                       for pattern in family["candidate_id_patterns"])
            }
            if not matched:
                raise ValueError(
                    f"candidate_id has no deferred registry provenance: {candidate.candidate_id}"
                )
            groups_by_id.setdefault(candidate.candidate_id, set()).update(matched)

    if len(by_id) != expected_count:
        raise ValueError(
            f"three-day daily candidate universe drift: expected {expected_count}, found {len(by_id)}"
        )
    entries = []
    for candidate_id in sorted(by_id):
        candidate, payload, definition_hash = by_id[candidate_id]
        alternatives = _candidate_feature_requirements(candidate)
        entries.append(DailyCandidateManifestEntry(
            candidate_id=candidate_id,
            candidate=candidate,
            canonical_candidate_payload=_freeze(payload),
            definition_hash=definition_hash,
            required_feature_alternatives=alternatives,
            deferred_groups=tuple(sorted(groups_by_id[candidate_id])),
        ))
    frozen_entries = tuple(entries)
    candidate_ids = tuple(entry.candidate_id for entry in frozen_entries)
    ordered_hashes = tuple((entry.candidate_id, entry.definition_hash) for entry in frozen_entries)
    universe_payload = [_thaw(entry.canonical_candidate_payload) for entry in frozen_entries]
    universe_hash = candidate_definition_hash(universe_payload)
    manifest_payload = {
        "candidate_count": len(frozen_entries),
        "candidate_ids": list(candidate_ids),
        "candidate_universe_hash": universe_hash,
        "candidates": [
            {
                "candidate_id": entry.candidate_id,
                "candidate_payload": _thaw(entry.canonical_candidate_payload),
                "definition_hash": entry.definition_hash,
                "required_feature_alternatives": [
                    {name: list(sources) for name, sources in alternative}
                    for alternative in entry.required_feature_alternatives
                ],
                "deferred_groups": [list(item) for item in entry.deferred_groups],
            }
            for entry in frozen_entries
        ],
    }
    return ThreeDayDailyCandidateManifest(
        entries=frozen_entries,
        candidate_ids=candidate_ids,
        ordered_definition_hashes=ordered_hashes,
        candidate_universe_hash=universe_hash,
        manifest_hash=candidate_definition_hash(manifest_payload),
    )


def _combine_requirement_alternatives(groups):
    combined: tuple[dict[str, tuple[str, ...]], ...] = ({},)
    for alternatives in groups:
        expanded = []
        for left in combined:
            for right in alternatives:
                merged = dict(left)
                for name, sources in right.items():
                    merged[name] = tuple(sorted(set(merged.get(name, ())) | set(sources)))
                expanded.append(merged)
        unique = {
            tuple((name, tuple(sources)) for name, sources in sorted(item.items())): item
            for item in expanded
        }
        combined = tuple(unique[key] for key in sorted(unique))
    return combined


def _strategy_feature_requirements(strategy: object):
    direct = getattr(strategy, "required_features", None)
    if isinstance(direct, Mapping):
        return ({name: tuple(sources) for name, sources in direct.items()},)
    inner = getattr(strategy, "inner", None)
    if inner is not None:
        return _strategy_feature_requirements(inner)
    children = getattr(strategy, "children", ())
    if children:
        return _combine_requirement_alternatives(
            tuple(_strategy_feature_requirements(child) for child in children)
        )
    name = type(strategy).__name__
    if name == "FlowExhaustionReversalStrategy":
        return ({"taker_imbalance": tuple(strategy.taker_imbalance_sources),
                 "cvd_delta": tuple(strategy.cvd_delta_sources)},)
    if name in {"OpenInterestImpulseStrategy", "OpenInterestDivergenceStrategy"}:
        return ({"open_interest_change_ratio_5m": ("metrics",),
                 "taker_long_short_volume_ratio": ("metrics",)},)
    if name == "PositioningCrowdingReversalStrategy":
        return ({"top_trader_position_long_short_ratio": ("metrics",),
                 "global_long_short_ratio": ("metrics",),
                 "taker_long_short_volume_ratio": ("metrics",)},)
    if name == "GlobalRatioShockReversalStrategy":
        return ({"global_long_short_change_5m": ("metrics",)},)
    if name == "PremiumFundingReversionStrategy":
        flow = {"taker_imbalance": tuple(strategy.taker_imbalance_sources),
                "cvd_delta": tuple(strategy.cvd_delta_sources)}
        return ({**flow, "premium_index": tuple(strategy.premium_sources)},
                {**flow, "mark_price": tuple(strategy.mark_sources),
                 "index_price": tuple(strategy.index_sources)})
    if name == "SessionOpeningRangeStrategy":
        return ({"taker_imbalance": tuple(strategy.taker_imbalance_sources),
                 "cvd_delta": tuple(strategy.cvd_delta_sources),
                 "trade_intensity": tuple(strategy.trade_intensity_sources)},)
    return ({},)


def _candidate_feature_requirements(candidate: SchedulerBacktestCandidate):
    strategies = build_strategies(candidate)
    alternatives = _combine_requirement_alternatives(
        tuple(_strategy_feature_requirements(strategy) for strategy in strategies)
    )
    return tuple(
        tuple((name, tuple(sources)) for name, sources in sorted(item.items()))
        for item in alternatives
    )


def run_daily_strategy_evidence(
    *,
    manifest: ThreeDayDailyCandidateManifest,
    phase: str,
    outcome_start_at: datetime,
    component_fingerprint: str,
    market: MarketSnapshot,
    market_feature_provider: object | None,
    run_identity: DailyEvidenceRunIdentity,
    ledger: "AppendOnlyEvidenceLedger",
    symbol: Symbol | None = None,
    candidate_ids: Sequence[str] = (),
    replay_callable=None,
) -> tuple[DailyStrategyEvidence, ...]:
    """Run isolated one-day canonical evidence, resuming only an exact identity."""
    if outcome_start_at.tzinfo is not timezone.utc or outcome_start_at.time() != datetime.min.time():
        raise ValueError("daily outcome start must be canonical midnight UTC")
    outcome_end_at = outcome_start_at + timedelta(days=1)
    if phase != run_identity.phase or not (
        run_identity.phase_start_at <= outcome_start_at < outcome_end_at <= run_identity.phase_end_at
    ):
        raise ValueError("daily outcome is outside the run identity phase")
    if manifest.candidate_universe_hash != run_identity.candidate_universe_hash:
        raise ValueError("candidate universe hash does not match run identity")
    if manifest.ordered_definition_hashes != run_identity.ordered_candidate_definition_hashes:
        raise ValueError("candidate definition hashes do not match run identity")
    if market_snapshot_hash(market) != run_identity.market_data_hash:
        raise ValueError("market data hash does not match run identity")
    replay = replay_callable or run_scheduler_driven_backtest
    selected_symbol = symbol or market.symbol
    if selected_symbol != market.symbol or selected_symbol.pair != run_identity.symbol:
        raise ValueError("market symbol does not match run identity")
    if market.timeframe != TIMEFRAME or run_identity.timeframe != "1m":
        raise ValueError("daily evidence requires the canonical 1m timeframe")
    if ledger.key_fields != DAILY_EVIDENCE_KEY_FIELDS:
        raise ValueError("daily evidence ledger uses an incompatible unique key")

    requested = tuple(candidate_ids)
    if len(set(requested)) != len(requested):
        raise ValueError("candidate selection must be unique")
    unknown = sorted(set(requested) - set(manifest.candidate_ids))
    if unknown:
        raise ValueError(f"unknown candidate_id: {', '.join(unknown)}")
    selected = tuple(
        entry for entry in manifest.entries if not requested or entry.candidate_id in requested
    )
    existing = ledger.load()
    if existing and existing[0].get("run_identity") != run_identity.digest:
        raise ValueError("run identity does not match existing daily evidence")
    by_key = {
        tuple(row[field] for field in DAILY_EVIDENCE_KEY_FIELDS): row for row in existing
    }
    results = []
    for entry in selected:
        key = (
            run_identity.digest,
            phase,
            outcome_start_at.isoformat(),
            component_fingerprint,
            entry.candidate_id,
        )
        resumed = by_key.get(key)
        if resumed is not None:
            results.append(_evidence_from_payload(resumed["evidence"]))
            continue
        warmup = required_warmup_candles((entry.candidate,), market_feature_provider)
        context_start_at = outcome_start_at - timedelta(minutes=warmup)
        _validate_market_context(market, context_start_at, outcome_end_at)
        unavailable_reason = _feature_unavailability_reason(
            entry, market, market_feature_provider, context_start_at, outcome_end_at
        )
        if unavailable_reason is None:
            replay_result = replay(
                market,
                start_at=outcome_start_at,
                end_at=outcome_end_at,
                context_start_at=context_start_at,
                candidate=entry.candidate,
                symbol=selected_symbol,
                market_feature_provider=market_feature_provider,
                include_deferred=True,
                initial_equity=run_identity.initial_equity,
                include_trade_details=True,
                force_close_at_end=True,
            )
            _validate_replay_provenance(
                replay_result,
                identity=run_identity,
                provider=market_feature_provider,
                outcome_start_at=outcome_start_at,
                outcome_end_at=outcome_end_at,
            )
            evidence = _available_evidence(
                replay_result, entry=entry, run_identity=run_identity,
                component_fingerprint=component_fingerprint,
                outcome_start_at=outcome_start_at, market=market,
            )
        else:
            evidence = _unavailable_evidence(
                reason=unavailable_reason, entry=entry, run_identity=run_identity,
                component_fingerprint=component_fingerprint,
                outcome_start_at=outcome_start_at,
            )
        row = {
            "run_identity": run_identity.digest,
            "phase": phase,
            "outcome_start_at": outcome_start_at.isoformat(),
            "component_fingerprint": component_fingerprint,
            "candidate_id": entry.candidate_id,
            "evidence": evidence.canonical_payload(),
        }
        ledger.append(row)
        results.append(evidence)
    return tuple(results)


def _validate_market_context(market: MarketSnapshot, start_at: datetime, end_at: datetime) -> None:
    candles = tuple(
        candle for candle in market.candles if start_at <= candle.opened_at < end_at
    )
    expected = int((end_at - start_at).total_seconds() // 60)
    if len(candles) != expected or not candles or candles[0].opened_at != start_at:
        raise ValueError("market context is missing required contiguous warmup/outcome candles")
    for left, right in zip(candles, candles[1:]):
        if left.closed_at != right.opened_at:
            raise ValueError("market context contains a candle gap")
    if candles[-1].closed_at != end_at:
        raise ValueError("market context does not cover the half-open daily outcome")


def _feature_unavailability_reason(entry, market, provider, start_at, end_at):
    if entry.required_feature_alternatives == ((),):
        return None
    if provider is None:
        return "point_in_time_feature_provider_unavailable"
    for candle in market.candles:
        if not start_at <= candle.opened_at < end_at:
            continue
        as_of = candle.closed_at
        feature_set = provider.load_features(market.symbol, market.timeframe, as_of)
        missing_alternatives = []
        for alternative in entry.required_feature_alternatives:
            missing = []
            for name, sources in alternative:
                value = feature_set.get(name)
                if value is None or value.source not in sources or value.available_at > as_of:
                    missing.append(name)
            missing_alternatives.append(tuple(missing))
        if all(missing_alternatives):
            rendered = " OR ".join(",".join(items) for items in missing_alternatives)
            return f"point_in_time_features_unavailable@{as_of.isoformat()}:{rendered}"
    return None


def _hashes(identity: DailyEvidenceRunIdentity):
    return {
        "model_artifact_hash": identity.model_artifact_hash,
        "data_hash": identity.market_data_hash,
        "cost_config_hash": candidate_definition_hash(_thaw(identity.cost_model)),
        "engine_config_hash": candidate_definition_hash({
            "engine_version": identity.engine_version,
            "code_version": identity.code_version,
            "evidence_schema_version": identity.evidence_schema_version,
        }),
    }


def _validate_replay_provenance(replay, *, identity, provider, outcome_start_at, outcome_end_at):
    if not isinstance(replay, Mapping):
        raise ValueError("canonical replay result must be a mapping")
    required = {
        "engine", "engine_version", "cost_model", "start_at", "end_at",
        "feature_cache_hash", "feature_config_hash", "feature_cache_schema_version",
        "feature_source_coverage", "feature_unavailable_counts", "feature_provenance",
        "future_feature_access_count",
    }
    missing = sorted(required - set(replay))
    if missing:
        raise ValueError(f"canonical replay omitted provenance fields: {', '.join(missing)}")
    if replay["engine"] != "scheduler_driven" or replay["engine_version"] != BACKTEST_ENGINE_VERSION:
        raise ValueError("canonical replay engine identity mismatch")
    if identity.engine_version != BACKTEST_ENGINE_VERSION:
        raise ValueError("run identity engine version is not canonical")
    expected_cost = _canonical_cost_model()
    if replay["cost_model"] != expected_cost or _thaw(identity.cost_model) != expected_cost:
        raise ValueError("canonical replay cost model mismatch")
    if replay["start_at"] != outcome_start_at.isoformat() or replay["end_at"] != outcome_end_at.isoformat():
        raise ValueError("canonical replay interval mismatch")
    if replay["future_feature_access_count"] != 0:
        raise ValueError("canonical replay reported future feature access")

    if provider is not None:
        required_provider_fields = (
            "feature_cache_hash", "feature_cache_schema_version", "feature_source_coverage",
            "feature_unavailable_counts", "feature_provenance",
        )
        missing_provider = tuple(field for field in required_provider_fields if not hasattr(provider, field))
        if missing_provider:
            raise ValueError(f"feature provider omitted provenance fields: {', '.join(missing_provider)}")
    expected_cache = getattr(provider, "feature_cache_hash", None) if provider is not None else None
    expected_coverage = getattr(provider, "feature_source_coverage", {}) if provider is not None else {}
    expected_unavailable = getattr(provider, "feature_unavailable_counts", {}) if provider is not None else {}
    expected_provenance = getattr(provider, "feature_provenance", {}) if provider is not None else {}
    expected_schema = getattr(provider, "feature_cache_schema_version", None) if provider is not None else "none"
    expected_config = feature_provider_config_hash(provider)
    actual = {
        "feature_cache_hash": expected_cache,
        "feature_config_hash": expected_config,
        "feature_cache_schema_version": expected_schema,
        "feature_source_coverage": expected_coverage,
        "feature_unavailable_counts": expected_unavailable,
        "feature_provenance": expected_provenance,
    }
    for field, value in actual.items():
        if replay[field] != value:
            label = field.removeprefix("feature_").replace("_", " ")
            raise ValueError(f"canonical replay {label} mismatch")
    if provider is not None and expected_schema is None:
        raise ValueError("feature cache schema is required")
    if provider is not None and (
        _SHA256.fullmatch(str(expected_cache)) is None
        or not isinstance(expected_coverage, Mapping)
        or not isinstance(expected_unavailable, Mapping)
        or not isinstance(expected_provenance, Mapping)
    ):
        raise ValueError("feature provider provenance values are invalid")
    if identity.feature_cache_hash != expected_cache:
        raise ValueError("run identity feature cache hash mismatch")
    if identity.feature_config_hash != expected_config:
        raise ValueError("run identity feature config hash mismatch")
    if identity.feature_cache_schema_version != expected_schema:
        raise ValueError("run identity feature cache schema mismatch")
    if identity.feature_provenance_hash != candidate_definition_hash(expected_provenance):
        raise ValueError("run identity feature provenance mismatch")
    if identity.feature_source_coverage_hash != candidate_definition_hash(expected_coverage):
        raise ValueError("run identity feature source coverage mismatch")
    if identity.feature_unavailable_counts_hash != candidate_definition_hash(expected_unavailable):
        raise ValueError("run identity feature unavailable counts mismatch")


def _base_evidence_fields(entry, identity, component_fingerprint, outcome_start_at):
    return {
        "component_fingerprint": component_fingerprint,
        "candidate_id": entry.candidate_id,
        "cluster_anchor_at": outcome_start_at,
        "feature_start_at": outcome_start_at - timedelta(days=3),
        "feature_end_at": outcome_start_at,
        "outcome_start_at": outcome_start_at,
        "outcome_end_at": outcome_start_at + timedelta(days=1),
        "initial_equity": identity.initial_equity,
        "candidate_hash": entry.definition_hash,
        **_hashes(identity),
    }


def _unavailable_evidence(*, reason, entry, run_identity, component_fingerprint, outcome_start_at):
    zero = Decimal(0)
    return DailyStrategyEvidence(
        **_base_evidence_fields(entry, run_identity, component_fingerprint, outcome_start_at),
        final_equity=run_identity.initial_equity, gross_pnl=zero, net_pnl=zero,
        gross_return_ratio=zero, net_return_ratio=zero, fees=zero, closed_trade_count=0,
        exposure_ratio=zero, turnover_ratio=zero, maximum_drawdown_ratio=zero,
        maximum_adverse_excursion_ratio=zero, profit_factor=None,
        profit_factor_status="no_realized_pnl",
        downside_deviation_ratio=zero, expected_shortfall_10_ratio=zero,
        median_daily_return_ratio=zero, tenth_percentile_daily_return_ratio=zero,
        worst_seven_day_return_ratio=zero, return_without_best_episode_ratio=zero,
        top_episode_profit_share=zero, top_five_trade_profit_share=zero,
        availability_status="unavailable", availability_reason=reason, trade_pnls=None,
    )


def _available_evidence(replay, *, entry, run_identity, component_fingerprint,
                        outcome_start_at, market):
    """Map one canonical day to the domain's finite single-day statistics.

    Profit factor uses net trade PnLs with an explicit undefined status when
    there is no loss denominator. With one daily observation, median, p10, ES10, and worst-7-day
    are that observation; downside deviation is its negative-part magnitude;
    removing the sole best episode yields zero.
    """
    required = {"candidate_id", "candidate_definition_hash", "initial_equity", "final_equity",
                "gross_pnl", "net_pnl", "fee_paid", "return_ratio", "max_drawdown_ratio",
                "maximum_adverse_excursion_ratio", "trade_count", "trades", "position_open_at_end"}
    missing = sorted(required - set(replay))
    if missing:
        raise ValueError(f"canonical replay omitted required daily evidence fields: {', '.join(missing)}")
    if replay["candidate_id"] != entry.candidate_id or replay["candidate_definition_hash"] != entry.definition_hash:
        raise ValueError("canonical replay candidate hash mismatch")
    if replay["position_open_at_end"] is not False:
        raise ValueError("canonical daily replay left a position open")
    initial = _replay_decimal(replay["initial_equity"], "initial equity", positive=True)
    final = _replay_decimal(replay["final_equity"], "final equity")
    gross = _replay_decimal(replay["gross_pnl"], "gross PnL")
    net = _replay_decimal(replay["net_pnl"], "net PnL")
    fees = _replay_decimal(replay["fee_paid"], "fees", nonnegative=True)
    if initial != run_identity.initial_equity or final != initial + net or gross - fees != net:
        raise ValueError("canonical replay accounting does not reconcile")
    if not isinstance(replay["trades"], list):
        raise ValueError("canonical replay trades must be a JSON list")
    trades = tuple(replay["trades"])
    if (not isinstance(replay["trade_count"], int) or isinstance(replay["trade_count"], bool)
            or replay["trade_count"] < 0 or replay["trade_count"] != len(trades)):
        raise ValueError("canonical replay trade count mismatch")
    audited = tuple(_validate_trade_payload(trade, entry) for trade in trades)
    with decimal_arithmetic_context():
        trade_pnls = tuple(item["net_pnl"] for item in audited)
        trade_gross = sum((item["gross_pnl"] for item in audited), Decimal(0))
        trade_fees = sum((item["fee_paid"] for item in audited), Decimal(0))
        if sum(trade_pnls, Decimal(0)) != net or trade_gross != gross or trade_fees != fees:
            raise ValueError("canonical replay trade ledger does not reconcile")
        positive = sum((value for value in trade_pnls if value > 0), Decimal(0))
        negative = -sum((value for value in trade_pnls if value < 0), Decimal(0))
        profit_factor = positive / negative if negative else None
        profit_factor_status = (
            "finite" if negative else "positive_without_losses" if positive else "no_realized_pnl"
        )
        exposure = sum((Decimal(item["holding_bars"]) for item in audited), Decimal(0)) / Decimal(1440)
        if not Decimal(0) <= exposure <= Decimal(1):
            raise ValueError("canonical replay exposure is outside one isolated day")
        turnover = sum((
            (item["entry_price"] + item["exit_price"]) * item["quantity"] for item in audited
        ), Decimal(0)) / initial
        daily_return = net / initial
    reported_return = _replay_decimal(replay["return_ratio"], "return ratio")
    if reported_return != daily_return:
        raise ValueError("canonical replay return ratio mismatch")
    drawdown = _replay_decimal(replay["max_drawdown_ratio"], "maximum drawdown", nonnegative=True)
    aggregate_mae = _replay_decimal(
        replay["maximum_adverse_excursion_ratio"], "maximum adverse excursion", nonnegative=True
    )
    expected_mae = max((item["maximum_adverse_excursion_ratio"] for item in audited), default=Decimal(0))
    if aggregate_mae != expected_mae:
        raise ValueError("canonical replay maximum adverse excursion aggregate mismatch")
    downside = -daily_return if daily_return < 0 else Decimal(0)
    top_five = (
        sum(sorted((value for value in trade_pnls if value > 0), reverse=True)[:5], Decimal(0)) / positive
        if positive else Decimal(0)
    )
    return DailyStrategyEvidence(
        **_base_evidence_fields(entry, run_identity, component_fingerprint, outcome_start_at),
        final_equity=final, gross_pnl=gross, net_pnl=net,
        gross_return_ratio=gross / initial, net_return_ratio=daily_return, fees=fees,
        closed_trade_count=len(trades), exposure_ratio=exposure, turnover_ratio=turnover,
        maximum_drawdown_ratio=drawdown,
        maximum_adverse_excursion_ratio=aggregate_mae,
        profit_factor=profit_factor,
        profit_factor_status=profit_factor_status,
        downside_deviation_ratio=downside, expected_shortfall_10_ratio=daily_return,
        median_daily_return_ratio=daily_return, tenth_percentile_daily_return_ratio=daily_return,
        worst_seven_day_return_ratio=daily_return, return_without_best_episode_ratio=Decimal(0),
        top_episode_profit_share=Decimal(1) if net > 0 else Decimal(0),
        top_five_trade_profit_share=top_five, availability_status="available",
        availability_reason=None, trade_pnls=trade_pnls,
    )


_REQUIRED_TRADE_FIELDS = frozenset({
    "entry_at", "exit_at", "entry_price", "exit_price", "direction", "quantity",
    "margin", "gross_pnl", "net_pnl", "fee_paid", "exit_reason", "holding_bars",
    "owner_strategy_profile_id", "owner_candidate_definition_hash", "owner_guard_hash",
    "owner_leverage", "owner_max_holding_bars", "maximum_adverse_excursion_ratio",
})


def _replay_decimal(value, field, *, positive=False, nonnegative=False):
    try:
        result = Decimal(str(value))
    except Exception as error:
        raise ValueError(f"canonical replay {field} must be a decimal") from error
    if not result.is_finite() or (positive and result <= 0) or (nonnegative and result < 0):
        raise ValueError(f"canonical replay {field} is invalid")
    return result


def _validate_trade_payload(trade, entry):
    if not isinstance(trade, Mapping):
        raise ValueError("canonical replay trade must be an object")
    missing = sorted(_REQUIRED_TRADE_FIELDS - set(trade))
    if missing:
        raise ValueError(f"canonical replay trade omitted {' '.join(missing).replace('_', ' ')}")
    holding = trade["holding_bars"]
    if not isinstance(holding, int) or isinstance(holding, bool) or holding < 0:
        raise ValueError("canonical replay trade holding bars is invalid")
    if trade["direction"] not in {"long", "short"}:
        raise ValueError("canonical replay trade direction is invalid")
    if not isinstance(trade["exit_reason"], str) or not trade["exit_reason"]:
        raise ValueError("canonical replay trade exit reason is invalid")
    if trade["owner_strategy_profile_id"] != entry.candidate_id:
        raise ValueError("canonical replay trade owner candidate mismatch")
    if trade["owner_candidate_definition_hash"] != entry.definition_hash:
        raise ValueError("canonical replay trade owner candidate hash mismatch")
    if _SHA256.fullmatch(str(trade["owner_guard_hash"])) is None:
        raise ValueError("canonical replay trade owner guard hash is invalid")
    if (not isinstance(trade["owner_max_holding_bars"], int)
            or isinstance(trade["owner_max_holding_bars"], bool)
            or trade["owner_max_holding_bars"] <= 0):
        raise ValueError("canonical replay trade owner maximum holding bars is invalid")
    for field in ("entry_at", "exit_at"):
        try:
            timestamp = datetime.fromisoformat(str(trade[field]))
        except ValueError as error:
            raise ValueError(f"canonical replay trade {field.replace('_', ' ')} is invalid") from error
        if timestamp.tzinfo is not timezone.utc:
            raise ValueError(f"canonical replay trade {field.replace('_', ' ')} must be canonical UTC")
    audited = {
        "entry_price": _replay_decimal(trade["entry_price"], "trade entry price", positive=True),
        "exit_price": _replay_decimal(trade["exit_price"], "trade exit price", positive=True),
        "quantity": _replay_decimal(trade["quantity"], "trade quantity", positive=True),
        "margin": _replay_decimal(trade["margin"], "trade margin", positive=True),
        "gross_pnl": _replay_decimal(trade["gross_pnl"], "trade gross PnL"),
        "net_pnl": _replay_decimal(trade["net_pnl"], "trade net PnL"),
        "fee_paid": _replay_decimal(trade["fee_paid"], "trade fees", nonnegative=True),
        "holding_bars": holding,
        "maximum_adverse_excursion_ratio": _replay_decimal(
            trade["maximum_adverse_excursion_ratio"], "trade maximum adverse excursion", nonnegative=True
        ),
    }
    _replay_decimal(trade["owner_leverage"], "trade owner leverage", positive=True)
    expected_gross = (
        (audited["exit_price"] - audited["entry_price"]) * audited["quantity"]
        if trade["direction"] == "long"
        else (audited["entry_price"] - audited["exit_price"]) * audited["quantity"]
    )
    if audited["gross_pnl"] != expected_gross or audited["gross_pnl"] - audited["fee_paid"] != audited["net_pnl"]:
        raise ValueError("canonical replay trade accounting does not reconcile")
    return audited


def _evidence_from_payload(payload: Mapping[str, object]) -> DailyStrategyEvidence:
    decimals = {
        "initial_equity", "final_equity", "gross_pnl", "net_pnl", "gross_return_ratio",
        "net_return_ratio", "fees", "exposure_ratio", "turnover_ratio",
        "maximum_drawdown_ratio", "maximum_adverse_excursion_ratio",
        "downside_deviation_ratio", "expected_shortfall_10_ratio", "median_daily_return_ratio",
        "tenth_percentile_daily_return_ratio", "worst_seven_day_return_ratio",
        "return_without_best_episode_ratio", "top_episode_profit_share", "top_five_trade_profit_share",
    }
    values = {name: Decimal(str(payload[name])) for name in decimals}
    return DailyStrategyEvidence(
        component_fingerprint=str(payload["component_fingerprint"]),
        candidate_id=str(payload["candidate_id"]),
        cluster_anchor_at=datetime.fromisoformat(str(payload["cluster_anchor_at"])),
        feature_start_at=datetime.fromisoformat(str(payload["feature_interval"]["start_at"])),
        feature_end_at=datetime.fromisoformat(str(payload["feature_interval"]["end_at"])),
        outcome_start_at=datetime.fromisoformat(str(payload["outcome_interval"]["start_at"])),
        outcome_end_at=datetime.fromisoformat(str(payload["outcome_interval"]["end_at"])),
        closed_trade_count=int(payload["closed_trade_count"]),
        availability_status=str(payload["availability_status"]),
        availability_reason=payload["availability_reason"],
        candidate_hash=str(payload["candidate_hash"]), model_artifact_hash=str(payload["model_artifact_hash"]),
        data_hash=str(payload["data_hash"]), cost_config_hash=str(payload["cost_config_hash"]),
        engine_config_hash=str(payload["engine_config_hash"]),
        profit_factor=None if payload["profit_factor"] is None else Decimal(str(payload["profit_factor"])),
        profit_factor_status=str(payload["profit_factor_status"]),
        trade_pnls=None if payload["trade_pnls"] is None else tuple(Decimal(str(value)) for value in payload["trade_pnls"]),
        **values,
    )


class LoadedEvidenceRows(list[dict[str, object]]):
    def __init__(self, rows=(), *, recovery_metadata=None):
        super().__init__(rows)
        self.recovery_metadata = dict(recovery_metadata or {})


class AppendOnlyEvidenceLedger:
    def __init__(self, path: Path, key_fields: Sequence[str], *, strict_identity: bool = True):
        self.path = Path(path)
        self.key_fields = tuple(key_fields)
        if not self.key_fields or len(set(self.key_fields)) != len(self.key_fields):
            raise ValueError("ledger key fields must be nonempty and unique")
        self.strict_identity = strict_identity

    def _key(self, row: Mapping[str, object]) -> tuple[object, ...]:
        try:
            key = tuple(row[field] for field in self.key_fields)
        except KeyError as error:
            raise ValueError(f"ledger row is missing identity field: {error.args[0]}") from error
        if any(value is None or value == "" for value in key):
            raise ValueError("ledger row identity fields must be nonempty")
        return key

    def load(self) -> LoadedEvidenceRows:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with evidence_file_lock(self.path):
            return self._load_unlocked()

    def _load_unlocked(self) -> LoadedEvidenceRows:
        if not self.path.exists():
            return LoadedEvidenceRows()
        rows = []
        seen = {}
        recovery = {}
        with self.path.open("rb") as handle:
            line_number = 0
            while True:
                offset = handle.tell()
                raw = handle.readline()
                if not raw:
                    break
                line_number += 1
                if not raw.strip():
                    continue
                if not raw.endswith(b"\n"):
                    digest = hashlib.sha256(raw).hexdigest()
                    quarantine = self.path.with_name(
                        f"{self.path.name}.truncated-{digest[:12]}.jsonl"
                    )
                    if not quarantine.exists():
                        quarantine.write_bytes(raw)
                    with self.path.open("r+b") as output:
                        output.truncate(offset)
                        output.flush()
                        os.fsync(output.fileno())
                    recovery["truncated_final_line"] = {
                        "line_number": line_number,
                        "quarantine_path": str(quarantine),
                        "sha256": digest,
                        "truncated_to_byte": offset,
                    }
                    break
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError(f"malformed interior JSONL row on line {line_number}") from error
                if not isinstance(row, dict):
                    raise ValueError(f"JSONL row on line {line_number} must be an object")
                key = self._key(row)
                existing = seen.get(key)
                if existing is None:
                    seen[key] = row
                    rows.append(row)
                elif existing != row:
                    raise ValueError(f"conflicting duplicate ledger key: {key}")
        if self.strict_identity and rows:
            identities = {row.get("run_identity") for row in rows}
            if len(identities) != 1:
                raise ValueError("mixed run_identity values in evidence ledger")
        rows.sort(key=lambda row: tuple(str(row[field]) for field in self.key_fields))
        return LoadedEvidenceRows(rows, recovery_metadata=recovery)

    def append(self, row: Mapping[str, object], *, rows_loader=None, lock_factory=None) -> bool:
        normalized = json.loads(_canonical_json(dict(row)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        selected_lock = lock_factory or evidence_file_lock
        with selected_lock(self.path):
            rows = rows_loader() if rows_loader is not None else self._load_unlocked()
            if self.strict_identity and rows and rows[0].get("run_identity") != normalized.get("run_identity"):
                raise ValueError("run_identity does not match existing evidence ledger")
            key = self._key(normalized)
            existing = next((item for item in rows if self._key(item) == key), None)
            if existing is not None:
                if existing != normalized:
                    raise ValueError(f"conflicting duplicate ledger key: {key}")
                return False
            encoded = (_canonical_json(normalized) + "\n").encode("utf-8")
            descriptor = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
            try:
                written = os.write(descriptor, encoded)
                if written != len(encoded):
                    raise OSError("incomplete JSONL row append")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return True


def evidence_lock_path(path: Path) -> Path:
    path = Path(path)
    return path.with_name(f"{path.name}.lock")


@contextmanager
def evidence_file_lock(path: Path, *, timeout_seconds: float = 10.0, stale_seconds: float = 300.0):
    lock_path = evidence_lock_path(path)
    deadline = time.monotonic() + timeout_seconds
    token = uuid.uuid4().hex
    owner = {"pid": os.getpid(), "token": token, "created_at": time.time()}
    encoded = _canonical_json(owner).encode("utf-8")
    owned_stat = None
    while owned_stat is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            recover_evidence_file_lock_if_stale(lock_path, stale_seconds=stale_seconds)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for evidence lock: {lock_path}")
            time.sleep(0.01)
            continue
        try:
            if os.write(descriptor, encoded) != len(encoded):
                raise OSError("incomplete evidence lock metadata write")
            os.fsync(descriptor)
            owned_stat = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    try:
        yield
    finally:
        cleanup_owned_evidence_file_lock(
            lock_path, token=token, pid=os.getpid(), inode=owned_stat.st_ino
        )


def cleanup_owned_evidence_file_lock(
    lock_path: Path, *, token: str, pid: int, inode: int, timeout_seconds: float = 1.0
):
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            stat = lock_path.stat()
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, UnicodeError, json.JSONDecodeError):
            if time.monotonic() >= deadline:
                raise OSError(f"could not verify owned evidence lock: {lock_path}")
            time.sleep(0.005)
            continue
        if (stat.st_ino != inode or not isinstance(metadata, dict)
                or metadata.get("token") != token or metadata.get("pid") != pid):
            return
        try:
            lock_path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)


def recover_evidence_file_lock_if_stale(lock_path: Path, *, stale_seconds: float) -> bool:
    try:
        observed = lock_path.stat()
        raw = lock_path.read_bytes()
    except FileNotFoundError:
        return True
    try:
        metadata = json.loads(raw.decode("utf-8"))
        pid = metadata["pid"]
        valid = isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        valid = False
        pid = 0
    recoverable = (
        time.time() - observed.st_mtime >= stale_seconds
        if not valid else not _process_is_alive(pid)
    )
    if not recoverable:
        return False
    try:
        if lock_path.stat().st_ino != observed.st_ino or lock_path.read_bytes() != raw:
            return False
        lock_path.unlink()
        return True
    except FileNotFoundError:
        return True


def _process_is_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError):
        return False
    return True


def _windows_process_is_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    not_found = {87, 1168}
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        return error == error_access_denied or error not in not_found
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            error = ctypes.get_last_error()
            return error == error_access_denied or error not in not_found
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


__all__ = [
    "AppendOnlyEvidenceLedger",
    "DAILY_EVIDENCE_CODE_VERSION",
    "DAILY_EVIDENCE_KEY_FIELDS",
    "DAILY_EVIDENCE_SCHEMA_VERSION",
    "DailyCandidateManifestEntry",
    "LoadedEvidenceRows",
    "ThreeDayDailyCandidateManifest",
    "build_three_day_daily_candidate_manifest",
    "market_snapshot_hash",
]
