import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.incremental_walk_forward_runner import (
    IncrementalRunSpec,
    aggregate_incremental_rows,
    build_run_identity,
    completed_keys,
    load_jsonl_rows,
    run_incremental_walk_forward,
    market_data_hash,
    write_jsonl_row,
)
from scripts.scheduler_driven_scalping_backtest import (
    BACKTEST_ENGINE_VERSION,
    FEE_RATE,
    SLIPPAGE_RATE,
    candidate_definition_hash,
    candidate_payload,
    microstructure_alpha_candidates,
)
from src.domain.market import Candle, MarketSnapshot, Symbol, Timeframe


def test_jsonl_resume_keys_round_trip(tmp_path: Path) -> None:
    output_path = tmp_path / "rows.jsonl"
    row = {
        "run_identity": "run-a",
        "symbol": "BTCUSDT",
        "candidate_id": "candidate-a",
        "fold": 1,
        "test_start_at": "2021-01-01T00:00:00+00:00",
        "test_end_at": "2021-02-01T00:00:00+00:00",
        "return_ratio": "0.01",
    }

    write_jsonl_row(output_path, row)

    rows = load_jsonl_rows(output_path)
    assert rows == [row]
    assert completed_keys(rows) == {("BTCUSDT", "candidate-a", 1)}
    assert rows.recovery_metadata == {}


def test_jsonl_loader_recovers_only_truncated_final_line(tmp_path: Path) -> None:
    output_path = tmp_path / "rows.jsonl"
    row = _resume_row()
    valid_line = json.dumps(row, sort_keys=True) + "\n"
    output_path.write_text(valid_line + '{"run_identity":"run-a"', encoding="utf-8")

    rows = load_jsonl_rows(output_path)

    assert rows == [row]
    recovery = rows.recovery_metadata["truncated_final_line"]
    assert recovery["line_number"] == 2
    assert Path(recovery["quarantine_path"]).read_text(encoding="utf-8") == '{"run_identity":"run-a"'
    assert output_path.read_text(encoding="utf-8") == valid_line


def test_jsonl_loader_rejects_malformed_interior_line(tmp_path: Path) -> None:
    output_path = tmp_path / "rows.jsonl"
    valid_line = json.dumps(_resume_row(), sort_keys=True)
    output_path.write_text(f"{valid_line}\n{{bad-json}}\n{valid_line}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="interior|line 2"):
        load_jsonl_rows(output_path)


def test_jsonl_loader_deduplicates_identical_rows_and_rejects_conflicts(tmp_path: Path) -> None:
    output_path = tmp_path / "rows.jsonl"
    row = _resume_row()
    line = json.dumps(row, sort_keys=True)
    output_path.write_text(f"{line}\n{line}\n", encoding="utf-8")

    assert load_jsonl_rows(output_path) == [row]

    conflicting = {**row, "return_ratio": "0.99"}
    output_path.write_text(f"{line}\n{json.dumps(conflicting, sort_keys=True)}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting duplicate"):
        load_jsonl_rows(output_path)


def test_jsonl_loader_rejects_legacy_rows_without_run_identity(tmp_path: Path) -> None:
    output_path = tmp_path / "legacy.jsonl"
    legacy = _resume_row()
    legacy.pop("run_identity")
    output_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="legacy.*new.*path"):
        load_jsonl_rows(output_path)


def test_concurrent_jsonl_writers_append_one_complete_row(tmp_path: Path) -> None:
    output_path = tmp_path / "rows.jsonl"
    row = _resume_row()

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: write_jsonl_row(output_path, row), range(24)))

    assert load_jsonl_rows(output_path) == [row]
    raw = output_path.read_bytes()
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == 1


def test_rows_file_lock_records_owner_and_cleans_only_own_lock(tmp_path: Path) -> None:
    import scripts.incremental_walk_forward_runner as module

    rows_path = tmp_path / "rows.jsonl"
    lock_path = module._rows_file_lock_path(rows_path)

    with module._rows_file_lock(rows_path):
        metadata = json.loads(lock_path.read_text(encoding="utf-8"))
        assert metadata["pid"] == os.getpid()
        assert isinstance(metadata["token"], str) and metadata["token"]
        assert isinstance(metadata["created_at"], float)

    assert not lock_path.exists()


