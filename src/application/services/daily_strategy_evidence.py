"""Frozen daily candidate research universe and resumable evidence primitives."""

from __future__ import annotations

import hashlib
import json
import os
import time
import re
from fnmatch import fnmatchcase
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence

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

_EXPECTED_CANDIDATE_GROUPS = frozenset({
    "all", "alpha", "counter", "discovered", "exact", "metrics", "microstructure", "multi",
})
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class DailyCandidateCatalog:
    candidate_groups: Mapping[str, Sequence[object]]
    deferred_registry: Mapping[str, object]
    candidate_id_validator: Callable[[Sequence[str]], None]
    candidate_payload_builder: Callable[[object], Mapping[str, object]]


@dataclass(frozen=True)
class DailyEvidenceReplayContract:
    replay: Callable[..., Mapping[str, object]]
    engine_name: str
    engine_version: str
    cost_model: Mapping[str, object]
    timeframe: object
    timeframe_label: str
    warmup_resolver: Callable[[Sequence[object], object | None], int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cost_model", _freeze(dict(self.cost_model)))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def candidate_definition_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def feature_provider_config_hash(provider) -> str | None:
    if provider is None:
        return None
    return candidate_definition_hash({
        "provider": type(provider).__name__,
        "declared_config_hash": getattr(provider, "feature_config_hash", None),
        "feature_cache_hash": getattr(provider, "feature_cache_hash", None),
        "feature_source_coverage": getattr(provider, "feature_source_coverage", {}),
        "feature_unavailable_counts": getattr(provider, "feature_unavailable_counts", {}),
        "feature_provenance": getattr(provider, "feature_provenance", {"provider": type(provider).__name__}),
    })


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
    candidate: object
    canonical_candidate_payload: Mapping[str, object]
    definition_hash: str
    required_feature_alternatives: tuple[tuple[tuple[str, tuple[str, ...]], ...], ...]
    deferred_groups: tuple[tuple[str, str], ...]
    deferred_pattern_provenance: tuple[tuple[str, str, str], ...]


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
    candidate_manifest_hash: str
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
            "model_artifact_hash", "candidate_manifest_hash", "candidate_universe_hash", "market_data_hash",
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
            "candidate_manifest_hash": self.candidate_manifest_hash,
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
    catalog: DailyCandidateCatalog,
    expected_count: int = EXPECTED_THREE_DAY_DAILY_CANDIDATE_COUNT,
) -> ThreeDayDailyCandidateManifest:
    """Freeze the explicit, opt-in three-day/daily research universe."""
    registry = catalog.deferred_registry
    status_by_group = {
        str(family["candidate_group"]): str(family["status"])
        for family in registry["families"]
    }
    supplied = catalog.candidate_groups
    if set(supplied) != _EXPECTED_CANDIDATE_GROUPS:
        raise ValueError("candidate manifest requires exactly all eight public groups")
    if any(not tuple(candidates) for candidates in supplied.values()):
        raise ValueError("every public candidate group must be nonempty")
    unknown_groups = sorted(set(supplied) - set(status_by_group))
    if unknown_groups:
        raise ValueError(f"candidate groups are absent from deferred registry: {', '.join(unknown_groups)}")

    by_id: dict[str, tuple[object, dict[str, object], str]] = {}
    groups_by_id: dict[str, set[tuple[str, str]]] = {}
    patterns_by_id: dict[str, set[tuple[str, str, str]]] = {}
    for group in sorted(supplied):
        candidates = tuple(supplied[group])
        catalog.candidate_id_validator(tuple(candidate.candidate_id for candidate in candidates))
        for candidate in candidates:
            payload = dict(catalog.candidate_payload_builder(candidate))
            definition_hash = candidate_definition_hash(payload)
            existing = by_id.get(candidate.candidate_id)
            if existing is not None and (
                existing[2] != definition_hash or existing[1] != payload
            ):
                raise ValueError(
                    f"conflicting duplicate candidate_id definition: {candidate.candidate_id}"
                )
            by_id.setdefault(candidate.candidate_id, (candidate, payload, definition_hash))
            matched_patterns = {
                (str(family["candidate_group"]), str(family["status"]), str(pattern))
                for family in registry["families"]
                for pattern in family["candidate_id_patterns"]
                if fnmatchcase(candidate.candidate_id, pattern)
            }
            if not matched_patterns:
                raise ValueError(
                    f"candidate_id has no deferred registry provenance: {candidate.candidate_id}"
                )
            patterns_by_id.setdefault(candidate.candidate_id, set()).update(matched_patterns)
            groups_by_id.setdefault(candidate.candidate_id, set()).update(
                (group, status) for group, status, _pattern in matched_patterns
            )

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
            deferred_pattern_provenance=tuple(sorted(patterns_by_id[candidate_id])),
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
                "deferred_pattern_provenance": [list(item) for item in entry.deferred_pattern_provenance],
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


