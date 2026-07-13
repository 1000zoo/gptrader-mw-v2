from __future__ import annotations

import argparse
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence


def evaluate_payload(payload: Mapping[str, object]) -> dict[str, object]:
    series = _candidate_series(payload)
    months = sorted({month for monthly in series.values() for month in monthly})

    return {
        "candidate_count": len(series),
        "months": months,
        "candidate_series": _json_candidate_series(series),
        "candidate_summaries": _candidate_summaries(series),
        "correlations": _correlations(series),
        "portfolio_monthly_returns": _portfolio_monthly_returns(series, months),
        "portfolio_summary": _portfolio_summary(series, months),
    }


def _candidate_series(payload: Mapping[str, object]) -> dict[str, dict[str, Decimal]]:
    if "candidate_series" in payload:
        raw_series = payload["candidate_series"]
        if not isinstance(raw_series, Mapping):
            raise ValueError("candidate_series must be an object keyed by candidate id")
        return {
            str(candidate_id): {
                str(month): _decimal(return_ratio)
                for month, return_ratio in _monthly_items(monthly_returns)
            }
            for candidate_id, monthly_returns in raw_series.items()
        }

    return _candidate_series_from_folds(payload)


def _monthly_items(monthly_returns: object) -> Sequence[tuple[object, object]]:
    if isinstance(monthly_returns, Mapping):
        return tuple(monthly_returns.items())
    if isinstance(monthly_returns, Sequence) and not isinstance(monthly_returns, (str, bytes)):
        rows = []
        for row in monthly_returns:
            if not isinstance(row, Mapping):
                raise ValueError("candidate monthly return rows must be objects")
            rows.append((row["month"], row["return_ratio"]))
        return tuple(rows)
    raise ValueError("candidate monthly returns must be an object or list of rows")


def _candidate_series_from_folds(payload: Mapping[str, object]) -> dict[str, dict[str, Decimal]]:
    folds = payload.get("folds")
    if not isinstance(folds, Sequence) or isinstance(folds, (str, bytes)):
        raise ValueError("payload must include candidate_series or folds")

    series: dict[str, dict[str, Decimal]] = {}
    for fold in folds:
        if not isinstance(fold, Mapping):
            raise ValueError("fold rows must be objects")
        month = _fold_month(fold)
        results = fold.get("results")
        if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
            raise ValueError("fold results must be a list")
        for result in results:
            if not isinstance(result, Mapping):
                raise ValueError("fold result rows must be objects")
            candidate_id = str(result.get("candidate_id") or _candidate_id_from_candidate(result))
            if not candidate_id:
                raise ValueError("fold result is missing candidate_id")
            if "return_ratio" not in result:
                raise ValueError(f"fold result for {candidate_id} is missing return_ratio")
            series.setdefault(candidate_id, {})[month] = _decimal(result["return_ratio"])
    return series


def _candidate_id_from_candidate(result: Mapping[str, object]) -> object:
    candidate = result.get("candidate")
    if isinstance(candidate, Mapping):
        return candidate.get("candidate_id", "")
    return ""


def _fold_month(fold: Mapping[str, object]) -> str:
    for key in ("test_start_at", "start_at"):
        value = fold.get(key)
        if value:
            return str(value)[:7]
    test_period = fold.get("test_period")
    if isinstance(test_period, Mapping) and test_period.get("start_at"):
        return str(test_period["start_at"])[:7]
    raise ValueError("fold is missing test month fields")


def _json_candidate_series(series: Mapping[str, Mapping[str, Decimal]]) -> dict[str, list[dict[str, str]]]:
    return {
        candidate_id: [
            {"month": month, "return_ratio": _decimal_text(return_ratio)}
            for month, return_ratio in sorted(monthly_returns.items())
        ]
        for candidate_id, monthly_returns in sorted(series.items())
    }