def test_rows_file_lock_recovers_crashed_owner(tmp_path: Path) -> None:
    import scripts.incremental_walk_forward_runner as module

    rows_path = tmp_path / "rows.jsonl"
    lock_path = module._rows_file_lock_path(rows_path)
    lock_path.write_text(
        json.dumps({"pid": 2_147_483_647, "token": "crashed", "created_at": time.time()}),
        encoding="utf-8",
    )

    assert write_jsonl_row(rows_path, _resume_row()) is True
    assert load_jsonl_rows(rows_path) == [_resume_row()]
    assert not lock_path.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows process-probe regression")
def test_windows_process_probe_never_terminates_live_process() -> None:
    import scripts.incremental_walk_forward_runner as module

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        for _ in range(5):
            assert module._process_is_alive(process.pid) is True
            assert process.poll() is None
        process.terminate()
        process.wait(timeout=5)
        assert module._process_is_alive(process.pid) is False
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_rows_file_lock_recovers_only_old_malformed_metadata(tmp_path: Path) -> None:
    import scripts.incremental_walk_forward_runner as module

    rows_path = tmp_path / "rows.jsonl"
    lock_path = module._rows_file_lock_path(rows_path)
    lock_path.write_text("malformed", encoding="utf-8")

    with pytest.raises(TimeoutError):
        with module._rows_file_lock(rows_path, timeout_seconds=0.03, stale_seconds=60):
            pass
    assert lock_path.read_text(encoding="utf-8") == "malformed"

    old = time.time() - 120
    os.utime(lock_path, (old, old))
    with module._rows_file_lock(rows_path, timeout_seconds=0.2, stale_seconds=60):
        assert json.loads(lock_path.read_text(encoding="utf-8"))["pid"] == os.getpid()
    assert not lock_path.exists()


def test_lock_recovery_treats_first_read_permission_error_as_active(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import scripts.incremental_walk_forward_runner as module

    rows_path = tmp_path / "rows.jsonl"
    lock_path = module._rows_file_lock_path(rows_path)
    metadata = {"pid": os.getpid(), "token": "active-owner", "created_at": time.time()}
    lock_path.write_text(json.dumps(metadata), encoding="utf-8")
    original_read_bytes = Path.read_bytes
    attempts = 0

    def denied_once(path):
        nonlocal attempts
        if path == lock_path:
            attempts += 1
            if attempts == 1:
                raise PermissionError("simulated Windows sharing violation")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", denied_once)

    assert module._recover_rows_file_lock_if_stale(lock_path, stale_seconds=0) is False
    assert lock_path.exists()
    assert json.loads(lock_path.read_text(encoding="utf-8")) == metadata
    lock_path.unlink()


def test_rows_file_lock_does_not_clean_replaced_token(tmp_path: Path) -> None:
    import scripts.incremental_walk_forward_runner as module

    rows_path = tmp_path / "rows.jsonl"
    lock_path = module._rows_file_lock_path(rows_path)
    replacement = {"pid": os.getpid(), "token": "replacement", "created_at": time.time()}

    with module._rows_file_lock(rows_path):
        lock_path.write_text(json.dumps(replacement), encoding="utf-8")

    assert json.loads(lock_path.read_text(encoding="utf-8")) == replacement
    lock_path.unlink()


def test_rows_file_lock_cleanup_never_suppresses_critical_section_error(tmp_path: Path) -> None:
    import scripts.incremental_walk_forward_runner as module

    rows_path = tmp_path / "rows.jsonl"

    with pytest.raises(RuntimeError, match="append failed"):
        with module._rows_file_lock(rows_path):
            module._rows_file_lock_path(rows_path).unlink()
            raise RuntimeError("append failed")
    assert not module._rows_file_lock_path(rows_path).exists()


def test_two_run_identities_serialize_on_one_rows_file_lock(monkeypatch, tmp_path: Path) -> None:
    import scripts.incremental_walk_forward_runner as module

    rows_path = tmp_path / "rows.jsonl"
    original_loader = module.load_jsonl_rows
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def observed_loader(path):
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        try:
            return original_loader(path)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(module, "load_jsonl_rows", observed_loader)
    rows = (_resume_row(run_identity="run-a"), _resume_row(run_identity="run-b"))
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda row: write_jsonl_row(rows_path, row), rows))

    assert maximum_active == 1
    assert len(original_loader(rows_path)) == 2