RequirementAlternatives = tuple[dict[str, tuple[str, ...]], ...]


def _configured_sources(params: Mapping[str, object], name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = params.get(name, default)
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise ValueError(f"strategy feature source field {name} must be a sequence")
    sources = tuple(value)
    if not sources or any(not isinstance(source, str) or not source for source in sources):
        raise ValueError(f"strategy feature source field {name} is invalid")
    return sources


def _no_feature_requirements(_params: Mapping[str, object]) -> RequirementAlternatives:
    return ({},)


def _flow_requirements(params: Mapping[str, object], *, intensity: bool) -> RequirementAlternatives:
    required = {
        "taker_imbalance": _configured_sources(params, "taker_imbalance_sources", ("klines", "aggTrades")),
        "cvd_delta": _configured_sources(params, "cvd_delta_sources", ("aggTrades",)),
    }
    if intensity:
        required["trade_intensity"] = _configured_sources(params, "trade_intensity_sources", ("aggTrades",))
    return (required,)


def _premium_requirements(params: Mapping[str, object]) -> RequirementAlternatives:
    flow = _flow_requirements(params, intensity=False)[0]
    return (
        {**flow, "premium_index": _configured_sources(params, "premium_sources", ("premiumIndexKlines",))},
        {**flow,
         "mark_price": _configured_sources(params, "mark_sources", ("markPriceKlines",)),
         "index_price": _configured_sources(params, "index_sources", ("indexPriceKlines",))},
    )


def _micro_router_requirements(params: Mapping[str, object]) -> RequirementAlternatives:
    # The canonical router always evaluates all default legs; a disabled/missing leg
    # must therefore be represented in point-in-time availability.
    return _combine_requirement_alternatives((
        _no_feature_requirements({}),
        _flow_requirements(params, intensity=True),
        _flow_requirements(params, intensity=True),
        _flow_requirements(params, intensity=False),
        _premium_requirements(params),
    ))


def _oi_requirements(_params: Mapping[str, object]) -> RequirementAlternatives:
    return ({"open_interest_change_ratio_5m": ("metrics",),
             "taker_long_short_volume_ratio": ("metrics",)},)


def _positioning_requirements(_params: Mapping[str, object]) -> RequirementAlternatives:
    return ({"top_trader_position_long_short_ratio": ("metrics",),
             "global_long_short_ratio": ("metrics",),
             "taker_long_short_volume_ratio": ("metrics",)},)


_STRATEGY_REQUIREMENT_BUILDERS: Mapping[str, Callable[[Mapping[str, object]], RequirementAlternatives]] = MappingProxyType({
    "chart_pattern": _no_feature_requirements,
    "compression": _no_feature_requirements,
    "counter_mtf": _no_feature_requirements,
    "mtf": _no_feature_requirements,
    "range_edge": _no_feature_requirements,
    "regime_router": _no_feature_requirements,
    "flow_breakout": lambda params: _flow_requirements(params, intensity=True),
    "counter_flow_breakout": lambda params: _flow_requirements(params, intensity=True),
    "flow_exhaustion": lambda params: _flow_requirements(params, intensity=False),
    "counter_flow_exhaustion": lambda params: _flow_requirements(params, intensity=False),
    "session_range": lambda params: _flow_requirements(params, intensity=True),
    "counter_session_range": lambda params: _flow_requirements(params, intensity=True),
    "premium_funding": _premium_requirements,
    "micro_router": _micro_router_requirements,
    "counter_micro_router": _micro_router_requirements,
    "oi_impulse": _oi_requirements,
    "oi_divergence": _oi_requirements,
    "positioning_crowding": _positioning_requirements,
    "global_ratio_shock": lambda _params: ({"global_long_short_change_5m": ("metrics",)},),
})
SUPPORTED_STRATEGY_REQUIREMENT_KINDS = frozenset(_STRATEGY_REQUIREMENT_BUILDERS)


def _strategy_spec_feature_requirements(spec: object) -> RequirementAlternatives:
    kind = getattr(spec, "kind", None)
    params = getattr(spec, "params", None)
    if not isinstance(kind, str) or not isinstance(params, Mapping):
        raise ValueError("strategy candidate spec must expose typed kind and params")
    builder = _STRATEGY_REQUIREMENT_BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"unsupported strategy candidate kind: {kind}")
    return builder(params)


