from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import hashlib
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.deferred_strategy_registry import load_deferred_strategy_registry
from scripts.scheduler_driven_scalping_backtest import (
    BACKTEST_ENGINE_VERSION,
    FEE_RATE,
    FEATURE_CACHE_SCHEMA_VERSION,
    SLIPPAGE_RATE,
    build_scheduler_candidates,
    candidate_definition_hash,
    feature_provider_config_hash,
    microstructure_alpha_candidates,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.domain.regime.three_day_daily_profile import decimal_arithmetic_context
from src.domain.regime.three_day_daily_profile import PROFILE_ID
from src.domain.regime.three_day_chart_features import THREE_DAY_CHART_FEATURE_SCHEMA_VERSION
from src.application.services.daily_strategy_evidence import (
    DAILY_EVIDENCE_KEY_FIELDS,
    DAILY_EVIDENCE_CODE_VERSION,
    DAILY_EVIDENCE_SCHEMA_VERSION,
    AppendOnlyEvidenceLedger,
    DailyEvidenceRunIdentity,
    build_three_day_daily_candidate_manifest,
    evidence_file_lock,
    evidence_lock_path,
    market_snapshot_hash,
    run_daily_strategy_evidence,
)


def _row(**changes):
    row = {
        "run_identity": "run-a",
        "phase": "Validation",
        "outcome_start_at": "2025-07-10T00:00:00+00:00",
        "component_fingerprint": "component-a",
        "candidate_id": "candidate-a",
        "payload": "same",
    }
    row.update(changes)
    return row


def _all_groups(candidate):
    return {
        group: (candidate,)
        for group in ("all", "alpha", "counter", "discovered", "exact", "metrics", "microstructure", "multi")
    }


def test_three_day_manifest_freezes_exact_repository_universe_without_registry_mutation():
    before = json.dumps(load_deferred_strategy_registry(), sort_keys=True)

    manifest = build_three_day_daily_candidate_manifest()

    assert len(manifest.entries) == 459
    assert manifest.candidate_ids == tuple(sorted(set(manifest.candidate_ids)))
    assert tuple(entry.candidate_id for entry in manifest.entries) == manifest.candidate_ids
    assert all(entry.definition_hash for entry in manifest.entries)
    assert all(entry.required_feature_alternatives for entry in manifest.entries)
    assert {group for entry in manifest.entries for group, _ in entry.deferred_groups} == {
        "all", "alpha", "counter", "discovered", "exact", "metrics", "microstructure", "multi"
    }
    assert {status for entry in manifest.entries for _, status in entry.deferred_groups} == {
        "failed", "deferred", "superseded"
    }
    assert manifest == build_three_day_daily_candidate_manifest()
    assert json.dumps(load_deferred_strategy_registry(), sort_keys=True) == before


def test_manifest_collapses_identical_duplicates_and_rejects_conflicting_definitions():
    candidate = build_scheduler_candidates()[0]
    collapsed = build_three_day_daily_candidate_manifest(
        candidate_groups={**_all_groups(candidate), "all": (candidate, candidate)}, expected_count=1
    )
    assert collapsed.candidate_ids == (candidate.candidate_id,)
    assert collapsed.entries[0].deferred_groups == (("all", "failed"),)

    conflicting = replace(candidate, equity_ratio=candidate.equity_ratio * 2)
    with pytest.raises(ValueError, match="conflicting.*candidate_id"):
        build_three_day_daily_candidate_manifest(
            candidate_groups={**_all_groups(candidate), "all": (candidate, conflicting)}, expected_count=1
        )


def test_manifest_count_is_a_repository_snapshot_drift_alarm():
    candidate = build_scheduler_candidates()[0]
    with pytest.raises(ValueError, match="expected 459.*found 1"):
        build_three_day_daily_candidate_manifest(candidate_groups=_all_groups(candidate))


@pytest.mark.parametrize("groups", ({"all": build_scheduler_candidates()[:1]}, {**_all_groups(build_scheduler_candidates()[0]), "extra": (build_scheduler_candidates()[0],)}, {**_all_groups(build_scheduler_candidates()[0]), "alpha": ()}))
def test_manifest_requires_exactly_all_eight_nonempty_public_groups(groups):
    with pytest.raises(ValueError, match="eight|group|nonempty"):
        build_three_day_daily_candidate_manifest(candidate_groups=groups, expected_count=1)


def test_manifest_rejects_explicit_empty_group_map_instead_of_using_defaults():
    with pytest.raises(ValueError, match="eight|group"):
        build_three_day_daily_candidate_manifest(candidate_groups={}, expected_count=459)


def test_generic_daily_ledger_is_idempotent_and_rejects_conflicts(tmp_path: Path):
    ledger = AppendOnlyEvidenceLedger(tmp_path / "nested" / "evidence.jsonl", DAILY_EVIDENCE_KEY_FIELDS)
    assert ledger.append(_row()) is True
    assert ledger.append(_row()) is False
    with pytest.raises(ValueError, match="conflicting duplicate"):
        ledger.append(_row(payload="different"))
    assert ledger.load() == [_row()]
    assert (tmp_path / "nested" / "evidence.jsonl").read_bytes().endswith(b"\n")


def test_generic_daily_ledger_recovers_truncated_tail_and_rejects_interior_damage(tmp_path: Path):
    path = tmp_path / "evidence.jsonl"
    valid = json.dumps(_row(), sort_keys=True, separators=(",", ":")) + "\n"
    path.write_text(valid + '{"run_identity":"run-a"', encoding="utf-8")
    rows = AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS).load()
    assert rows == [_row()]
    assert rows.recovery_metadata["truncated_final_line"]["line_number"] == 2
    assert path.read_text(encoding="utf-8") == valid

    path.write_text(valid + "{bad}\n" + valid, encoding="utf-8")
    with pytest.raises(ValueError, match="interior|line 2"):
        AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS).load()