def test_concurrent_writers_stress_mixed_identities(tmp_path: Path) -> None:
    for iteration in range(12):
        rows_path = tmp_path / f"rows-{iteration}.jsonl"
        rows = tuple(
            _resume_row(run_identity=f"run-{index % 2}")
            for index in range(24)
        )
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda row: write_jsonl_row(rows_path, row), rows))

        loaded = load_jsonl_rows(rows_path)
        assert {row["run_identity"] for row in loaded} == {"run-0", "run-1"}
        assert len(loaded) == 2
        assert not (tmp_path / f"rows-{iteration}.jsonl.lock").exists()


def _resume_row(*, run_identity: str = "run-a") -> dict[str, object]:
    return {
        "run_identity": run_identity,
        "symbol": "BTCUSDT",
        "candidate_id": "candidate-a",
        "fold": 1,
        "test_start_at": "2021-01-01T00:00:00+00:00",
        "test_end_at": "2021-02-01T00:00:00+00:00",
        "return_ratio": "0.01",
    }


def test_aggregate_incremental_rows_builds_walk_forward_payload() -> None:
    spec = IncrementalRunSpec(
        symbol="BTCUSDT",
        start_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2021, 3, 1, tzinfo=timezone.utc),
        data_start_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        data_end_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        candidate_group="multi",
        candidate_ids=("candidate-a", "candidate-b"),
    )
    rows = [
        {
            "symbol": "BTCUSDT",
            "candidate_id": "candidate-a",
            "fold": 1,
            "test_start_at": "2021-01-01T00:00:00+00:00",
            "test_end_at": "2021-02-01T00:00:00+00:00",
            "return_ratio": "0.10",
            "daily_return_ratio": "0.003",
            "trades_per_day": "1",
            "net_win_rate": "0.6",
            "average_net_trade_roe": "0.01",
            "average_net_trade_expectancy_ratio": "0.010",
            "max_drawdown_ratio": "0.02",
            "trade_count": 10,
        },
        {
            "symbol": "BTCUSDT",
            "candidate_id": "candidate-a",
            "fold": 2,
            "test_start_at": "2021-02-01T00:00:00+00:00",
            "test_end_at": "2021-03-01T00:00:00+00:00",
            "return_ratio": "-0.02",
            "daily_return_ratio": "-0.001",
            "trades_per_day": "2",
            "net_win_rate": "0.4",
            "average_net_trade_roe": "-0.01",
            "average_net_trade_expectancy_ratio": "-0.001",
            "max_drawdown_ratio": "0.05",
            "trade_count": 20,
        },
        {
            "symbol": "BTCUSDT",
            "candidate_id": "candidate-b",
            "fold": 2,
            "test_start_at": "2021-02-01T00:00:00+00:00",
            "test_end_at": "2021-03-01T00:00:00+00:00",
            "return_ratio": "0.03",
            "daily_return_ratio": "0.001",
            "trades_per_day": "3",
            "net_win_rate": "0.5",
            "average_net_trade_roe": "0.02",
            "average_net_trade_expectancy_ratio": "0.001",
            "max_drawdown_ratio": "0.01",
            "trade_count": 30,
        },
    ]

    payload = aggregate_incremental_rows(spec, rows)

    assert payload["mode"] == "walk_forward_incremental"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["data_start_at"] == "2021-01-01T00:00:00+00:00"
    assert payload["data_end_at"] == "2026-07-01T00:00:00+00:00"
    assert payload["fold_count"] == 2
    assert [fold["test_start_at"] for fold in payload["folds"]] == [
        "2021-01-01T00:00:00+00:00",
        "2021-02-01T00:00:00+00:00",
    ]
    assert payload["candidate_count"] == 2
    assert payload["candidate_series"]["candidate-a"] == [
        {"month": "2021-01", "return_ratio": "0.10"},
        {"month": "2021-02", "return_ratio": "-0.02"},
    ]
    candidate_a = next(row for row in payload["results"] if row["candidate_id"] == "candidate-a")
    assert candidate_a["average_return_ratio"] == str((Decimal("0.10") + Decimal("-0.02")) / Decimal("2"))
    assert candidate_a["positive_fold_count"] == 1