def candidate_feature_requirements(candidate: object) -> RequirementAlternatives:
    return _combine_requirement_alternatives(
        tuple(_strategy_spec_feature_requirements(spec) for spec in candidate.strategies)
    )


def _candidate_feature_requirements(candidate: object):
    alternatives = candidate_feature_requirements(candidate)
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
    replay_contract: DailyEvidenceReplayContract,
    symbol: Symbol | None = None,
    candidate_ids: Sequence[str] = (),
) -> tuple[DailyStrategyEvidence, ...]:
    """Run isolated one-day canonical evidence, resuming only an exact identity."""
    if outcome_start_at.tzinfo is not timezone.utc or outcome_start_at.time() != datetime.min.time():
        raise ValueError("daily outcome start must be canonical midnight UTC")
    outcome_end_at = outcome_start_at + timedelta(days=1)
    replay = replay_contract.replay
    selected_symbol = symbol or market.symbol
    provider_snapshot = _provider_identity_snapshot(market_feature_provider)
    _validate_static_run_context(
        manifest=manifest, phase=phase, outcome_start_at=outcome_start_at,
        outcome_end_at=outcome_end_at, market=market, provider_snapshot=provider_snapshot,
        identity=run_identity, selected_symbol=selected_symbol, replay_contract=replay_contract,
    )
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
        warmup = replay_contract.warmup_resolver((entry.candidate,), market_feature_provider)
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
            if _provider_identity_snapshot(market_feature_provider) != provider_snapshot:
                raise ValueError("feature provider identity mutated during canonical replay")
            _validate_replay_provenance(
                replay_result,
                identity=run_identity,
                provider_snapshot=provider_snapshot,
                replay_contract=replay_contract,
                outcome_start_at=outcome_start_at,
                outcome_end_at=outcome_end_at,
            )
            evidence = _available_evidence(
                replay_result, entry=entry, run_identity=run_identity,
                component_fingerprint=component_fingerprint,
                outcome_start_at=outcome_start_at, market=market,
            )
        else:
            if _provider_identity_snapshot(market_feature_provider) != provider_snapshot:
                raise ValueError("feature provider identity mutated during availability evaluation")
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


def _validate_replay_provenance(replay, *, identity, provider_snapshot, replay_contract,
                                outcome_start_at, outcome_end_at):
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
    if replay["engine"] != replay_contract.engine_name or replay["engine_version"] != replay_contract.engine_version:
        raise ValueError("canonical replay engine identity mismatch")
    expected_cost = _thaw(replay_contract.cost_model)
    if replay["cost_model"] != expected_cost:
        raise ValueError("canonical replay cost model mismatch")
    if replay["start_at"] != outcome_start_at.isoformat() or replay["end_at"] != outcome_end_at.isoformat():
        raise ValueError("canonical replay interval mismatch")
    if replay["future_feature_access_count"] != 0:
        raise ValueError("canonical replay reported future feature access")

    provider_values = _thaw(provider_snapshot)
    actual = {
        "feature_cache_hash": provider_values["cache_hash"],
        "feature_config_hash": provider_values["config_hash"],
        "feature_cache_schema_version": provider_values["schema_version"],
        "feature_source_coverage": provider_values["source_coverage"],
        "feature_unavailable_counts": provider_values["unavailable_counts"],
        "feature_provenance": provider_values["provenance"],
    }
    for field, value in actual.items():
        if replay[field] != value:
            label = field.removeprefix("feature_").replace("_", " ")
            raise ValueError(f"canonical replay {label} mismatch")
    identity_claims = {
        "feature_cache_hash": identity.feature_cache_hash,
        "feature_config_hash": identity.feature_config_hash,
        "feature_cache_schema_version": identity.feature_cache_schema_version,
        "feature_source_coverage": identity.feature_source_coverage_hash,
        "feature_unavailable_counts": identity.feature_unavailable_counts_hash,
        "feature_provenance": identity.feature_provenance_hash,
    }
    for field, claim in identity_claims.items():
        observed = replay[field] if field in {
            "feature_cache_hash", "feature_config_hash", "feature_cache_schema_version"
        } else candidate_definition_hash(replay[field])
        if observed != claim:
            raise ValueError(f"canonical replay {field} conflicts with frozen run identity")