def test_generic_daily_ledger_quarantines_valid_json_without_terminal_newline(tmp_path: Path):
    path = tmp_path / "evidence.jsonl"
    raw = json.dumps(_row(), sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    rows = AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS).load()
    assert rows == []
    assert path.read_bytes() == b""
    assert Path(rows.recovery_metadata["truncated_final_line"]["quarantine_path"]).read_bytes() == raw


def test_quarantine_is_durable_before_source_truncate(monkeypatch, tmp_path: Path):
    import src.application.services.daily_strategy_evidence as module

    path = tmp_path / "evidence.jsonl"
    raw = b'{"partial":true}'
    path.write_bytes(raw)
    events = []
    quarantine_descriptors = set()
    real_open = module.os.open
    real_fsync = module.os.fsync

    def observed_open(path_value, flags, *args):
        descriptor = real_open(path_value, flags, *args)
        if ".truncated-" in str(path_value):
            quarantine_descriptors.add(descriptor)
        return descriptor

    def observed_fsync(descriptor):
        if descriptor in quarantine_descriptors:
            events.append("quarantine_fsync")
        return real_fsync(descriptor)

    real_truncate = module._truncate_source_to_offset

    def observed_truncate(*args, **kwargs):
        events.append("truncate")
        return real_truncate(*args, **kwargs)

    monkeypatch.setattr(module.os, "open", observed_open)
    monkeypatch.setattr(module.os, "fsync", observed_fsync)
    monkeypatch.setattr(module, "_truncate_source_to_offset", observed_truncate)
    AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS).load()
    assert events.index("quarantine_fsync") < events.index("truncate")


def test_quarantine_write_error_leaves_source_intact(monkeypatch, tmp_path: Path):
    import src.application.services.daily_strategy_evidence as module

    path = tmp_path / "evidence.jsonl"
    raw = b'{"partial":true}'
    path.write_bytes(raw)
    monkeypatch.setattr(module, "_durably_write_quarantine", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS).load()
    assert path.read_bytes() == raw