def test_incremental_runner_can_select_alpha_candidate_group() -> None:
    from scripts.incremental_walk_forward_runner import _select_candidates

    candidates = _select_candidates(
        "alpha",
        ("alpha-sweep-tp0045-sl0040-e0060-l5-alpha-open",),
        include_deferred=True,
    )

    assert [candidate.candidate_id for candidate in candidates] == [
        "alpha-sweep-tp0045-sl0040-e0060-l5-alpha-open"
    ]


def test_incremental_runner_rejects_deferred_candidate_group_without_opt_in() -> None:
    from scripts.incremental_walk_forward_runner import _select_candidates

    with pytest.raises(ValueError, match="deferred-strategy-registry.json"):
        _select_candidates("alpha", ())


@pytest.mark.parametrize(
    "candidate_group",
    ("exact", "multi", "alpha", "microstructure", "counter", "metrics", "discovered"),
)
def test_incremental_runner_blocks_every_registered_candidate_group(
    candidate_group: str,
) -> None:
    from scripts.incremental_walk_forward_runner import _select_candidates

    with pytest.raises(ValueError, match=f"candidate group '{candidate_group}' is deferred"):
        _select_candidates(candidate_group, ())


def test_incremental_run_rejects_deferred_group_before_loading_market(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import scripts.incremental_walk_forward_runner as module

    monkeypatch.setattr(
        module,
        "load_period_market",
        lambda period: pytest.fail("market data must not load for a deferred group"),
    )
    spec = IncrementalRunSpec(
        symbol="BTCUSDT",
        start_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        data_start_at=datetime(2025, 7, 1, tzinfo=timezone.utc),
        data_end_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        candidate_group="alpha",
        candidate_ids=(),
    )

    with pytest.raises(ValueError, match="candidate group 'alpha' is deferred"):
        run_incremental_walk_forward(
            spec=spec,
            rows_path=tmp_path / "rows.jsonl",
            payload_path=tmp_path / "payload.json",
            summary_path=tmp_path / "summary.md",
        )


def test_incremental_runner_can_select_microstructure_candidate_group() -> None:
    from scripts.incremental_walk_forward_runner import _select_candidates

    candidates = _select_candidates(
        "microstructure",
        ("micro-mtf-balanced-tight",),
        include_deferred=True,
    )

    assert [candidate.candidate_id for candidate in candidates] == ["micro-mtf-balanced-tight"]


def test_incremental_runner_can_select_counter_candidate_group() -> None:
    from scripts.incremental_walk_forward_runner import _select_candidates

    candidates = _select_candidates(
        "counter",
        ("counter-mtf-strict-tight",),
        include_deferred=True,
    )

    assert [candidate.candidate_id for candidate in candidates] == [
        "counter-mtf-strict-tight"
    ]


def test_incremental_runner_can_select_metrics_candidate_group() -> None:
    from scripts.incremental_walk_forward_runner import _select_candidates

    candidates = _select_candidates(
        "metrics",
        ("metrics-oi-impulse-strict-tight",),
        include_deferred=True,
    )

    assert [candidate.candidate_id for candidate in candidates] == [
        "metrics-oi-impulse-strict-tight"
    ]


def test_incremental_runner_can_select_discovered_candidate_group() -> None:
    from scripts.incremental_walk_forward_runner import _select_candidates

    candidates = _select_candidates(
        "discovered",
        ("discovered-global-up-reversal-hold60",),
        include_deferred=True,
    )

    assert [candidate.candidate_id for candidate in candidates] == [
        "discovered-global-up-reversal-hold60"
    ]


def test_resume_and_aggregate_isolate_rows_by_current_run_identity() -> None:
    spec = IncrementalRunSpec(
        symbol="BTCUSDT",
        start_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2021, 2, 1, tzinfo=timezone.utc),
        data_start_at=datetime(2020, 7, 1, tzinfo=timezone.utc),
        data_end_at=datetime(2021, 2, 1, tzinfo=timezone.utc),
        candidate_group="microstructure",
        candidate_ids=("candidate-a",),
        feature_cache_hash="new-cache",
        candidate_universe_hash="new-candidates",
        run_identity="current-run",
    )
    metric_fields = {
        "daily_return_ratio": "0.001",
        "trades_per_day": "1",
        "net_win_rate": "0.5",
        "average_net_trade_roe": "0.01",
        "average_net_trade_expectancy_ratio": "0.001",
        "max_drawdown_ratio": "0.01",
        "trade_count": 1,
    }
    rows = [
        {
            "symbol": "BTCUSDT", "candidate_id": "candidate-a", "fold": 1,
            "test_start_at": "2021-01-01T00:00:00+00:00", "test_end_at": "2021-02-01T00:00:00+00:00",
            "return_ratio": "9", "run_identity": "old-run", **metric_fields,
        },
        {
            "symbol": "BTCUSDT", "candidate_id": "candidate-a", "fold": 1,
            "test_start_at": "2021-01-01T00:00:00+00:00", "test_end_at": "2021-02-01T00:00:00+00:00",
            "return_ratio": "0.1", "run_identity": "current-run", **metric_fields,
        },
    ]

    assert completed_keys(rows, run_identity="current-run") == {("BTCUSDT", "candidate-a", 1)}
    payload = aggregate_incremental_rows(spec, rows)
    assert payload["results"][0]["average_return_ratio"] == "0.1"
    assert payload["run_identity"] == "current-run"
    assert payload["feature_cache_hash"] == "new-cache"
    assert payload["candidate_universe_hash"] == "new-candidates"


