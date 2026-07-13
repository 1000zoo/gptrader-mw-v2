from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


REQUIRED_FIELDS = (
    "symbol",
    "candidate_id",
    "test_start_at",
    "test_end_at",
    "return_ratio",
    "trade_count",
    "average_net_trade_expectancy_ratio",
    "max_drawdown_ratio",
)
TRAIN_NUMERIC_FIELDS = (
    "return_ratio",
    "trade_count",
    "average_net_trade_expectancy_ratio",
    "max_drawdown_ratio",
)


def evaluate_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    symbol: str,
    train_months: int = 6,
    top_k: int = 3,
    min_train_trades: int = 0,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, object]:
    _validate_options(train_months, top_k, min_train_trades)
    if not symbol:
        raise ValueError("symbol is required")
    _validate_source_rows(rows)
    matched_rows = [row for row in rows if _row_matches_symbol(row, symbol)]
    unique_rows = _deduplicate_rows(matched_rows)
    by_month, by_candidate = _index_rows(unique_rows)
    start_month = _month_key(start) if start else None
    end_month = _month_key(end) if end else None

    if start_month and end_month:
        test_months = _calendar_months(start_month, end_month)
    else:
        test_months = sorted(by_month)

    folds: list[dict[str, object]] = []
    for test_month in test_months:
        if start_month and test_month < start_month:
            continue
        if end_month and test_month >= end_month:
            continue
        train_month_keys = _prior_months(test_month, train_months)
        folds.append(
            _evaluate_fold(
                test_month=test_month,
                train_months=train_month_keys,
                test_rows=by_month.get(test_month, []),
                by_candidate=by_candidate,
                top_k=top_k,
                min_train_trades=min_train_trades,
            )
        )

    top_1_series = []
    equal_weight_series = []
    for fold in folds:
        selections = fold["selections"]
        top_1_available = bool(selections and selections[0]["availability"])
        top_k_available = bool(selections) and all(
            selection["availability"] for selection in selections
        )
        if fold["status"] == "cash":
            top_1_available = True
            top_k_available = True
        top_1_series.append(
            _series_row(
                month=str(fold["test_month"]),
                return_ratio=str(fold["top_1_oos_return_ratio"]),
                available=top_1_available,
                candidate_id=(selections[0]["candidate_id"] if selections else None),
                include_candidate_id=True,
            )
        )
        equal_weight_series.append(
            _series_row(
                month=str(fold["test_month"]),
                return_ratio=str(fold["equal_weight_top_k_oos_return_ratio"]),
                available=top_k_available,
            )
        )
    return {
        "mode": "train_selected_walk_forward",
        "symbol": symbol,
        "train_months": train_months,
        "top_k": top_k,
        "min_train_trades": min_train_trades,
        "start": start,
        "end": end,
        "input_row_count": len(matched_rows),
        "deduplicated_row_count": len(unique_rows),
        "fold_count": len(folds),
        "candidate_universe": sorted(by_candidate),
        "folds": folds,
        "top_1_oos_series": top_1_series,
        "equal_weight_top_k_oos_series": equal_weight_series,
        "top_1_oos_summary": _series_summary(top_1_series),
        "equal_weight_top_k_oos_summary": _series_summary(equal_weight_series),
    }


def load_jsonl_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"invalid JSONL at line {line_number}: row must be an object")
        rows.append(row)
    return rows