def test_conflicting_existing_quarantine_leaves_source_intact(tmp_path: Path):
    path = tmp_path / "evidence.jsonl"
    raw = b'{"partial":true}'
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    quarantine = path.with_name(f"{path.name}.truncated-{digest[:12]}.jsonl")
    quarantine.write_bytes(b"conflict")
    with pytest.raises(ValueError, match="conflicting.*quarantine"):
        AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS).load()
    assert path.read_bytes() == raw


def test_public_ledger_load_waits_for_exclusive_writer_lock(tmp_path: Path):
    path = tmp_path / "evidence.jsonl"
    ledger = AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS)
    ledger.append(_row())
    entered = threading.Event()
    release = threading.Event()

    def writer():
        with evidence_file_lock(path):
            entered.set()
            release.wait(1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        owner = pool.submit(writer)
        assert entered.wait(1)
        reader = pool.submit(ledger.load)
        time.sleep(0.03)
        assert not reader.done()
        release.set()
        owner.result()
        assert reader.result() == [_row()]


def test_generic_daily_ledger_recovers_dead_lock_but_times_out_on_live_owner(tmp_path: Path):
    path = tmp_path / "evidence.jsonl"
    lock_path = evidence_lock_path(path)
    lock_path.write_text(json.dumps({"pid": 2**30, "token": "dead", "created_at": 0}), encoding="utf-8")
    AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS).append(_row())
    assert not lock_path.exists()

    lock_path.write_text(json.dumps({"pid": os.getpid(), "token": "live", "created_at": time.time()}), encoding="utf-8")
    with pytest.raises(TimeoutError):
        with evidence_file_lock(path, timeout_seconds=0.02, stale_seconds=0):
            pass


def test_generic_daily_lock_does_not_remove_replaced_owner_token(tmp_path: Path):
    path = tmp_path / "evidence.jsonl"
    lock_path = evidence_lock_path(path)
    with evidence_file_lock(path):
        lock_path.write_text(json.dumps({"pid": os.getpid(), "token": "replacement", "created_at": time.time()}), encoding="utf-8")
    assert lock_path.exists()


def _utc(value: str):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _market(start: datetime, minutes: int):
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    candles = tuple(
        Candle(
            symbol=symbol, timeframe=timeframe,
            opened_at=start + timedelta(minutes=index),
            closed_at=start + timedelta(minutes=index + 1),
            open_price=Decimal("100"), high_price=Decimal("101"),
            low_price=Decimal("99"), close_price=Decimal("100"), volume=Decimal("1"),
        )
        for index in range(minutes)
    )
    return MarketSnapshot(candles)


def _identity(manifest, market, provider=None):
    coverage = getattr(provider, "feature_source_coverage", {}) if provider else {}
    unavailable = getattr(provider, "feature_unavailable_counts", {}) if provider else {}
    provenance = getattr(provider, "feature_provenance", {}) if provider else {}
    return DailyEvidenceRunIdentity(
        profile_id=PROFILE_ID, feature_schema_version=THREE_DAY_CHART_FEATURE_SCHEMA_VERSION,
        phase="Validation", phase_start_at=_utc("2025-07-10"),
        phase_end_at=_utc("2025-07-11"), model_artifact_hash="1" * 64,
        candidate_universe_hash=manifest.candidate_universe_hash,
        ordered_candidate_definition_hashes=manifest.ordered_definition_hashes,
        market_data_hash=market_snapshot_hash(market),
        feature_cache_hash=getattr(provider, "feature_cache_hash", None) if provider else None,
        feature_config_hash=feature_provider_config_hash(provider),
        feature_cache_schema_version=getattr(provider, "feature_cache_schema_version", "none") if provider else "none",
        feature_provenance_hash=candidate_definition_hash(provenance),
        feature_source_coverage_hash=candidate_definition_hash(coverage),
        feature_unavailable_counts_hash=candidate_definition_hash(unavailable),
        engine_version=BACKTEST_ENGINE_VERSION,
        cost_model={"venue": "binance_usd_m_futures", "fee_rate_per_side": str(FEE_RATE),
                    "slippage_rate_per_side": str(SLIPPAGE_RATE), "funding_fee": "excluded"},
        symbol="BTCUSDT", timeframe="1m",
        initial_equity=Decimal("1000"), code_version=DAILY_EVIDENCE_CODE_VERSION,
        evidence_schema_version=DAILY_EVIDENCE_SCHEMA_VERSION,
    )