def test_run_identity_changes_with_cache_and_candidate_definitions() -> None:
    spec = IncrementalRunSpec(
        symbol="BTCUSDT",
        start_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2021, 2, 1, tzinfo=timezone.utc),
        data_start_at=datetime(2020, 7, 1, tzinfo=timezone.utc),
        data_end_at=datetime(2021, 2, 1, tzinfo=timezone.utc),
        candidate_group="microstructure",
        candidate_ids=(),
    )

    folds = ((spec.data_start_at, spec.start_at, spec.start_at, spec.end_at),)
    arguments = {
        "feature_cache_hash": "cache-a",
        "candidate_universe_hash": "candidates-a",
        "market_data_hash": "market-a",
        "folds": folds,
    }
    base = build_run_identity(spec, **arguments)
    assert base != build_run_identity(spec, **{**arguments, "feature_cache_hash": "cache-b"})
    assert base != build_run_identity(spec, **{**arguments, "candidate_universe_hash": "candidates-b"})
    assert base != build_run_identity(spec, **{**arguments, "market_data_hash": "market-b"})
    assert base != build_run_identity(
        spec,
        **{**arguments, "folds": ((spec.data_start_at, spec.start_at, spec.start_at, spec.end_at + timedelta(days=1)),)},
    )
    assert base != build_run_identity(spec, **arguments, engine_version="changed-engine")
    assert base != build_run_identity(spec, **arguments, fee_rate=FEE_RATE + Decimal("0.0001"))
    assert base != build_run_identity(spec, **arguments, slippage_rate=SLIPPAGE_RATE + Decimal("0.0001"))


def test_market_data_hash_is_deterministic_and_changes_with_candle_data() -> None:
    market = _market_for_hash()
    changed = _market_for_hash(last_close=Decimal("101"))

    assert market_data_hash(market) == market_data_hash(market)
    assert market_data_hash(market) != market_data_hash(changed)