def _validate_static_run_context(*, manifest, phase, outcome_start_at, outcome_end_at,
                                 market, provider_snapshot, identity, selected_symbol,
                                 replay_contract):
    if identity.engine_version != replay_contract.engine_version:
        raise ValueError("run identity engine version is not canonical")
    if _thaw(identity.cost_model) != _thaw(replay_contract.cost_model):
        raise ValueError("run identity cost model is not canonical")
    if phase != identity.phase or not (
        identity.phase_start_at <= outcome_start_at < outcome_end_at <= identity.phase_end_at
    ):
        raise ValueError("daily outcome is outside the run identity phase interval")
    if manifest.candidate_universe_hash != identity.candidate_universe_hash:
        raise ValueError("candidate universe hash does not match run identity")
    if manifest.manifest_hash != identity.candidate_manifest_hash:
        raise ValueError("candidate manifest hash does not match run identity")
    if manifest.ordered_definition_hashes != identity.ordered_candidate_definition_hashes:
        raise ValueError("candidate definition hashes do not match run identity")
    if market_snapshot_hash(market) != identity.market_data_hash:
        raise ValueError("market data hash does not match run identity")
    if selected_symbol != market.symbol or selected_symbol.pair != identity.symbol:
        raise ValueError("market symbol does not match run identity")
    if market.timeframe != replay_contract.timeframe or identity.timeframe != replay_contract.timeframe_label:
        raise ValueError("daily evidence requires the canonical 1m timeframe")
    if not isinstance(identity.initial_equity, Decimal) or identity.initial_equity <= 0:
        raise ValueError("initial equity is invalid")
    actual = _thaw(provider_snapshot)
    comparisons = (
        (identity.feature_cache_hash, actual["cache_hash"], "cache hash"),
        (identity.feature_config_hash, actual["config_hash"], "config hash"),
        (identity.feature_cache_schema_version, actual["schema_version"], "schema"),
        (identity.feature_provenance_hash, candidate_definition_hash(actual["provenance"]), "provenance"),
        (identity.feature_source_coverage_hash, candidate_definition_hash(actual["source_coverage"]), "coverage"),
        (identity.feature_unavailable_counts_hash, candidate_definition_hash(actual["unavailable_counts"]), "unavailable counts"),
    )
    for claimed, observed, label in comparisons:
        if claimed != observed:
            raise ValueError(f"run identity feature {label} mismatch")


def _actual_provider_identity(provider):
    if provider is None:
        return {
            "cache_hash": None, "config_hash": None, "schema_version": "none",
            "source_coverage": {}, "unavailable_counts": {}, "provenance": {},
        }
    required = (
        "feature_cache_hash", "feature_cache_schema_version", "feature_source_coverage",
        "feature_unavailable_counts", "feature_provenance",
    )
    missing = tuple(field for field in required if not hasattr(provider, field))
    if missing:
        raise ValueError(f"feature provider omitted provenance fields: {', '.join(missing)}")
    values = {
        "cache_hash": provider.feature_cache_hash,
        "config_hash": feature_provider_config_hash(provider),
        "schema_version": provider.feature_cache_schema_version,
        "source_coverage": provider.feature_source_coverage,
        "unavailable_counts": provider.feature_unavailable_counts,
        "provenance": provider.feature_provenance,
    }
    if (
        _SHA256.fullmatch(str(values["cache_hash"])) is None
        or not isinstance(values["schema_version"], str) or not values["schema_version"]
        or type(values["source_coverage"]) is not dict
        or type(values["unavailable_counts"]) is not dict
        or type(values["provenance"]) is not dict
        or any(not isinstance(key, str) or not isinstance(count, int) or isinstance(count, bool) or count < 0
               for key, count in values["source_coverage"].items())
        or any(not isinstance(key, str) or not isinstance(count, int) or isinstance(count, bool) or count < 0
               for key, count in values["unavailable_counts"].items())
    ):
        raise ValueError("feature provider provenance values are invalid")
    return values