def _zero_replay(candidate, manifest, start, provider=None):
    return {
        "engine": "scheduler_driven", "engine_version": BACKTEST_ENGINE_VERSION,
        "cost_model": {"venue": "binance_usd_m_futures", "fee_rate_per_side": str(FEE_RATE),
                       "slippage_rate_per_side": str(SLIPPAGE_RATE), "funding_fee": "excluded"},
        "start_at": start.isoformat(), "end_at": (start + timedelta(days=1)).isoformat(),
        "candidate_id": candidate.candidate_id,
        "candidate_definition_hash": manifest.entries[0].definition_hash,
        "initial_equity": "1000", "final_equity": "1000",
        "gross_pnl": "0", "net_pnl": "0", "fee_paid": "0", "return_ratio": "0",
        "max_drawdown_ratio": "0", "maximum_adverse_excursion_ratio": "0",
        "trade_count": 0, "trades": [], "position_open_at_end": False,
        "feature_cache_hash": getattr(provider, "feature_cache_hash", None) if provider else None,
        "feature_config_hash": feature_provider_config_hash(provider),
        "feature_cache_schema_version": getattr(provider, "feature_cache_schema_version", "none") if provider else "none",
        "feature_source_coverage": getattr(provider, "feature_source_coverage", {}) if provider else {},
        "feature_unavailable_counts": getattr(provider, "feature_unavailable_counts", {}) if provider else {},
        "feature_provenance": getattr(provider, "feature_provenance", {}) if provider else {},
        "future_feature_access_count": 0,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("profile_id", "other-profile"), ("feature_schema_version", "other-features"),
        ("phase_end_at", _utc("2025-07-12")), ("model_artifact_hash", "9" * 64),
        ("candidate_universe_hash", "8" * 64),
        ("ordered_candidate_definition_hashes", (("other", "7" * 64),)),
        ("market_data_hash", "6" * 64), ("feature_cache_hash", "5" * 64),
        ("feature_config_hash", "4" * 64), ("feature_cache_schema_version", "other-cache"),
        ("feature_provenance_hash", "3" * 64), ("feature_source_coverage_hash", "2" * 64),
        ("feature_unavailable_counts_hash", "1" * 64), ("engine_version", "other-engine"),
        ("cost_model", {"venue": "other"}), ("symbol", "ETHUSDT"),
        ("timeframe", "5m"), ("initial_equity", Decimal("2000")),
        ("code_version", "other-code"), ("evidence_schema_version", "other-evidence"),
    ),
)
def test_daily_run_identity_invalidates_every_bound_input(field, value):
    candidate = replace(build_scheduler_candidates()[0], candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(candidate_groups=_all_groups(candidate), expected_count=1)
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=1), 1441)
    identity = _identity(manifest, market)
    try:
        changed = replace(identity, **{field: value})
    except ValueError:
        return
    assert changed.digest != identity.digest