def test_candidate_selection_is_canonical_and_rejects_unknown_ids() -> None:
    from scripts.incremental_walk_forward_runner import _select_candidates

    requested = ("micro-mtf-strict-wide", "micro-mtf-balanced-tight")
    forward = _select_candidates("microstructure", requested, include_deferred=True)
    reverse = _select_candidates(
        "microstructure",
        tuple(reversed(requested)),
        include_deferred=True,
    )

    assert [candidate.candidate_id for candidate in forward] == sorted(requested)
    assert [candidate.candidate_id for candidate in forward] == [candidate.candidate_id for candidate in reverse]
    assert candidate_definition_hash([candidate_payload(candidate) for candidate in forward]) == candidate_definition_hash(
        [candidate_payload(candidate) for candidate in reverse]
    )
    with pytest.raises(ValueError, match="unknown candidate_id"):
        _select_candidates("microstructure", ("does-not-exist",), include_deferred=True)


def test_candidate_selection_rejects_duplicate_definitions(monkeypatch) -> None:
    import scripts.incremental_walk_forward_runner as module

    candidate = microstructure_alpha_candidates()[0]
    monkeypatch.setattr(module, "microstructure_alpha_candidates", lambda: (candidate, candidate))

    with pytest.raises(ValueError, match="duplicate candidate_id"):
        module._select_candidates("microstructure", (), include_deferred=True)


def test_aggregate_retains_identical_feature_provenance() -> None:
    spec = IncrementalRunSpec(
        symbol="BTCUSDT",
        start_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2021, 3, 1, tzinfo=timezone.utc),
        data_start_at=datetime(2020, 7, 1, tzinfo=timezone.utc),
        data_end_at=datetime(2021, 3, 1, tzinfo=timezone.utc),
        candidate_group="microstructure",
        candidate_ids=("candidate-a",),
        run_identity="current-run",
    )
    provenance = {"archive.zip": {"kind": "archive", "source": "aggTrades"}}
    rows = [
        _aggregate_row(fold=1, month="2021-01", provenance=provenance),
        _aggregate_row(fold=2, month="2021-02", provenance=provenance),
    ]

    payload = aggregate_incremental_rows(spec, rows)

    assert payload["feature_provenance"] == provenance


def test_aggregate_preserves_partial_run_starting_at_fold_two() -> None:
    spec = _aggregate_spec(candidate_ids=("candidate-a",))

    payload = aggregate_incremental_rows(
        spec,
        [_aggregate_row(fold=2, month="2021-02", provenance={})],
    )

    assert payload["fold_count"] == 1
    assert payload["folds"][0]["fold"] == 2
    assert payload["folds"][0]["test_start_at"] == "2021-02-01T00:00:00+00:00"


@pytest.mark.parametrize(
    "case,error",
    [
        ("same_fold_different_boundary", "fold.*boundar"),
        ("same_boundary_different_fold", "boundar.*fold"),
        ("internal_gap", "gap"),
    ],
)
def test_aggregate_rejects_fold_boundary_conflicts_and_internal_gaps(case: str, error: str) -> None:
    if case == "same_fold_different_boundary":
        rows = [
            _aggregate_row(fold=2, month="2021-01", provenance={}, candidate_id="candidate-a"),
            _aggregate_row(fold=2, month="2021-02", provenance={}, candidate_id="candidate-b"),
        ]
    elif case == "same_boundary_different_fold":
        rows = [
            _aggregate_row(fold=2, month="2021-01", provenance={}, candidate_id="candidate-a"),
            _aggregate_row(fold=3, month="2021-01", provenance={}, candidate_id="candidate-b"),
        ]
    else:
        rows = [
            _aggregate_row(fold=1, month="2021-01", provenance={}, candidate_id="candidate-a"),
            _aggregate_row(fold=3, month="2021-03", provenance={}, candidate_id="candidate-b"),
        ]
    with pytest.raises(ValueError, match=error):
        aggregate_incremental_rows(_aggregate_spec(candidate_ids=()), rows)


