from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import time
from pathlib import Path

import pytest

from scripts.deferred_strategy_registry import load_deferred_strategy_registry
from scripts.scheduler_driven_scalping_backtest import (
    build_scheduler_candidates,
    microstructure_alpha_candidates,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe
from src.application.services.daily_strategy_evidence import (
    DAILY_EVIDENCE_KEY_FIELDS,
    AppendOnlyEvidenceLedger,
    DailyEvidenceRunIdentity,
    build_three_day_daily_candidate_manifest,
    evidence_file_lock,
    evidence_lock_path,
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
        candidate_groups={"all": (candidate, candidate)}, expected_count=1
    )
    assert collapsed.candidate_ids == (candidate.candidate_id,)
    assert collapsed.entries[0].deferred_groups == (("all", "failed"),)

    conflicting = replace(candidate, equity_ratio=candidate.equity_ratio * 2)
    with pytest.raises(ValueError, match="conflicting.*candidate_id"):
        build_three_day_daily_candidate_manifest(
            candidate_groups={"all": (candidate, conflicting)}, expected_count=1
        )


def test_manifest_count_is_a_repository_snapshot_drift_alarm():
    candidate = build_scheduler_candidates()[0]
    with pytest.raises(ValueError, match="expected 459.*found 1"):
        build_three_day_daily_candidate_manifest(candidate_groups={"all": (candidate,)})


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


def _identity(manifest):
    return DailyEvidenceRunIdentity(
        profile_id="three-day-daily", feature_schema_version="features-v1",
        phase="Validation", phase_start_at=_utc("2025-07-10"),
        phase_end_at=_utc("2025-07-11"), model_artifact_hash="1" * 64,
        candidate_universe_hash=manifest.candidate_universe_hash,
        ordered_candidate_definition_hashes=manifest.ordered_definition_hashes,
        market_data_hash="2" * 64, feature_cache_hash="3" * 64,
        feature_config_hash="4" * 64, feature_cache_schema_version="cache-v1",
        feature_provenance_hash="5" * 64, engine_version="engine-v1",
        cost_model={"fee": "0.0004"}, symbol="BTCUSDT", timeframe="1m",
        initial_equity=Decimal("1000"), code_version="code-v1",
        evidence_schema_version="daily-evidence-v1",
    )


def test_daily_execution_uses_exact_warmup_isolated_replay_and_resumes(tmp_path: Path):
    candidate = replace(build_scheduler_candidates()[0], candle_limit=2)
    manifest = build_three_day_daily_candidate_manifest(
        candidate_groups={"all": (candidate,)}, expected_count=1
    )
    start = _utc("2025-07-10")
    market = _market(start - timedelta(minutes=2), 1442)
    calls = []

    def replay(snapshot, **kwargs):
        calls.append(kwargs)
        return {
            "candidate_id": candidate.candidate_id,
            "candidate_definition_hash": manifest.entries[0].definition_hash,
            "initial_equity": "1000", "final_equity": "1000",
            "gross_pnl": "0", "net_pnl": "0", "fee_paid": "0",
            "return_ratio": "0", "max_drawdown_ratio": "0",
            "maximum_adverse_excursion_ratio": "0",
            "trade_count": 0, "trades": [], "position_open_at_end": False,
        }

    ledger = AppendOnlyEvidenceLedger(tmp_path / "daily.jsonl", DAILY_EVIDENCE_KEY_FIELDS)
    first = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=market,
        market_feature_provider=None, run_identity=_identity(manifest), ledger=ledger,
        replay_callable=replay,
    )
    second = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=market,
        market_feature_provider=None, run_identity=_identity(manifest), ledger=ledger,
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


def test_daily_execution_records_expected_point_in_time_feature_unavailability(tmp_path: Path):
    candidate = replace(next(
        item for item in microstructure_alpha_candidates()
        if item.candidate_id == "micro-flow-breakout-balanced-tight"
    ), candle_limit=1)
    manifest = build_three_day_daily_candidate_manifest(
        candidate_groups={"microstructure": (candidate,)}, expected_count=1
    )
    assert manifest.entries[0].required_feature_alternatives != ((),)
    start = _utc("2025-07-10")
    ledger = AppendOnlyEvidenceLedger(tmp_path / "daily.jsonl", DAILY_EVIDENCE_KEY_FIELDS)
    identity = _identity(manifest)
    called = False

    def replay(*args, **kwargs):
        nonlocal called
        called = True

    rows = run_daily_strategy_evidence(
        manifest=manifest, phase="Validation", outcome_start_at=start,
        component_fingerprint="component-a", market=_market(start - timedelta(minutes=1), 1441),
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
            component_fingerprint="component-a", market=_market(start - timedelta(minutes=1), 1441),
            market_feature_provider=None,
            run_identity=replace(identity, model_artifact_hash="9" * 64), ledger=ledger,
            replay_callable=replay,
        )