def test_daily_execution_uses_exact_warmup_isolated_replay_and_resumes(tmp_path: Path):
    candidate = replace(build_scheduler_candidates()[0], candle_limit=2)
    manifest = build_three_day_daily_candidate_manifest(
        candidate_groups=_all_groups(candidate), expected_count=1
    )
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=2), 1442)
    calls = []

    def replay(snapshot, **kwargs):
        calls.append(kwargs)
        return _zero_replay(candidate, manifest, start)

    ledger = AppendOnlyEvidenceLedger(tmp_path / "daily.jsonl", DAILY_EVIDENCE_KEY_FIELDS)
    first = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=market,
        market_feature_provider=None, run_identity=_identity(manifest, market), ledger=ledger,
        replay_callable=replay,
    )
    second = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=market,
        market_feature_provider=None, run_identity=_identity(manifest, market), ledger=ledger,
        replay_callable=replay,
    )

    assert first == second
    assert len(calls) == 1
    assert calls[0]["context_start_at"] == start - timedelta(minutes=2)
    assert calls[0]["start_at"] == start and calls[0]["end_at"] == start + timedelta(days=1)
    assert calls[0]["initial_equity"] == Decimal("1000")
    assert calls[0]["include_trade_details"] is True
    assert calls[0]["force_close_at_end"] is True
    assert first[0].trade_pnls == ()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("engine", "other", "engine"),
        ("engine_version", "other", "engine"),
        ("cost_model", {"venue": "other"}, "cost"),
        ("feature_cache_hash", "a" * 64, "cache"),
        ("feature_config_hash", "b" * 64, "config"),
        ("feature_cache_schema_version", "other", "schema"),
        ("feature_provenance", {"source": "other"}, "provenance"),
        ("feature_source_coverage", {"klines": 1}, "coverage"),
        ("feature_unavailable_counts", {"metrics": 1}, "unavailable"),
        ("start_at", _utc("2025-07-09").isoformat(), "interval"),
        ("end_at", _utc("2025-07-12").isoformat(), "interval"),
    ),
)
def test_daily_execution_rejects_canonical_replay_provenance_drift(tmp_path, field, value, message):
    candidate = replace(build_scheduler_candidates()[0], candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(candidate_groups=_all_groups(candidate), expected_count=1)
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=1), 1441)
    payload = _zero_replay(candidate, manifest, start)
    payload[field] = value
    with pytest.raises(ValueError, match=message):
        run_daily_strategy_evidence(
            manifest=manifest, phase="Validation", outcome_start_at=start,
            component_fingerprint="component-a", market=market,
            market_feature_provider=None, run_identity=_identity(manifest, market),
            ledger=AppendOnlyEvidenceLedger(tmp_path / f"{field}.jsonl", DAILY_EVIDENCE_KEY_FIELDS),
            replay_callable=lambda *_args, **_kwargs: payload,
        )


@pytest.mark.parametrize("missing", ("holding_bars", "maximum_adverse_excursion_ratio"))
def test_daily_execution_rejects_incomplete_trade_metrics(tmp_path, missing):
    candidate = replace(build_scheduler_candidates()[0], candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(candidate_groups=_all_groups(candidate), expected_count=1)
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=1), 1441)
    payload = _zero_replay(candidate, manifest, start)
    trade = {
        "entry_at": start.isoformat(), "exit_at": (start + timedelta(minutes=1)).isoformat(),
        "entry_price": "100", "exit_price": "100", "direction": "long", "quantity": "1",
        "margin": "50", "gross_pnl": "0", "net_pnl": "0", "fee_paid": "0",
        "exit_reason": "test", "holding_bars": 1,
        "owner_strategy_profile_id": candidate.candidate_id,
        "owner_candidate_definition_hash": manifest.entries[0].definition_hash,
        "owner_guard_hash": "a" * 64, "owner_leverage": "2", "owner_max_holding_bars": 1,
        "maximum_adverse_excursion_ratio": "0",
    }
    trade.pop(missing)
    payload.update(trade_count=1, trades=[trade])
    with pytest.raises(ValueError, match=missing.replace("_", " ")):
        run_daily_strategy_evidence(
            manifest=manifest, phase="Validation", outcome_start_at=start,
            component_fingerprint="component-a", market=market,
            market_feature_provider=None, run_identity=_identity(manifest, market),
            ledger=AppendOnlyEvidenceLedger(tmp_path / f"{missing}.jsonl", DAILY_EVIDENCE_KEY_FIELDS),
            replay_callable=lambda *_args, **_kwargs: payload,
        )