def test_aggregate_retains_explicit_resume_recovery_metadata() -> None:
    spec = IncrementalRunSpec(
        symbol="BTCUSDT",
        start_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2021, 2, 1, tzinfo=timezone.utc),
        data_start_at=datetime(2020, 7, 1, tzinfo=timezone.utc),
        data_end_at=datetime(2021, 2, 1, tzinfo=timezone.utc),
        candidate_group="microstructure",
        candidate_ids=("candidate-a",),
        run_identity="current-run",
    )
    recovery = {"truncated_final_line": {"line_number": 2, "quarantine_path": "rows.truncated"}}

    payload = aggregate_incremental_rows(
        spec,
        [_aggregate_row(fold=1, month="2021-01", provenance={})],
        recovery_metadata=recovery,
    )

    assert payload["resume_recovery"] == recovery


@pytest.mark.parametrize(
    "other_provenance",
    [
        {"archive.zip": {"kind": "rest", "source": "aggTrades"}},
        "not-a-mapping",
    ],
)
def test_aggregate_rejects_conflicting_or_malformed_feature_provenance(other_provenance) -> None:
    spec = IncrementalRunSpec(
        symbol="BTCUSDT",
        start_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2021, 3, 1, tzinfo=timezone.utc),
        data_start_at=datetime(2020, 7, 1, tzinfo=timezone.utc),
        data_end_at=datetime(2021, 3, 1, tzinfo=timezone.utc),
        candidate_group="microstructure",
        candidate_ids=("candidate-a",),
        run_identity="current-run",
    )
    rows = [
        _aggregate_row(
            fold=1,
            month="2021-01",
            provenance={"archive.zip": {"kind": "archive", "source": "aggTrades"}},
        ),
        _aggregate_row(fold=2, month="2021-02", provenance=other_provenance),
    ]

    with pytest.raises(ValueError, match="feature_provenance"):
        aggregate_incremental_rows(spec, rows)


def _aggregate_row(
    *,
    fold: int,
    month: str,
    provenance,
    candidate_id: str = "candidate-a",
) -> dict[str, object]:
    return {
        "symbol": "BTCUSDT",
        "candidate_id": candidate_id,
        "fold": fold,
        "test_start_at": f"{month}-01T00:00:00+00:00",
        "test_end_at": f"{month}-28T00:00:00+00:00",
        "return_ratio": "0",
        "daily_return_ratio": "0",
        "trades_per_day": "0",
        "net_win_rate": "0",
        "average_net_trade_roe": "0",
        "average_net_trade_expectancy_ratio": "0",
        "max_drawdown_ratio": "0",
        "trade_count": 0,
        "run_identity": "current-run",
        "feature_source_coverage": {"aggTrades": 1},
        "feature_unavailable_counts": {"aggTrades": 0},
        "feature_provenance": provenance,
    }


def _aggregate_spec(*, candidate_ids: tuple[str, ...]) -> IncrementalRunSpec:
    return IncrementalRunSpec(
        symbol="BTCUSDT",
        start_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2021, 4, 1, tzinfo=timezone.utc),
        data_start_at=datetime(2020, 7, 1, tzinfo=timezone.utc),
        data_end_at=datetime(2021, 4, 1, tzinfo=timezone.utc),
        candidate_group="microstructure",
        candidate_ids=candidate_ids,
        run_identity="current-run",
    )


def _market_for_hash(*, last_close: Decimal = Decimal("100")) -> MarketSnapshot:
    opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    symbol = Symbol("BTC", "USDT")
    timeframe = Timeframe(1, "m")
    return MarketSnapshot(
        tuple(
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                opened_at=opened_at + timedelta(minutes=index),
                closed_at=opened_at + timedelta(minutes=index + 1),
                open_price=Decimal("100"),
                high_price=Decimal("101"),
                low_price=Decimal("99"),
                close_price=last_close if index == 1 else Decimal("100"),
                volume=Decimal("10"),
            )
            for index in range(2)
        )
    )