def _candidate_summaries(series: Mapping[str, Mapping[str, Decimal]]) -> list[dict[str, object]]:
    rows = []
    for candidate_id, monthly_returns in sorted(series.items()):
        returns = list(monthly_returns.values())
        rows.append(
            {
                "candidate_id": candidate_id,
                "month_count": len(returns),
                "average_monthly_return": _decimal_text(_average(returns)),
                "min_monthly_return": _decimal_text(min(returns)) if returns else None,
                "worst_monthly_drawdown_proxy": _decimal_text(min(returns)) if returns else None,
                "positive_month_count": sum(1 for value in returns if value > 0),
                "positive_month_ratio": _decimal_text(_positive_ratio(returns)),
            }
        )
    return rows


def _correlations(series: Mapping[str, Mapping[str, Decimal]]) -> list[dict[str, object]]:
    rows = []
    candidate_ids = sorted(series)
    for left_index, candidate_a in enumerate(candidate_ids):
        for candidate_b in candidate_ids[left_index + 1 :]:
            common_months = sorted(set(series[candidate_a]) & set(series[candidate_b]))
            left = [series[candidate_a][month] for month in common_months]
            right = [series[candidate_b][month] for month in common_months]
            rows.append(
                {
                    "candidate_a": candidate_a,
                    "candidate_b": candidate_b,
                    "correlation": _float_text(_pearson(left, right)),
                }
            )
    return rows


def _portfolio_monthly_returns(
    series: Mapping[str, Mapping[str, Decimal]], months: Sequence[str]
) -> list[dict[str, str]]:
    rows = []
    for month in months:
        returns = [monthly_returns[month] for monthly_returns in series.values() if month in monthly_returns]
        if returns:
            rows.append({"month": month, "return_ratio": _decimal_text(_average(returns))})
    return rows


def _portfolio_summary(series: Mapping[str, Mapping[str, Decimal]], months: Sequence[str]) -> dict[str, object]:
    returns = [
        _average([monthly_returns[month] for monthly_returns in series.values() if month in monthly_returns])
        for month in months
        if any(month in monthly_returns for monthly_returns in series.values())
    ]
    return {
        "average_monthly_return": _decimal_text(_average(returns)),
        "min_monthly_return": _decimal_text(min(returns)) if returns else None,
        "worst_monthly_drawdown_proxy": _decimal_text(min(returns)) if returns else None,
        "positive_month_ratio": _decimal_text(_positive_ratio(returns)),
        "positive_month_count": sum(1 for value in returns if value > 0),
        "month_count": len(returns),
    }


def _average(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return sum(values, Decimal("0")) / Decimal(len(values))


def _positive_ratio(values: Sequence[Decimal]) -> Decimal:
    if not values:
        return Decimal("0")
    return Decimal(sum(1 for value in values if value > 0)) / Decimal(len(values))


def _pearson(left: Sequence[Decimal], right: Sequence[Decimal]) -> float | None:
    if len(left) < 2 or len(right) < 2:
        return None
    left_values = [float(value) for value in left]
    right_values = [float(value) for value in right]
    left_mean = sum(left_values) / len(left_values)
    right_mean = sum(right_values) / len(right_values)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left_values, right_values)
    )
    left_variance = sum((value - left_mean) ** 2 for value in left_values)
    right_variance = sum((value - right_mean) ** 2 for value in right_values)
    denominator = math.sqrt(left_variance * right_variance)
    if denominator == 0:
        return None
    return numerator / denominator


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _decimal_text(value: Decimal) -> str:
    return str(value)


def _float_text(value: float | None) -> str | None:
    if value is None:
        return None
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate walk-forward candidate portfolio correlations.")
    parser.add_argument("input_path", type=Path)
    parser.add_argument("--output-path", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input_path.read_text(encoding="utf-8"))
    result = evaluate_payload(payload)
    output = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_path:
        args.output_path.parent.mkdir(parents=True, exist_ok=True)
        args.output_path.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)


if __name__ == "__main__":
    main()