def test_daily_execution_derives_exact_trade_ledger_and_single_day_metrics(tmp_path):
    candidate = replace(build_scheduler_candidates()[0], candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(candidate_groups=_all_groups(candidate), expected_count=1)
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=1), 1441)

    def trade(*, entry_price, exit_price, gross, net, fee, holding, mae):
        return {
            "entry_at": start.isoformat(), "exit_at": (start + timedelta(minutes=holding)).isoformat(),
            "entry_price": entry_price, "exit_price": exit_price, "direction": "long", "quantity": "1",
            "margin": "50", "gross_pnl": gross, "net_pnl": net, "fee_paid": fee,
            "exit_reason": "test", "holding_bars": holding,
            "owner_strategy_profile_id": candidate.candidate_id,
            "owner_candidate_definition_hash": manifest.entries[0].definition_hash,
            "owner_guard_hash": "a" * 64, "owner_leverage": "2", "owner_max_holding_bars": 60,
            "maximum_adverse_excursion_ratio": mae,
        }

    payload = _zero_replay(candidate, manifest, start)
    payload.update(
        initial_equity="1000", final_equity="1005", gross_pnl="7", net_pnl="5",
        fee_paid="2", return_ratio="0.005", trade_count=2,
        maximum_adverse_excursion_ratio="0.04",
        trades=[
            trade(entry_price="100", exit_price="107", gross="7", net="6", fee="1", holding=10, mae="0.02"),
            trade(entry_price="200", exit_price="200", gross="0", net="-1", fee="1", holding=20, mae="0.04"),
        ],
    )
    row = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=market,
        market_feature_provider=None, run_identity=_identity(manifest, market),
        ledger=AppendOnlyEvidenceLedger(tmp_path / "metrics.jsonl", DAILY_EVIDENCE_KEY_FIELDS),
        replay_callable=lambda *_args, **_kwargs: payload,
    )[0]
    assert row.trade_pnls == (Decimal("6"), Decimal("-1"))
    assert row.profit_factor == Decimal("6") and row.profit_factor_status == "finite"
    with decimal_arithmetic_context():
        assert row.exposure_ratio == Decimal(30) / Decimal(1440)
    assert row.turnover_ratio == Decimal("0.607")
    assert row.maximum_adverse_excursion_ratio == Decimal("0.04")
    assert row.gross_return_ratio == Decimal("0.007")
    assert row.net_return_ratio == row.expected_shortfall_10_ratio == Decimal("0.005")
    assert row.median_daily_return_ratio == row.tenth_percentile_daily_return_ratio == Decimal("0.005")


def test_daily_execution_represents_profitable_day_without_losses_without_pf_sentinel(tmp_path):
    candidate = replace(build_scheduler_candidates()[0], candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(candidate_groups=_all_groups(candidate), expected_count=1)
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=1), 1441)
    payload = _zero_replay(candidate, manifest, start)
    payload.update(
        final_equity="1005", gross_pnl="6", net_pnl="5", fee_paid="1", return_ratio="0.005",
        trade_count=1, trades=[{
            "entry_at": start.isoformat(), "exit_at": (start + timedelta(minutes=1)).isoformat(),
            "entry_price": "100", "exit_price": "106", "direction": "long", "quantity": "1",
            "margin": "50", "gross_pnl": "6", "net_pnl": "5", "fee_paid": "1",
            "exit_reason": "test", "holding_bars": 1,
            "owner_strategy_profile_id": candidate.candidate_id,
            "owner_candidate_definition_hash": manifest.entries[0].definition_hash,
            "owner_guard_hash": "a" * 64, "owner_leverage": "2", "owner_max_holding_bars": 60,
            "maximum_adverse_excursion_ratio": "0",
        }],
    )
    row = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=market,
        market_feature_provider=None, run_identity=_identity(manifest, market),
        ledger=AppendOnlyEvidenceLedger(tmp_path / "no-loss.jsonl", DAILY_EVIDENCE_KEY_FIELDS),
        replay_callable=lambda *_args, **_kwargs: payload,
    )[0]
    assert row.profit_factor is None
    assert row.profit_factor_status == "positive_without_losses"