def test_incremental_runner_loads_feature_cache_once_and_reuses_provider(monkeypatch, tmp_path: Path) -> None:
    import scripts.incremental_walk_forward_runner as module
    from scripts.scheduler_driven_scalping_backtest import microstructure_alpha_candidates

    candidates = microstructure_alpha_candidates()[:2]
    provider = object()
    loads = []
    passed_providers = []
    hash_calls = []
    original_market_data_hash = module.market_data_hash
    monkeypatch.setattr(module, "load_period_market", lambda period: _market_for_hash())
    monkeypatch.setattr(
        module,
        "_select_candidates",
        lambda group, ids, **kwargs: candidates,
    )
    monkeypatch.setattr(
        module,
        "build_walk_forward_folds",
        lambda **kwargs: ((
            kwargs["test_start"] - timedelta(days=180),
            kwargs["test_start"],
            kwargs["test_start"],
            kwargs["test_end"],
        ),),
    )

    def fake_load(path, **kwargs):
        loads.append((path, kwargs.get("manifest_path")))
        return SimpleNamespace(provider=provider, cache_hash="f" * 64)

    def fake_backtest(*args, **kwargs):
        passed_providers.append(kwargs["market_feature_provider"])
        return {
            "symbol": "BTCUSDT", "candidate_id": kwargs["candidate"].candidate_id,
            "return_ratio": "0", "daily_return_ratio": "0", "trades_per_day": "0",
            "net_win_rate": "0", "average_net_trade_roe": "0",
            "average_net_trade_expectancy_ratio": "0", "max_drawdown_ratio": "0",
            "trade_count": 0, "feature_source_coverage": {"aggTrades": 1},
            "feature_unavailable_counts": {"fundingRate": 1},
            "feature_provenance": {},
            "candidate_definition_hash": candidate_definition_hash(candidate_payload(kwargs["candidate"])),
        }

    monkeypatch.setattr(module, "load_market_feature_cache", fake_load)
    monkeypatch.setattr(module, "run_scheduler_driven_backtest", fake_backtest)
    monkeypatch.setattr(
        module,
        "market_data_hash",
        lambda market: (hash_calls.append(market), original_market_data_hash(market))[1],
    )
    spec = IncrementalRunSpec(
        symbol="BTCUSDT",
        start_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
        end_at=datetime(2021, 2, 1, tzinfo=timezone.utc),
        data_start_at=datetime(2020, 7, 1, tzinfo=timezone.utc),
        data_end_at=datetime(2021, 2, 1, tzinfo=timezone.utc),
        candidate_group="microstructure",
        candidate_ids=(),
    )

    payload = run_incremental_walk_forward(
        spec=spec,
        rows_path=tmp_path / "rows.jsonl",
        payload_path=tmp_path / "payload.json",
        summary_path=tmp_path / "summary.md",
        feature_cache_path=tmp_path / "features.jsonl",
        feature_manifest_path=tmp_path / "explicit.manifest.json",
        include_deferred=True,
    )

    assert loads == [(tmp_path / "features.jsonl", tmp_path / "explicit.manifest.json")]
    assert passed_providers == [provider, provider]
    assert payload["feature_cache_hash"] == "f" * 64
    assert payload["candidate_universe_hash"]
    assert len(hash_calls) == 1
    assert payload["source_coverage"] == {"aggTrades": 1}
    assert payload["unavailable_counts"] == {"fundingRate": 1}
    rows = load_jsonl_rows(tmp_path / "rows.jsonl")
    expected_individual_hashes = {
        candidate.candidate_id: candidate_definition_hash(candidate_payload(candidate))
        for candidate in candidates
    }
    assert {
        row["candidate_id"]: row["candidate_definition_hash"]
        for row in rows
    } == expected_individual_hashes
    assert {row["candidate_universe_hash"] for row in rows} == {payload["candidate_universe_hash"]}
    assert payload["candidate_universe_hash"] == candidate_definition_hash(
        [candidate_payload(candidate) for candidate in candidates]
    )
