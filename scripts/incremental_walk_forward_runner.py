from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.scheduler_driven_scalping_backtest import (  # noqa: E402
    BACKTEST_ENGINE_VERSION,
    FEE_RATE,
    SLIPPAGE_RATE,
    SchedulerBacktestCandidate,
    alpha_entry_candidates,
    build_walk_forward_folds,
    candidate_definition_hash,
    candidate_payload,
    exact_historical_candidates,
    load_market_feature_cache,
    markdown_summary,
    microstructure_alpha_candidates,
    counter_microstructure_candidates,
    metrics_positioning_candidates,
    discovered_metrics_candidates,
    multi_frequency_candidates,
    rank_scheduler_results,
    run_scheduler_driven_backtest,
    summarize_walk_forward_results,
    validate_unique_candidate_ids,
)
from scripts.deferred_strategy_registry import ensure_candidate_group_allowed  # noqa: E402
from scripts.validate_scalping_external_periods import PeriodSpec, load_period_market  # noqa: E402
from src.domain.market import MarketSnapshot, Symbol  # noqa: E402
from src.observability.logging import configure_runtime_logging  # noqa: E402


DEFAULT_ROWS_PATH = Path("docs/backtests/scheduler-driven-wfv-incremental.jsonl")
DEFAULT_PAYLOAD_PATH = Path("docs/backtests/scheduler-driven-wfv-incremental.json")
DEFAULT_SUMMARY_PATH = Path("docs/backtests/scheduler-driven-wfv-incremental.md")


@dataclass(frozen=True)
class IncrementalRunSpec:
    symbol: str
    start_at: datetime
    end_at: datetime
    data_start_at: datetime
    data_end_at: datetime
    candidate_group: str
    candidate_ids: tuple[str, ...]
    feature_cache_hash: str | None = None
    market_data_hash: str = ""
    candidate_universe_hash: str = ""
    run_identity: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_ids", tuple(sorted(set(self.candidate_ids))))


class LoadedJsonlRows(list[dict[str, object]]):
    def __init__(self, rows=(), *, recovery_metadata: dict[str, object] | None = None) -> None:
        super().__init__(rows)
        self.recovery_metadata = recovery_metadata or {}