def test_replay_exception_does_not_create_or_append_evidence_file(tmp_path):
    candidate = replace(build_scheduler_candidates()[0], candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(candidate_groups=_all_groups(candidate), expected_count=1)
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=1), 1441)
    path = tmp_path / "evidence.jsonl"
    with pytest.raises(RuntimeError, match="engine failed"):
        run_daily_strategy_evidence(
            manifest=manifest, phase="Validation", outcome_start_at=start,
            component_fingerprint="component-a", market=market,
            market_feature_provider=None, run_identity=_identity(manifest, market),
            ledger=AppendOnlyEvidenceLedger(path, DAILY_EVIDENCE_KEY_FIELDS),
            replay_callable=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("engine failed")),
        )
    assert not path.exists()


def test_multi_candidate_execution_matches_fresh_isolated_candidate_runs(tmp_path):
    candidates = tuple(replace(item, candle_limit=1) for item in build_scheduler_candidates()[:2])
    groups = {group: candidates for group in _all_groups(candidates[0])}
    manifest = build_three_day_daily_candidate_manifest(candidate_groups=groups, expected_count=2)
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=1), 1441)
    calls = []

    def replay(_market_snapshot, **kwargs):
        candidate = kwargs["candidate"]
        calls.append((candidate.candidate_id, kwargs["initial_equity"], tuple(sorted(kwargs))))
        entry = next(item for item in manifest.entries if item.candidate_id == candidate.candidate_id)
        payload = _zero_replay(candidate, manifest, start)
        payload["candidate_definition_hash"] = entry.definition_hash
        return payload

    combined = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=market,
        market_feature_provider=None, run_identity=_identity(manifest, market),
        ledger=AppendOnlyEvidenceLedger(tmp_path / "combined.jsonl", DAILY_EVIDENCE_KEY_FIELDS),
        replay_callable=replay,
    )
    isolated = tuple(
        run_daily_strategy_evidence(
            manifest=manifest, phase="Validation", outcome_start_at=start,
            component_fingerprint="component-a", market=market,
            market_feature_provider=None, run_identity=_identity(manifest, market),
            ledger=AppendOnlyEvidenceLedger(tmp_path / f"isolated-{candidate.candidate_id}.jsonl", DAILY_EVIDENCE_KEY_FIELDS),
            candidate_ids=(candidate.candidate_id,), replay_callable=replay,
        )[0]
        for candidate in candidates
    )
    assert combined == isolated
    assert [item.candidate_id for item in combined] == list(manifest.candidate_ids)
    assert all(initial == Decimal("1000") for _, initial, _ in calls)
    assert len({keys for _, _, keys in calls}) == 1