def _provider_identity_snapshot(provider):
    """Capture provider provenance by value before availability or replay can mutate it."""
    return _freeze(_actual_provider_identity(provider))


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
    if (
        initial != run_identity.initial_equity
        or not _decimal_reconciles(final, initial + net)
        or not _decimal_reconciles(gross - fees, net)
    ):
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
        if (
            not _decimal_reconciles(sum(trade_pnls, Decimal(0)), net)
            or not _decimal_reconciles(trade_gross, gross)
            or not _decimal_reconciles(trade_fees, fees)
        ):
            raise ValueError("canonical replay trade ledger does not reconcile")
        # Normalize sub-ULP scheduler accumulation noise to the exact domain
        # accounting identities after the independently reported values pass.
        net = gross - fees
        final = initial + net
        if trade_pnls:
            normalized = list(trade_pnls)
            normalized[-1] += net - sum(normalized, Decimal(0))
            trade_pnls = tuple(normalized)
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
    if not _decimal_reconciles(reported_return, daily_return):
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


def _decimal_reconciles(left: Decimal, right: Decimal) -> bool:
    """Allow only accumulated arithmetic noise from the 28-digit replay context."""
    scale = max(Decimal(1), abs(left), abs(right))
    return abs(left - right) <= scale * Decimal("1e-26")


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
        self._index: dict[tuple[object, ...], dict[str, object]] = {}
        self._rows: list[dict[str, object]] = []
        self._file_identity: tuple[int, int] | None = None
        self._verified_offset = 0
        self._line_count = 0
        self._initialized = False
        self._recovery_metadata: dict[str, object] = {}
        self._full_parse_count = 0
        self._parsed_byte_count = 0

    @property
    def full_parse_count(self) -> int:
        return self._full_parse_count

    @property
    def parsed_byte_count(self) -> int:
        return self._parsed_byte_count

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
        self._sync_index_unlocked()
        rows = sorted(
            self._rows,
            key=lambda row: tuple(str(row[field]) for field in self.key_fields),
        )
        return LoadedEvidenceRows(rows, recovery_metadata=self._recovery_metadata)

    def _reset_index(self) -> None:
        self._index = {}
        self._rows = []
        self._file_identity = None
        self._verified_offset = 0
        self._line_count = 0
        self._recovery_metadata = {}

    def _sync_index_unlocked(self) -> None:
        if not self.path.exists():
            if self._initialized:
                self._reset_index()
            self._initialized = True
            return
        stat = self.path.stat()
        identity = (stat.st_dev, stat.st_ino)
        rebuild = (
            not self._initialized
            or self._file_identity != identity
            or stat.st_size < self._verified_offset
        )
        if rebuild:
            self._reset_index()
            self._full_parse_count += 1
        elif stat.st_size == self._verified_offset:
            return
        self._parse_from_offset_unlocked(self._verified_offset)
        current = self.path.stat()
        self._file_identity = (current.st_dev, current.st_ino)
        self._initialized = True

    def _parse_from_offset_unlocked(self, start_offset: int) -> None:
        with self.path.open("rb") as handle:
            handle.seek(start_offset)
            line_number = self._line_count
            while True:
                offset = handle.tell()
                raw = handle.readline()
                if not raw:
                    break
                self._parsed_byte_count += len(raw)
                line_number += 1
                if not raw.strip():
                    self._verified_offset = handle.tell()
                    self._line_count = line_number
                    continue
                if not raw.endswith(b"\n"):
                    self._recovery_metadata["truncated_final_line"] = _recover_truncated_frame(
                        self.path, raw=raw, offset=offset, line_number=line_number
                    )
                    break
                try:
                    row = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise ValueError(f"malformed interior JSONL row on line {line_number}") from error
                if not isinstance(row, dict):
                    raise ValueError(f"JSONL row on line {line_number} must be an object")
                key = self._key(row)
                existing = self._index.get(key)
                if existing is None:
                    self._index[key] = row
                    self._rows.append(row)
                elif existing != row:
                    raise ValueError(f"conflicting duplicate ledger key: {key}")
                self._verified_offset = handle.tell()
                self._line_count = line_number
        if self.strict_identity and self._rows:
            identities = {row.get("run_identity") for row in self._rows}
            if len(identities) != 1:
                raise ValueError("mixed run_identity values in evidence ledger")

    def append(self, row: Mapping[str, object], *, rows_loader=None, lock_factory=None) -> bool:
        normalized = json.loads(_canonical_json(dict(row)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        selected_lock = lock_factory or evidence_file_lock
        with selected_lock(self.path):
            if rows_loader is not None:
                rows = rows_loader()
                index = {self._key(item): item for item in rows}
            else:
                self._sync_index_unlocked()
                rows = self._rows
                index = self._index
            if self.strict_identity and rows and rows[0].get("run_identity") != normalized.get("run_identity"):
                raise ValueError("run_identity does not match existing evidence ledger")
            key = self._key(normalized)
            existing = index.get(key)
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
            if rows_loader is None:
                self._index[key] = normalized
                self._rows.append(normalized)
                stat = self.path.stat()
                self._file_identity = (stat.st_dev, stat.st_ino)
                self._verified_offset = stat.st_size
                self._line_count += 1
                self._initialized = True
        return True


def _recover_truncated_frame(path: Path, *, raw: bytes, offset: int, line_number: int):
    digest = hashlib.sha256(raw).hexdigest()
    quarantine = path.with_name(f"{path.name}.truncated-{digest[:12]}.jsonl")
    _durably_write_quarantine(quarantine, raw)
    _truncate_source_to_offset(path, offset)
    return {
        "line_number": line_number,
        "quarantine_path": str(quarantine),
        "sha256": digest,
        "truncated_to_byte": offset,
    }


def _durably_write_quarantine(path: Path, raw: bytes) -> None:
    descriptor = None
    created = False
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        created = True
    except FileExistsError:
        existing = path.read_bytes()
        if existing != raw:
            raise ValueError(f"conflicting truncated-frame quarantine: {path}")
        descriptor = os.open(path, os.O_RDWR)
    try:
        if created:
            position = 0
            while position < len(raw):
                written = os.write(descriptor, raw[position:])
                if written <= 0:
                    raise OSError("incomplete quarantine frame write")
                position += written
        os.fsync(descriptor)
    except BaseException:
        if created:
            try:
                os.close(descriptor)
            finally:
                descriptor = None
                path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
    _fsync_parent_directory(path.parent)


def _truncate_source_to_offset(path: Path, offset: int) -> None:
    with path.open("r+b") as output:
        output.truncate(offset)
        output.flush()
        os.fsync(output.fileno())


def _fsync_parent_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        return
    finally:
        if descriptor is not None:
            os.close(descriptor)


def evidence_lock_path(path: Path) -> Path:
    path = Path(path)
    return path.with_name(f"{path.name}.lock")


def _try_advisory_lock(descriptor: int) -> bool:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _release_advisory_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def evidence_file_lock(path: Path, *, timeout_seconds: float = 10.0):
    lock_path = evidence_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    acquired = False
    try:
        while not _try_advisory_lock(descriptor):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for evidence lock: {lock_path}")
            time.sleep(0.01)
        acquired = True
        metadata = (_canonical_json({"pid": os.getpid(), "created_at": time.time()}) + "\n").encode()
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        position = 0
        while position < len(metadata):
            written = os.write(descriptor, metadata[position:])
            if written <= 0:
                raise OSError("incomplete evidence lock metadata write")
            position += written
        os.fsync(descriptor)
        yield
    finally:
        try:
            if acquired:
                _release_advisory_lock(descriptor)
        finally:
            os.close(descriptor)


__all__ = [
    "AppendOnlyEvidenceLedger",
    "DAILY_EVIDENCE_CODE_VERSION",
    "DAILY_EVIDENCE_KEY_FIELDS",
    "DAILY_EVIDENCE_SCHEMA_VERSION",
    "DailyCandidateManifestEntry",
    "DailyCandidateCatalog",
    "DailyEvidenceReplayContract",
    "DailyEvidenceRunIdentity",
    "LoadedEvidenceRows",
    "ThreeDayDailyCandidateManifest",
    "build_three_day_daily_candidate_manifest",
    "candidate_feature_requirements",
    "SUPPORTED_STRATEGY_REQUIREMENT_KINDS",
    "run_daily_strategy_evidence",
    "market_snapshot_hash",
]