def render_markdown(payload: Mapping[str, object]) -> str:
    top_1 = payload["top_1_oos_summary"]
    top_k = payload["equal_weight_top_k_oos_summary"]
    assert isinstance(top_1, Mapping) and isinstance(top_k, Mapping)
    lines = [
        "# Train-Selected Walk-Forward Evaluation",
        "",
        f"- Symbol: `{payload['symbol']}`",
        f"- Train window: {payload['train_months']} calendar months",
        f"- Top K: {payload['top_k']}",
        f"- Minimum train trades: {payload['min_train_trades']}",
        f"- Folds: {payload['fold_count']}",
        "",
        "## OOS Summary",
        "",
        "| Series | Positive months | Unavailable months | Compounded return | Average month | Worst month |",
        "|---|---:|---:|---:|---:|---:|",
        _summary_markdown_row("Top 1", top_1),
        _summary_markdown_row("Equal-weight top K", top_k),
        "",
        "## Folds",
        "",
        "| Test month | Status | Selected | Top 1 OOS | Top K OOS |",
        "|---|---|---|---:|---:|",
    ]
    folds = payload["folds"]
    assert isinstance(folds, Sequence)
    for fold in folds:
        assert isinstance(fold, Mapping)
        selections = fold["selections"]
        assert isinstance(selections, Sequence)
        selected = ", ".join(str(selection["candidate_id"]) for selection in selections)
        lines.append(
            f"| {fold['test_month']} | {fold['status']} | {selected or 'cash'} | "
            f"{fold['top_1_oos_return_ratio']} | {fold['equal_weight_top_k_oos_return_ratio']} |"
        )
    lines.extend(
        [
            "",
            "## Selection Evidence",
            "",
            "| Test month | Rank | Candidate | Train return | Positive months | Train expectancy | "
            "Train trades | Worst drawdown | OOS return |",
            "|---|---:|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for fold in folds:
        assert isinstance(fold, Mapping)
        selections = fold["selections"]
        assert isinstance(selections, Sequence)
        for selection in selections:
            assert isinstance(selection, Mapping)
            evidence = selection["train_evidence"]
            test_result = selection["oos_test_result"]
            assert isinstance(evidence, Mapping)
            oos_result = (
                str(test_result["return_ratio"])
                if isinstance(test_result, Mapping)
                else "0 (unavailable)"
            )
            lines.append(
                f"| {fold['test_month']} | {selection['rank']} | {selection['candidate_id']} | "
                f"{evidence['compounded_return']} | {evidence['positive_month_count']}/"
                f"{evidence['month_count']} | {evidence['aggregate_net_trade_expectancy_ratio']} | "
                f"{evidence['total_trade_count']} | {evidence['worst_max_drawdown_ratio']} | "
                f"{oos_result} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Select on trailing train months and evaluate only on the next OOS month."
    )
    parser.add_argument("--rows-path", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--train-months", type=int, default=6)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-train-trades", type=int, default=0)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--payload-path", type=Path, required=True)
    parser.add_argument("--summary-path", type=Path, required=True)
    args = parser.parse_args(argv)

    payload = evaluate_rows(
        load_jsonl_rows(args.rows_path),
        symbol=args.symbol,
        train_months=args.train_months,
        top_k=args.top_k,
        min_train_trades=args.min_train_trades,
        start=args.start,
        end=args.end,
    )
    payload["source_rows_path"] = str(args.rows_path)
    payload["source_rows_sha256"] = hashlib.sha256(args.rows_path.read_bytes()).hexdigest()
    args.payload_path.parent.mkdir(parents=True, exist_ok=True)
    args.payload_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.summary_path.parent.mkdir(parents=True, exist_ok=True)
    args.summary_path.write_text(render_markdown(payload), encoding="utf-8")


def _validate_options(train_months: int, top_k: int, min_train_trades: int) -> None:
    if train_months <= 0:
        raise ValueError("train_months must be positive")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if min_train_trades < 0:
        raise ValueError("min_train_trades cannot be negative")


def _validate_source_rows(rows: Sequence[Mapping[str, object]]) -> None:
    for row_number, row in enumerate(rows, start=1):
        missing = [field for field in REQUIRED_FIELDS if field not in row]
        if missing:
            raise ValueError(f"row {row_number} is missing required fields: {', '.join(missing)}")
        if not str(row["symbol"]):
            raise ValueError(f"row {row_number} symbol is required")
        start_at = _utc_month_boundary(row["test_start_at"], "test_start_at")
        end_at = _utc_month_boundary(row["test_end_at"], "test_end_at")
        if end_at != _next_month_boundary(start_at):
            raise ValueError(
                f"test_end_at must be exactly the next UTC month boundary for row {row_number}"
            )

        candidate_id = str(row["candidate_id"])
        month = f"{start_at.year:04d}-{start_at.month:02d}"
        return_ratio = _decimal(row["return_ratio"], "return_ratio", candidate_id, month)
        trade_count = _decimal(row["trade_count"], "trade_count", candidate_id, month)
        expectancy = _decimal(
            row["average_net_trade_expectancy_ratio"],
            "average_net_trade_expectancy_ratio",
            candidate_id,
            month,
        )
        max_drawdown = _decimal(
            row["max_drawdown_ratio"], "max_drawdown_ratio", candidate_id, month
        )
        if return_ratio <= Decimal("-1"):
            raise ValueError(f"return_ratio must be greater than -1 for {candidate_id} in {month}")
        if trade_count < 0 or trade_count != trade_count.to_integral_value():
            raise ValueError(
                f"trade_count must be a nonnegative integer for {candidate_id} in {month}"
            )
        if max_drawdown < 0:
            raise ValueError(
                f"max_drawdown_ratio must be nonnegative for {candidate_id} in {month}"
            )
        if not expectancy.is_finite():
            raise ValueError(
                f"average_net_trade_expectancy_ratio must be finite for {candidate_id} in {month}"
            )


def _row_matches_symbol(row: Mapping[str, object], symbol: str) -> bool:
    return str(row["symbol"]) == symbol


def _deduplicate_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    unique: dict[tuple[str, str], dict[str, object]] = {}
    signatures: dict[tuple[str, str], tuple[object, ...]] = {}
    for row_number, source_row in enumerate(rows, start=1):
        missing = [field for field in REQUIRED_FIELDS if field not in source_row]
        if missing:
            raise ValueError(f"row {row_number} is missing required fields: {', '.join(missing)}")
        row = dict(source_row)
        candidate_id = str(row["candidate_id"])
        month = _month_key(row["test_start_at"])
        key = (candidate_id, month)
        signature = _duplicate_signature(row)
        if key in unique:
            if signatures[key] != signature:
                raise ValueError(
                    f"conflicting duplicate candidate/month row for {candidate_id} in {month}"
                )
            continue
        unique[key] = row
        signatures[key] = signature
    return list(unique.values())


def _duplicate_signature(row: Mapping[str, object]) -> tuple[object, ...]:
    canonical = _canonical_json(row)
    assert isinstance(canonical, tuple)
    return canonical


def _canonical_json(value: object) -> tuple[object, ...]:
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("duplicate row contains a non-string JSON object key")
        return (
            "object",
            tuple((key, _canonical_json(value[key])) for key in sorted(value)),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return ("array", tuple(_canonical_json(item) for item in value))
    numeric = _optional_decimal(value)
    if numeric is not None:
        if not numeric.is_finite():
            raise ValueError(f"duplicate row contains a non-finite numeric value: {value}")
        return ("number", numeric)
    if isinstance(value, str):
        return ("string", value)
    raise ValueError(f"duplicate row contains a non-JSON-compatible value: {value}")


def _index_rows(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, list[dict[str, object]]], dict[str, dict[str, dict[str, object]]]]:
    by_month: dict[str, list[dict[str, object]]] = {}
    by_candidate: dict[str, dict[str, dict[str, object]]] = {}
    boundaries: dict[str, tuple[str, str]] = {}
    for source_row in rows:
        row = dict(source_row)
        month = _month_key(row["test_start_at"])
        candidate_id = str(row["candidate_id"])
        for field in TRAIN_NUMERIC_FIELDS:
            _decimal(row[field], field, candidate_id, month)
        boundary = (
            _utc_month_boundary(row["test_start_at"], "test_start_at").isoformat(),
            _utc_month_boundary(row["test_end_at"], "test_end_at").isoformat(),
        )
        if month in boundaries and boundaries[month] != boundary:
            raise ValueError(f"conflicting test boundaries for month {month}")
        boundaries[month] = boundary
        by_month.setdefault(month, []).append(row)
        by_candidate.setdefault(candidate_id, {})[month] = row
    return by_month, by_candidate


def _evaluate_fold(
    *,
    test_month: str,
    train_months: list[str],
    test_rows: Sequence[dict[str, object]],
    by_candidate: Mapping[str, Mapping[str, dict[str, object]]],
    top_k: int,
    min_train_trades: int,
) -> dict[str, object]:
    eligible: list[tuple[Decimal, str, dict[str, object]]] = []
    test_by_candidate = {str(row["candidate_id"]): row for row in test_rows}
    for candidate_id in sorted(by_candidate):
        candidate_rows = by_candidate[candidate_id]
        if not all(month in candidate_rows for month in train_months):
            continue
        evidence = _train_evidence([candidate_rows[month] for month in train_months])
        if not _passes_train_gate(evidence, len(train_months), min_train_trades):
            continue
        eligible.append((_decimal(evidence["score"]), candidate_id, evidence))
    eligible.sort(key=lambda item: (-item[0], item[1]))

    selections: list[dict[str, object]] = []
    for rank, (score, candidate_id, evidence) in enumerate(eligible[:top_k], start=1):
        test_result = test_by_candidate.get(candidate_id)
        available = test_result is not None
        selections.append(
            {
                "rank": rank,
                "candidate_id": candidate_id,
                "train_score": _decimal_text(score),
                "train_evidence": evidence,
                "availability": available,
                "oos_status": "available" if available else "unavailable",
                "oos_test_result": test_result,
            }
        )
    test_start_at, test_end_at = _month_bounds(test_month)
    selected_returns = [
        _decimal(selection["oos_test_result"]["return_ratio"])
        if selection["oos_test_result"] is not None
        else Decimal("0")
        for selection in selections
    ]
    top_1_return = selected_returns[0] if selected_returns else Decimal("0")
    top_k_return = _average(selected_returns)
    unavailable_selection_count = sum(
        1 for selection in selections if not selection["availability"]
    )
    if not test_rows:
        status = "unavailable"
    elif not selections:
        status = "cash"
    elif unavailable_selection_count == 0:
        status = "selected"
    elif unavailable_selection_count == len(selections):
        status = "unavailable"
    else:
        status = "partial_unavailable"
    return {
        "test_month": test_month,
        "test_start_at": test_start_at,
        "test_end_at": test_end_at,
        "train_months": train_months,
        "status": status,
        "selections": selections,
        "top_1_oos_return_ratio": _decimal_text(top_1_return),
        "equal_weight_top_k_oos_return_ratio": _decimal_text(top_k_return),
    }


def _train_evidence(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    returns = [_decimal(row["return_ratio"]) for row in rows]
    trades = [_decimal(row["trade_count"]) for row in rows]
    expectancies = [_decimal(row["average_net_trade_expectancy_ratio"]) for row in rows]
    drawdowns = [_decimal(row["max_drawdown_ratio"]) for row in rows]
    total_trades = sum(trades, Decimal("0"))
    aggregate_expectancy = (
        sum((expectancy * trade_count for expectancy, trade_count in zip(expectancies, trades)), Decimal("0"))
        / total_trades
        if total_trades > 0
        else Decimal("0")
    )
    compounded_return = _compound(returns)
    positive_month_count = sum(1 for value in returns if value > 0)
    positive_month_ratio = Decimal(positive_month_count) / Decimal(len(returns))
    worst_drawdown = max(drawdowns)
    score = (
        compounded_return * positive_month_ratio + aggregate_expectancy
    ) / (Decimal("1") + worst_drawdown)
    return {
        "months": [
            {
                "month": _month_key(row["test_start_at"]),
                "return_ratio": str(row["return_ratio"]),
                "trade_count": row["trade_count"],
                "average_net_trade_expectancy_ratio": str(
                    row["average_net_trade_expectancy_ratio"]
                ),
                "max_drawdown_ratio": str(row["max_drawdown_ratio"]),
            }
            for row in rows
        ],
        "month_count": len(rows),
        "compounded_return": _decimal_text(compounded_return),
        "positive_month_count": positive_month_count,
        "positive_month_ratio": _decimal_text(positive_month_ratio),
        "aggregate_net_trade_expectancy_ratio": _decimal_text(aggregate_expectancy),
        "total_trade_count": _number_text(total_trades),
        "worst_max_drawdown_ratio": _decimal_text(worst_drawdown),
        "score": _decimal_text(score),
    }


def _passes_train_gate(
    evidence: Mapping[str, object], train_months: int, min_train_trades: int
) -> bool:
    return (
        _decimal(evidence["compounded_return"]) > 0
        and int(evidence["positive_month_count"]) >= (train_months + 1) // 2
        and _decimal(evidence["aggregate_net_trade_expectancy_ratio"]) > 0
        and _decimal(evidence["total_trade_count"]) >= Decimal(min_train_trades)
    )


def _series_summary(series: Sequence[Mapping[str, object]]) -> dict[str, object]:
    returns = [_decimal(row["return_ratio"]) for row in series]
    return {
        "month_count": len(returns),
        "unavailable_month_count": sum(
            1 for row in series if row.get("available", True) is False
        ),
        "positive_month_ratio": _decimal_text(
            Decimal(sum(1 for value in returns if value > 0)) / Decimal(len(returns))
            if returns
            else Decimal("0")
        ),
        "compounded_return": _decimal_text(_compound(returns)),
        "average_monthly_return": _decimal_text(_average(returns)),
        "worst_monthly_result": _decimal_text(min(returns)) if returns else None,
    }


def _summary_markdown_row(label: str, summary: Mapping[str, object]) -> str:
    return (
        f"| {label} | {summary['positive_month_ratio']} | "
        f"{summary['unavailable_month_count']} | {summary['compounded_return']} | "
        f"{summary['average_monthly_return']} | {summary['worst_monthly_result']} |"
    )


def _series_row(
    *,
    month: str,
    return_ratio: str,
    available: bool,
    candidate_id: object | None = None,
    include_candidate_id: bool = False,
) -> dict[str, object]:
    row: dict[str, object] = {"month": month}
    if include_candidate_id:
        row["candidate_id"] = candidate_id
    if not available:
        row["available"] = False
    row["return_ratio"] = return_ratio
    return row


def _calendar_months(start: str, end: str) -> list[str]:
    if start >= end:
        raise ValueError("start must be before end")
    months = []
    current = start
    while current < end:
        months.append(current)
        current_start = _utc_month_boundary(
            f"{current}-01T00:00:00+00:00", "test_start_at"
        )
        next_start = _next_month_boundary(current_start)
        current = f"{next_start.year:04d}-{next_start.month:02d}"
    return months


def _month_bounds(month: str) -> tuple[str, str]:
    start_at = _utc_month_boundary(f"{month}-01T00:00:00+00:00", "test_start_at")
    end_at = _next_month_boundary(start_at)
    return start_at.isoformat(), end_at.isoformat()


def _utc_month_boundary(value: object, field: str) -> datetime:
    message = (
        f"{field} must be exactly the next UTC month boundary"
        if field == "test_end_at"
        else f"{field} must be exactly a UTC month boundary"
    )
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(message) from exc
    if (
        parsed.utcoffset() != timedelta(0)
        or parsed.day != 1
        or parsed.hour != 0
        or parsed.minute != 0
        or parsed.second != 0
        or parsed.microsecond != 0
    ):
        raise ValueError(message)
    return parsed.astimezone(timezone.utc)


def _next_month_boundary(value: datetime) -> datetime:
    if value.month == 12:
        return value.replace(year=value.year + 1, month=1)
    return value.replace(month=value.month + 1)


def _prior_months(month: str, count: int) -> list[str]:
    year, month_number = (int(part) for part in month.split("-"))
    absolute_month = year * 12 + month_number - 1
    return [
        f"{value // 12:04d}-{value % 12 + 1:02d}"
        for value in range(absolute_month - count, absolute_month)
    ]


def _month_key(value: object) -> str:
    text = str(value)
    if len(text) < 7 or text[4:5] != "-" or not text[:4].isdigit() or not text[5:7].isdigit():
        raise ValueError(f"invalid month/date value: {value}")
    month_number = int(text[5:7])
    if month_number < 1 or month_number > 12:
        raise ValueError(f"invalid month/date value: {value}")
    return text[:7]


def _compound(values: Sequence[Decimal]) -> Decimal:
    growth = Decimal("1")
    for value in values:
        growth *= Decimal("1") + value
    return growth - Decimal("1")


def _average(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else Decimal("0")


def _decimal(
    value: object,
    field: str | None = None,
    candidate_id: str | None = None,
    month: str | None = None,
) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        location = f" for {candidate_id} in {month}" if candidate_id and month else ""
        raise ValueError(f"invalid numeric {field or 'value'}{location}: {value}") from exc
    if not result.is_finite():
        location = f" for {candidate_id} in {month}" if candidate_id and month else ""
        raise ValueError(f"{field or 'value'} must be finite{location}: {value}")
    return result


def _optional_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_text(value: Decimal) -> str:
    return str(value)


def _number_text(value: Decimal) -> int | str:
    return int(value) if value == value.to_integral_value() else str(value)


if __name__ == "__main__":
    main()