def test_daily_execution_records_expected_point_in_time_feature_unavailability(tmp_path: Path):
    candidate = replace(next(
        item for item in microstructure_alpha_candidates()
        if item.candidate_id == "micro-flow-breakout-balanced-tight"
    ), candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(
        candidate_groups=_all_groups(candidate), expected_count=1
    )
    assert manifest.entries[0].required_feature_alternatives != ((),)
    start = _utc("2025-07-10")
    ledger = AppendOnlyEvidenceLedger(tmp_path / "daily.jsonl", DAILY_EVIDENCE_KEY_FIELDS)
    market = _market(start - timedelta(minutes=1), 1441)
    identity = _identity(manifest, market)
    called = False

    def replay(*args, **kwargs):
        nonlocal called
        called = True

    rows = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=market,
        market_feature_provider=None, run_identity=identity, ledger=ledger,
        replay_callable=replay,
    )
    assert called is False
    assert rows[0].availability_status == "unavailable"
    assert rows[0].availability_reason == "point_in_time_feature_provider_unavailable"
    assert rows[0].trade_pnls is None
    assert rows[0].net_pnl == 0

    with pytest.raises(ValueError, match="run identity"):
        run_daily_strategy_evidence(
            manifest=manifest, phase="Validation", outcome_start_at=start,
            component_fingerprint="component-a", market=market,
            market_feature_provider=None,
            run_identity=replace(identity, model_artifact_hash="9" * 64), ledger=ledger,
            replay_callable=replay,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("engine_version", "other", "engine"),
        ("cost_model", {"venue": "other"}, "cost"),
        ("feature_cache_hash", "a" * 64, "cache"),
        ("feature_config_hash", "b" * 64, "config"),
        ("feature_cache_schema_version", "other", "schema"),
        ("feature_provenance_hash", "c" * 64, "provenance"),
        ("feature_source_coverage_hash", "d" * 64, "coverage"),
        ("feature_unavailable_counts_hash", "e" * 64, "unavailable"),
    ),
)
def test_unavailable_evidence_rejects_static_identity_provenance_drift(tmp_path, field, value, message):
    candidate = replace(next(
        item for item in microstructure_alpha_candidates()
        if item.candidate_id == "micro-flow-breakout-balanced-tight"
    ), candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(candidate_groups=_all_groups(candidate), expected_count=1)
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=1), 1441)
    identity = replace(_identity(manifest, market), **{field: value})
    replayed = False

    def replay(*_args, **_kwargs):
        nonlocal replayed
        replayed = True

    with pytest.raises(ValueError, match=message):
        run_daily_strategy_evidence(
            manifest=manifest, phase="Validation", outcome_start_at=start,
            component_fingerprint="component-a", market=market,
            market_feature_provider=None, run_identity=identity,
            ledger=AppendOnlyEvidenceLedger(tmp_path / f"{field}.jsonl", DAILY_EVIDENCE_KEY_FIELDS),
            replay_callable=replay,
        )
    assert replayed is False


@pytest.mark.parametrize("future_publication", (False, True))
def test_daily_execution_checks_provider_at_each_point_in_time_boundary(tmp_path, future_publication):
    candidate = replace(next(
        item for item in microstructure_alpha_candidates()
        if item.candidate_id == "micro-flow-breakout-balanced-tight"
    ), candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(candidate_groups=_all_groups(candidate), expected_count=1)
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=1), 1441)

    class Provider:
        feature_cache_hash = "a" * 64
        feature_cache_schema_version = FEATURE_CACHE_SCHEMA_VERSION
        feature_source_coverage = {"aggTrades": 1441, "klines": 1441}
        feature_unavailable_counts = {}
        feature_provenance = {"source": {"dataset": "fixture"}}
        required_warmup_candles = 1

        def __init__(self):
            self.calls = []

        def load_features(self, symbol, timeframe, as_of):
            self.calls.append(as_of)
            values = {
                name: SimpleNamespace(
                    source=sources[0],
                    available_at=as_of + timedelta(minutes=1) if future_publication else as_of,
                )
                for name, sources in manifest.entries[0].required_feature_alternatives[0]
            }
            return SimpleNamespace(get=values.get)

    provider = Provider()
    replay_calls = []
    rows = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=market,
        market_feature_provider=provider, run_identity=_identity(manifest, market, provider),
        ledger=AppendOnlyEvidenceLedger(tmp_path / "provider.jsonl", DAILY_EVIDENCE_KEY_FIELDS),
        replay_callable=lambda *_args, **_kwargs: (
            replay_calls.append(1) or _zero_replay(candidate, manifest, start, provider)
        ),
    )
    assert provider.calls[0] == start
    if future_publication:
        assert rows[0].availability_status == "unavailable"
        assert replay_calls == []
    else:
        assert provider.calls[-1] == start + timedelta(days=1)
        assert len(provider.calls) == 1441
        assert rows[0].availability_status == "available"
        assert replay_calls == [1]