def write_jsonl_row(path: Path, row: dict[str, object]) -> bool:
    run_identity = row.get("run_identity")
    if not isinstance(run_identity, str) or not run_identity:
        raise ValueError("run_identity is required before writing a resume row")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _rows_file_lock(path):
        rows = load_jsonl_rows(path)
        key = _resume_row_key(row)
        existing = next((existing for existing in rows if _resume_row_key(existing) == key), None)
        if existing is not None:
            if existing != row:
                raise ValueError(f"conflicting duplicate resume key: {key}")
            return False
        encoded = (json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
        try:
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise OSError("incomplete JSONL row append")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return True


def load_jsonl_rows(path: Path) -> LoadedJsonlRows:
    if not path.exists():
        return LoadedJsonlRows()
    rows: list[dict[str, object]] = []
    seen: dict[tuple[str, str, str, int], dict[str, object]] = {}
    recovery: dict[str, object] = {}
    with path.open("rb") as handle:
        line_number = 0
        while True:
            offset = handle.tell()
            raw_line = handle.readline()
            if not raw_line:
                break
            line_number += 1
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                if raw_line.endswith(b"\n"):
                    raise ValueError(f"malformed interior JSONL row on line {line_number}") from error
                digest = hashlib.sha256(raw_line).hexdigest()
                quarantine_path = path.with_name(f"{path.name}.truncated-{digest[:12]}.jsonl")
                if not quarantine_path.exists():
                    quarantine_path.write_bytes(raw_line)
                with path.open("r+b") as output:
                    output.truncate(offset)
                    output.flush()
                    os.fsync(output.fileno())
                recovery["truncated_final_line"] = {
                    "line_number": line_number,
                    "quarantine_path": str(quarantine_path),
                    "sha256": digest,
                }
                break
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row on line {line_number} must be an object")
            if "run_identity" not in row:
                raise ValueError(
                    "legacy resume rows without run_identity are unsupported; use a new rows path"
                )
            key = _resume_row_key(row)
            existing = seen.get(key)
            if existing is None:
                seen[key] = row
                rows.append(row)
            elif existing != row:
                raise ValueError(f"conflicting duplicate resume key: {key}")
    return LoadedJsonlRows(rows, recovery_metadata=recovery)


def _resume_row_key(row: Mapping[str, object]) -> tuple[str, str, str, int]:
    try:
        return (
            str(row["run_identity"]),
            str(row["symbol"]),
            str(row["candidate_id"]),
            int(row["fold"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("resume row identity fields are invalid") from error


def _rows_file_lock_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


@contextmanager
def _rows_file_lock(
    path: Path,
    *,
    timeout_seconds: float = 10.0,
    stale_seconds: float = 300.0,
):
    lock_path = _rows_file_lock_path(path)
    deadline = time.monotonic() + timeout_seconds
    token = uuid.uuid4().hex
    owner = {"pid": os.getpid(), "token": token, "created_at": time.time()}
    encoded_owner = json.dumps(owner, sort_keys=True).encode("utf-8")
    owned_stat = None
    while owned_stat is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            _recover_rows_file_lock_if_stale(lock_path, stale_seconds=stale_seconds)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for resume lock: {lock_path}")
            time.sleep(0.01)
            continue
        try:
            written = os.write(descriptor, encoded_owner)
            if written != len(encoded_owner):
                raise OSError("incomplete rows-file lock metadata write")
            os.fsync(descriptor)
            owned_stat = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    try:
        yield
    finally:
        _cleanup_owned_rows_file_lock(
            lock_path,
            token=token,
            pid=os.getpid(),
            inode=owned_stat.st_ino,
        )


def _cleanup_owned_rows_file_lock(
    lock_path: Path,
    *,
    token: str,
    pid: int,
    inode: int,
    timeout_seconds: float = 1.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            current_stat = lock_path.stat()
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, UnicodeError, json.JSONDecodeError):
            if time.monotonic() >= deadline:
                raise OSError(f"could not verify owned rows-file lock: {lock_path}")
            time.sleep(0.005)
            continue
        if (
            current_stat.st_ino != inode
            or not isinstance(metadata, dict)
            or metadata.get("token") != token
            or metadata.get("pid") != pid
        ):
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


def _recover_rows_file_lock_if_stale(lock_path: Path, *, stale_seconds: float) -> bool:
    try:
        observed_stat = lock_path.stat()
        raw = lock_path.read_bytes()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    malformed = False
    try:
        metadata = json.loads(raw.decode("utf-8"))
        pid = metadata["pid"]
        token = metadata["token"]
        created_at = metadata["created_at"]
        if (
            not isinstance(pid, int)
            or isinstance(pid, bool)
            or pid <= 0
            or not isinstance(token, str)
            or not token
            or not isinstance(created_at, (int, float))
            or isinstance(created_at, bool)
        ):
            malformed = True
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        malformed = True

    recoverable = (
        time.time() - observed_stat.st_mtime >= stale_seconds
        if malformed
        else not _process_is_alive(pid)
    )
    if not recoverable:
        return False
    try:
        if lock_path.stat().st_ino != observed_stat.st_ino or lock_path.read_bytes() != raw:
            return False
        lock_path.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


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

    process_query_limited_information = 0x1000
    still_active = 259
    error_access_denied = 5
    error_invalid_parameter = 87
    error_not_found = 1168

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    get_exit_code.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    ctypes.set_last_error(0)
    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_access_denied:
            return True
        if error in (error_invalid_parameter, error_not_found):
            return False
        return True

    try:
        exit_code = wintypes.DWORD()
        ctypes.set_last_error(0)
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            error = ctypes.get_last_error()
            if error == error_access_denied:
                return True
            if error in (error_invalid_parameter, error_not_found):
                return False
            return True
        return exit_code.value == still_active
    finally:
        close_handle(handle)


def completed_keys(
    rows: Iterable[dict[str, object]],
    *,
    run_identity: str | None = None,
) -> set[tuple[str, str, int]]:
    return {
        (str(row["symbol"]), str(row["candidate_id"]), int(row["fold"]))
        for row in rows
        if run_identity is None or row.get("run_identity") == run_identity
    }


def build_run_identity(
    spec: IncrementalRunSpec,
    *,
    feature_cache_hash: str | None,
    candidate_universe_hash: str,
    market_data_hash: str,
    folds: tuple[tuple[datetime, datetime, datetime, datetime], ...],
    engine_version: str = BACKTEST_ENGINE_VERSION,
    fee_rate=FEE_RATE,
    slippage_rate=SLIPPAGE_RATE,
) -> str:
    payload = {
        "symbol": spec.symbol,
        "start_at": spec.start_at.isoformat(),
        "end_at": spec.end_at.isoformat(),
        "data_start_at": spec.data_start_at.isoformat(),
        "data_end_at": spec.data_end_at.isoformat(),
        "candidate_group": spec.candidate_group,
        "candidate_ids": list(spec.candidate_ids),
        "backtest_engine_version": engine_version,
        "fee_rate": str(fee_rate),
        "slippage_rate": str(slippage_rate),
        "market_data_hash": market_data_hash,
        "feature_cache_hash": feature_cache_hash,
        "candidate_universe_hash": candidate_universe_hash,
        "folds": [
            [value.isoformat() for value in fold]
            for fold in folds
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def market_data_hash(market: MarketSnapshot) -> str:
    digest = hashlib.sha256()
    for candle in market.candles:
        payload = (
            candle.opened_at.isoformat(),
            candle.closed_at.isoformat(),
            str(candle.open_price),
            str(candle.high_price),
            str(candle.low_price),
            str(candle.close_price),
            str(candle.volume),
        )
        digest.update(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def aggregate_incremental_rows(
    spec: IncrementalRunSpec,
    rows: list[dict[str, object]],
    *,
    recovery_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    filtered = [
        row
        for row in rows
        if row.get("symbol") == spec.symbol
        and (not spec.candidate_ids or row.get("candidate_id") in spec.candidate_ids)
        and (not spec.run_identity or row.get("run_identity") == spec.run_identity)
    ]
    fold_boundaries = _validated_fold_boundaries(filtered)
    results_by_fold: dict[int, list[dict[str, object]]] = {}
    by_candidate: dict[str, list[dict[str, object]]] = {}
    candidate_series: dict[str, list[dict[str, str]]] = {}
    for row in sorted(filtered, key=lambda item: (int(item["fold"]), str(item["candidate_id"]))):
        fold_number = int(row["fold"])
        result = {key: value for key, value in row.items() if key not in {"fold", "test_start_at", "test_end_at", "run_identity"}}
        results_by_fold.setdefault(fold_number, []).append(result)
        candidate_id = str(row["candidate_id"])
        by_candidate.setdefault(candidate_id, []).append(result)
        candidate_series.setdefault(candidate_id, []).append(
            {
                "month": str(row["test_start_at"])[:7],
                "return_ratio": str(row["return_ratio"]),
            }
        )

    folds = [
        {
            "fold": fold_number,
            "test_start_at": fold_boundaries[fold_number][0],
            "test_end_at": fold_boundaries[fold_number][1],
            "results": rank_scheduler_results(results),
        }
        for fold_number, results in sorted(results_by_fold.items())
    ]
    source_coverage = _consistent_count_mapping(filtered, "feature_source_coverage")
    unavailable_counts = _consistent_count_mapping(filtered, "feature_unavailable_counts")
    feature_provenance = _consistent_mapping(filtered, "feature_provenance")
    return {
        "mode": "walk_forward_incremental",
        "symbol": spec.symbol,
        "candidate_group": spec.candidate_group,
        "candidate_ids": list(spec.candidate_ids),
        "feature_cache_hash": spec.feature_cache_hash,
        "market_data_hash": spec.market_data_hash,
        "candidate_universe_hash": spec.candidate_universe_hash,
        "backtest_engine_version": BACKTEST_ENGINE_VERSION,
        "run_identity": spec.run_identity,
        "source_coverage": source_coverage,
        "unavailable_counts": unavailable_counts,
        "feature_source_coverage": source_coverage,
        "feature_unavailable_counts": unavailable_counts,
        "feature_provenance": feature_provenance,
        "resume_recovery": dict(recovery_metadata or {}),
        "start_at": spec.start_at.isoformat(),
        "end_at": spec.end_at.isoformat(),
        "data_start_at": spec.data_start_at.isoformat(),
        "data_end_at": spec.data_end_at.isoformat(),
        "fold_count": len(folds),
        "candidate_count": len(by_candidate),
        "folds": folds,
        "candidate_series": {
            candidate_id: sorted(series, key=lambda item: item["month"])
            for candidate_id, series in sorted(candidate_series.items())
        },
        "results": summarize_walk_forward_results(by_candidate),
    }


def _validated_fold_boundaries(
    rows: Iterable[dict[str, object]],
) -> dict[int, tuple[str, str]]:
    fold_to_boundary: dict[int, tuple[str, str]] = {}
    boundary_to_fold: dict[tuple[str, str], int] = {}
    for row in rows:
        fold_value = row.get("fold")
        if not isinstance(fold_value, int) or isinstance(fold_value, bool) or fold_value < 1:
            raise ValueError("fold number must be a positive JSON integer")
        test_start = row.get("test_start_at")
        test_end = row.get("test_end_at")
        if not isinstance(test_start, str) or not isinstance(test_end, str):
            raise ValueError("fold boundaries must be timestamp strings")
        try:
            start_at = datetime.fromisoformat(test_start)
            end_at = datetime.fromisoformat(test_end)
        except ValueError as error:
            raise ValueError("fold boundaries must be ISO timestamps") from error
        if (
            start_at.tzinfo is None
            or end_at.tzinfo is None
            or start_at >= end_at
        ):
            raise ValueError("fold boundaries must be timezone-aware and increasing")
        boundary = (test_start, test_end)
        existing_boundary = fold_to_boundary.get(fold_value)
        if existing_boundary is not None and existing_boundary != boundary:
            raise ValueError(f"fold {fold_value} has conflicting boundaries")
        existing_fold = boundary_to_fold.get(boundary)
        if existing_fold is not None and existing_fold != fold_value:
            raise ValueError(
                f"boundary {boundary!r} is assigned to conflicting fold numbers"
            )
        fold_to_boundary[fold_value] = boundary
        boundary_to_fold[boundary] = fold_value

    fold_numbers = sorted(fold_to_boundary)
    if len(fold_numbers) > 1 and fold_numbers != list(
        range(fold_numbers[0], fold_numbers[-1] + 1)
    ):
        raise ValueError("fold number gap in selected run rows")
    return fold_to_boundary


def _consistent_count_mapping(rows: Iterable[dict[str, object]], field: str) -> dict[str, int]:
    selected: dict[str, int] | None = None
    for row in rows:
        values = row.get(field, {})
        if not isinstance(values, dict):
            continue
        normalized = {str(name): int(count) for name, count in values.items()}
        if selected is None:
            selected = normalized
        elif normalized != selected:
            raise ValueError(f"conflicting {field} values for one run identity")
    return dict(sorted((selected or {}).items()))


def _consistent_mapping(rows: Iterable[dict[str, object]], field: str) -> dict[str, object]:
    selected: dict[str, object] | None = None
    for row in rows:
        values = row.get(field, {})
        if not isinstance(values, Mapping):
            raise ValueError(f"{field} must be a mapping for one run identity")
        current = dict(values)
        if selected is None:
            selected = current
        elif current != selected:
            raise ValueError(f"conflicting {field} values for one run identity")
    return selected or {}


def run_incremental_walk_forward(
    *,
    spec: IncrementalRunSpec,
    rows_path: Path,
    payload_path: Path,
    summary_path: Path,
    feature_cache_path: Path | None = None,
    feature_manifest_path: Path | None = None,
    include_deferred: bool = False,
) -> dict[str, object]:
    symbol = _parse_symbol(spec.symbol)
    candidates = _select_candidates(
        spec.candidate_group,
        spec.candidate_ids,
        include_deferred=include_deferred,
    )
    period = PeriodSpec(
        spec.symbol,
        f"scheduler-driven-{spec.symbol.lower()}-{_label_date(spec.data_start_at)}_{_label_date(spec.data_end_at)}",
        _date_arg(spec.data_start_at),
        _date_arg(spec.data_end_at),
    )
    market = load_period_market(period)
    if market is None:
        raise RuntimeError("no market data loaded")
    universe_hash = candidate_definition_hash([candidate_payload(candidate) for candidate in candidates])
    data_hash = market_data_hash(market)
    folds = build_walk_forward_folds(test_start=spec.start_at, test_end=spec.end_at)
    loaded_features = (
        load_market_feature_cache(
            feature_cache_path,
            manifest_path=feature_manifest_path,
            expected_symbol=symbol,
        )
        if feature_cache_path is not None
        else None
    )
    cache_hash = loaded_features.cache_hash if loaded_features is not None else None
    run_identity = build_run_identity(
        spec,
        feature_cache_hash=cache_hash,
        candidate_universe_hash=universe_hash,
        market_data_hash=data_hash,
        folds=folds,
    )
    current_spec = replace(
        spec,
        feature_cache_hash=cache_hash,
        market_data_hash=data_hash,
        candidate_universe_hash=universe_hash,
        run_identity=run_identity,
    )
    feature_provider = loaded_features.provider if loaded_features is not None else None
    rows = load_jsonl_rows(rows_path)
    recovery_metadata = dict(rows.recovery_metadata)
    done = completed_keys(rows, run_identity=run_identity)
    for fold_index, (_, _, test_start, test_end) in enumerate(folds, start=1):
        for candidate in candidates:
            key = (spec.symbol, candidate.candidate_id, fold_index)
            if key in done:
                continue
            result = run_scheduler_driven_backtest(
                market,
                start_at=test_start,
                end_at=test_end,
                candidate=candidate,
                symbol=symbol,
                market_feature_provider=feature_provider,
                include_deferred=include_deferred,
            )
            row = {
                **{key: value for key, value in result.items() if key != "candidate"},
                "fold": fold_index,
                "test_start_at": test_start.isoformat(),
                "test_end_at": test_end.isoformat(),
                "feature_cache_hash": cache_hash,
                "candidate_universe_hash": universe_hash,
                "run_identity": run_identity,
            }
            write_jsonl_row(rows_path, row)
            rows = load_jsonl_rows(rows_path)
            recovery_metadata.update(rows.recovery_metadata)
            done = completed_keys(rows, run_identity=run_identity)
            payload = aggregate_incremental_rows(
                current_spec,
                rows,
                recovery_metadata=recovery_metadata,
            )
            _write_payloads(payload, payload_path, summary_path)
    payload = aggregate_incremental_rows(
        current_spec,
        rows,
        recovery_metadata=recovery_metadata,
    )
    _write_payloads(payload, payload_path, summary_path)
    return payload


def _write_payloads(payload: dict[str, object], payload_path: Path, summary_path: Path) -> None:
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(markdown_summary({**payload, "mode": "walk_forward"}, limit=20), encoding="utf-8")


def _select_candidates(
    candidate_group: str,
    candidate_ids: tuple[str, ...],
    *,
    include_deferred: bool = False,
) -> tuple[SchedulerBacktestCandidate, ...]:
    ensure_candidate_group_allowed(
        candidate_group,
        include_deferred=include_deferred,
    )
    if candidate_group == "multi":
        candidates = tuple(multi_frequency_candidates())
    elif candidate_group == "exact":
        candidates = tuple(exact_historical_candidates())
    elif candidate_group == "alpha":
        candidates = tuple(alpha_entry_candidates())
    elif candidate_group == "microstructure":
        candidates = tuple(microstructure_alpha_candidates())
    elif candidate_group == "counter":
        candidates = tuple(counter_microstructure_candidates())
    elif candidate_group == "metrics":
        candidates = tuple(metrics_positioning_candidates())
    elif candidate_group == "discovered":
        candidates = tuple(discovered_metrics_candidates())
    else:
        raise ValueError(
            "candidate_group must be multi, exact, alpha, microstructure, counter, metrics, or discovered"
        )
    candidates = validate_unique_candidate_ids(candidates)
    requested_ids = tuple(sorted(set(candidate_ids)))
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    unknown_ids = tuple(candidate_id for candidate_id in requested_ids if candidate_id not in by_id)
    if unknown_ids:
        raise ValueError(f"unknown candidate_id: {', '.join(unknown_ids)}")
    if requested_ids:
        candidates = tuple(by_id[candidate_id] for candidate_id in requested_ids)
    else:
        candidates = tuple(sorted(candidates, key=lambda candidate: candidate.candidate_id))
    if not candidates:
        raise ValueError("no candidates selected")
    return candidates


def _parse_datetime(value: str) -> datetime:
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    raise ValueError(f"unsupported date format: {value}")


def _parse_symbol(value: str) -> Symbol:
    normalized = value.upper()
    if not normalized.endswith("USDT") or len(normalized) <= 4:
        raise ValueError(f"unsupported symbol format: {value}")
    return Symbol(normalized[:-4], "USDT")


def _label_date(value: datetime) -> str:
    return f"{value.year}-{value.month}-{value.day}"


def _date_arg(value: datetime) -> str:
    return f"{value.year}/{value.month}/{value.day}"


def main() -> None:
    configure_runtime_logging(level="ERROR")
    parser = argparse.ArgumentParser(description="Run scheduler-driven WFV with resumable JSONL output.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2021/1/1")
    parser.add_argument("--end", default="2026/7/1")
    parser.add_argument("--data-start", default=None)
    parser.add_argument("--data-end", default=None)
    parser.add_argument(
        "--candidate-group",
        choices=("multi", "exact", "alpha", "microstructure", "counter", "metrics", "discovered"),
        default="multi",
    )
    parser.add_argument("--candidate-id", action="append", default=[])
    parser.add_argument(
        "--include-deferred",
        action="store_true",
        help="Allow intentional reproduction of a group in the deferred strategy registry.",
    )
    parser.add_argument("--rows-path", type=Path, default=DEFAULT_ROWS_PATH)
    parser.add_argument("--payload-path", type=Path, default=DEFAULT_PAYLOAD_PATH)
    parser.add_argument("--summary-path", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--feature-cache", type=Path, default=None)
    parser.add_argument("--feature-cache-manifest", type=Path, default=None)
    args = parser.parse_args()

    spec = IncrementalRunSpec(
        symbol=args.symbol.upper(),
        start_at=_parse_datetime(args.start),
        end_at=_parse_datetime(args.end),
        data_start_at=_parse_datetime(args.data_start or args.start),
        data_end_at=_parse_datetime(args.data_end or args.end),
        candidate_group=args.candidate_group,
        candidate_ids=tuple(args.candidate_id),
    )
    ensure_candidate_group_allowed(
        args.candidate_group,
        include_deferred=args.include_deferred,
    )
    payload = run_incremental_walk_forward(
        spec=spec,
        rows_path=args.rows_path,
        payload_path=args.payload_path,
        summary_path=args.summary_path,
        feature_cache_path=args.feature_cache,
        feature_manifest_path=args.feature_cache_manifest,
        include_deferred=args.include_deferred,
    )
    print(f"ROWS {args.rows_path}")
    print(f"PAYLOAD {args.payload_path}")
    print(f"SUMMARY {args.summary_path}")
    print(f"FOLDS {payload['fold_count']}")
    print(f"CANDIDATES {payload['candidate_count']}")


if __name__ == "__main__":
    main()
