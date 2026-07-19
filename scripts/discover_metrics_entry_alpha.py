from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.infrastructure.exchange.binance.research_data.historical_feature_loader import (
    validate_cache_pair,
)


UTC = timezone.utc
DEFAULT_COST = 0.0012


@dataclass(frozen=True)
class ForwardOutcome:
    gross_return: float
    net_return: float
    won: bool

    @classmethod
    def from_prices(
        cls,
        *,
        direction: int,
        entry_price: float,
        future_price: float,
        round_trip_cost: float,
    ) -> "ForwardOutcome":
        if direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")
        if entry_price <= 0 or future_price <= 0:
            raise ValueError("prices must be positive")
        gross = direction * (future_price / entry_price - 1.0)
        net = gross - round_trip_cost
        return cls(gross, net, net > 0)


@dataclass(frozen=True)
class Condition:
    feature: str
    operator: str
    threshold: float

    def matches(self, features: Mapping[str, float]) -> bool:
        value = features.get(self.feature)
        if value is None or not math.isfinite(value):
            return False
        if self.operator == ">=":
            return value >= self.threshold
        if self.operator == "<=":
            return value <= self.threshold
        raise ValueError(f"unsupported operator: {self.operator}")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    direction: int
    conditions: tuple[Condition, ...]

    def matches(self, features: Mapping[str, float]) -> bool:
        return all(condition.matches(features) for condition in self.conditions)


@dataclass(frozen=True)
class Observation:
    measured_at: datetime
    close: float
    features: Mapping[str, float]


@dataclass(frozen=True)
class RuleMonthResult:
    rule_id: str
    horizon_minutes: int
    month: str
    signal_count: int
    win_rate: float
    average_net_return: float
    total_net_return: float


def candidate_rules() -> tuple[Rule, ...]:
    rules: list[Rule] = []

    def add(name: str, direction: int, *conditions: Condition) -> None:
        rules.append(Rule(name, direction, tuple(conditions)))

    taker_high = (1.10, 1.25, 1.50, 2.00)
    taker_low = (0.90, 0.80, 0.67, 0.50)
    for threshold in taker_high:
        condition = Condition("taker_long_short_volume_ratio", ">=", threshold)
        add(f"taker-high-{threshold:g}-continuation", 1, condition)
        add(f"taker-high-{threshold:g}-reversal", -1, condition)
    for threshold in taker_low:
        condition = Condition("taker_long_short_volume_ratio", "<=", threshold)
        add(f"taker-low-{threshold:g}-continuation", -1, condition)
        add(f"taker-low-{threshold:g}-reversal", 1, condition)

    oi_thresholds = (0.0005, 0.0010, 0.0020, 0.0040)
    price_thresholds = (0.0010, 0.0020, 0.0030)
    for oi in oi_thresholds:
        for price in price_thresholds:
            for taker in (1.10, 1.25):
                common = (
                    Condition("open_interest_change_ratio_5m", ">=", oi),
                    Condition("price_return_5m", ">=", price),
                    Condition("taker_long_short_volume_ratio", ">=", taker),
                )
                add(f"oi-up-{oi:g}-price-up-{price:g}-taker-{taker:g}-cont", 1, *common)
                add(f"oi-up-{oi:g}-price-up-{price:g}-taker-{taker:g}-fade", -1, *common)
            for taker in (0.90, 0.80):
                common = (
                    Condition("open_interest_change_ratio_5m", ">=", oi),
                    Condition("price_return_5m", "<=", -price),
                    Condition("taker_long_short_volume_ratio", "<=", taker),
                )
                add(f"oi-up-{oi:g}-price-down-{price:g}-taker-{taker:g}-cont", -1, *common)
                add(f"oi-up-{oi:g}-price-down-{price:g}-taker-{taker:g}-fade", 1, *common)

            contraction = Condition("open_interest_change_ratio_5m", "<=", -oi)
            price_up = Condition("price_return_5m", ">=", price)
            price_down = Condition("price_return_5m", "<=", -price)
            add(f"oi-down-{oi:g}-price-up-{price:g}-fade", -1, contraction, price_up)
            add(f"oi-down-{oi:g}-price-up-{price:g}-cont", 1, contraction, price_up)
            add(f"oi-down-{oi:g}-price-down-{price:g}-fade", 1, contraction, price_down)
            add(f"oi-down-{oi:g}-price-down-{price:g}-cont", -1, contraction, price_down)

    for low in (0.80, 0.90):
        for taker in (1.10, 1.25):
            add(
                f"crowded-short-{low:g}-taker-{taker:g}-reversal",
                1,
                Condition("top_trader_position_long_short_ratio", "<=", low),
                Condition("global_long_short_ratio", "<=", low),
                Condition("taker_long_short_volume_ratio", ">=", taker),
            )
    for high in (1.15, 1.30, 1.50):
        for taker in (0.90, 0.80):
            add(
                f"crowded-long-{high:g}-taker-{taker:g}-reversal",
                -1,
                Condition("top_trader_position_long_short_ratio", ">=", high),
                Condition("global_long_short_ratio", ">=", high),
                Condition("taker_long_short_volume_ratio", "<=", taker),
            )

    for change in (0.02, 0.05, 0.10):
        add(
            f"global-ratio-up-{change:g}-continuation",
            1,
            Condition("global_long_short_change_5m", ">=", change),
        )
        add(
            f"global-ratio-up-{change:g}-reversal",
            -1,
            Condition("global_long_short_change_5m", ">=", change),
        )
        add(
            f"global-ratio-down-{change:g}-continuation",
            -1,
            Condition("global_long_short_change_5m", "<=", -change),
        )
        add(
            f"global-ratio-down-{change:g}-reversal",
            1,
            Condition("global_long_short_change_5m", "<=", -change),
        )
    return tuple(rules)


def load_observations(path: Path) -> tuple[Observation, ...]:
    path = Path(path)
    manifest_path = path.with_suffix(".manifest.json")
    if not validate_cache_pair(path, manifest_path):
        raise ValueError("feature cache and manifest failed validation")
    closes: dict[datetime, float] = {}
    metrics_rows: list[tuple[datetime, float, dict[str, float]]] = []
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            measured_at = datetime.fromisoformat(payload["measured_at"]).astimezone(UTC)
            if measured_at in closes:
                raise ValueError("duplicate feature-cache measured_at")
            features = payload["features"]
            close = float(features["close"]["value"])
            closes[measured_at] = close
            current_metrics = {
                name: float(value["value"])
                for name, value in features.items()
                if value["source"] == "metrics"
                and datetime.fromisoformat(value["available_at"]).astimezone(UTC)
                == measured_at
            }
            if current_metrics:
                metrics_rows.append((measured_at, close, current_metrics))

    observations = []
    for measured_at, close, features in metrics_rows:
        five_minutes_ago = measured_at.timestamp() - 300
        previous_at = datetime.fromtimestamp(five_minutes_ago, tz=UTC)
        previous = closes.get(previous_at)
        if previous is not None and previous > 0:
            features["price_return_5m"] = close / previous - 1.0
        observations.append(Observation(measured_at, close, features))
    return tuple(observations)


def evaluate_rules(
    observations: Sequence[Observation],
    *,
    rules: Sequence[Rule],
    horizons: Sequence[int] = (5, 15, 30, 60),
    round_trip_cost: float = DEFAULT_COST,
) -> tuple[RuleMonthResult, ...]:
    close_by_time = {observation.measured_at: observation.close for observation in observations}
    aggregates: dict[tuple[str, int, str], list[float]] = defaultdict(list)
    for observation in observations:
        matched_rules = tuple(
            rule for rule in rules if rule.matches(observation.features)
        )
        if not matched_rules:
            continue
        for horizon in horizons:
            future_at = datetime.fromtimestamp(
                observation.measured_at.timestamp() + horizon * 60,
                tz=UTC,
            )
            future = close_by_time.get(future_at)
            if future is None:
                continue
            month = observation.measured_at.strftime("%Y-%m")
            if future_at.strftime("%Y-%m") != month:
                continue
            for rule in matched_rules:
                outcome = ForwardOutcome.from_prices(
                    direction=rule.direction,
                    entry_price=observation.close,
                    future_price=future,
                    round_trip_cost=round_trip_cost,
                )
                aggregates[(rule.rule_id, horizon, month)].append(outcome.net_return)
    results = []
    for (rule_id, horizon, month), returns in sorted(aggregates.items()):
        results.append(
            RuleMonthResult(
                rule_id=rule_id,
                horizon_minutes=horizon,
                month=month,
                signal_count=len(returns),
                win_rate=sum(value > 0 for value in returns) / len(returns),
                average_net_return=sum(returns) / len(returns),
                total_net_return=sum(returns),
            )
        )
    return tuple(results)


def select_walk_forward(
    rows: Sequence[RuleMonthResult],
    *,
    test_months: Sequence[str],
    train_months: int = 6,
    top_k: int = 5,
    min_train_signals: int = 100,
    min_positive_train_months: int = 4,
) -> list[dict[str, object]]:
    by_key = {(row.rule_id, row.horizon_minutes, row.month): row for row in rows}
    candidates = sorted({(row.rule_id, row.horizon_minutes) for row in rows})
    folds = []
    for test_month in test_months:
        train = _previous_months(test_month, train_months)
        eligible = []
        for rule_id, horizon in candidates:
            train_rows = [
                by_key[(rule_id, horizon, month)]
                for month in train
                if (rule_id, horizon, month) in by_key
            ]
            signal_count = sum(row.signal_count for row in train_rows)
            positive_months = sum(row.average_net_return > 0 for row in train_rows)
            if (
                len(train_rows) != train_months
                or signal_count < min_train_signals
                or positive_months < min_positive_train_months
            ):
                continue
            average = (
                sum(row.average_net_return * row.signal_count for row in train_rows)
                / signal_count
            )
            if average <= 0:
                continue
            eligible.append((average, positive_months, signal_count, rule_id, horizon))
        eligible.sort(reverse=True)
        selected = eligible[:top_k]
        oos = [
            by_key.get((rule_id, horizon, test_month))
            for _, _, _, rule_id, horizon in selected
        ]
        available = [row for row in oos if row is not None]
        folds.append(
            {
                "test_month": test_month,
                "selected_rule_ids": [
                    f"{rule_id}@{horizon}m"
                    for _, _, _, rule_id, horizon in selected
                ],
                "oos_average_net_return": (
                    sum(row.average_net_return for row in available) / len(available)
                    if available
                    else 0.0
                ),
                "oos_positive_rules": sum(
                    row.average_net_return > 0 for row in available
                ),
                "selection_evidence": [
                    {
                        "rule_id": f"{rule_id}@{horizon}m",
                        "train_average_net_return": average,
                        "positive_train_months": positive,
                        "train_signal_count": count,
                    }
                    for average, positive, count, rule_id, horizon in selected
                ],
            }
        )
    return folds


def _previous_months(month: str, count: int) -> tuple[str, ...]:
    year, month_number = (int(part) for part in month.split("-"))
    cursor = year * 12 + month_number - 1
    values = []
    for offset in range(count, 0, -1):
        value = cursor - offset
        values.append(f"{value // 12:04d}-{value % 12 + 1:02d}")
    return tuple(values)


def _result_payload(
    rows: Sequence[RuleMonthResult],
    folds: Sequence[Mapping[str, object]],
    *,
    feature_cache_path: Path,
    observations: Sequence[Observation],
    rules: Sequence[Rule],
    horizons: Sequence[int],
    selection: Mapping[str, int],
) -> dict[str, object]:
    return {
        "method": "train-only metrics forward-return screen",
        "cost_model": {"round_trip_price_return": DEFAULT_COST},
        "feature_cache": {
            "path": str(feature_cache_path),
            "sha256": _sha256_file(feature_cache_path),
        },
        "observation_count": len(observations),
        "observation_start": observations[0].measured_at.isoformat() if observations else None,
        "observation_end": observations[-1].measured_at.isoformat() if observations else None,
        "horizons_minutes": list(horizons),
        "selection": dict(selection),
        "rule_count": len(rules),
        "rules": [asdict(rule) for rule in rules],
        "monthly_result_count": len(rows),
        "monthly_results": [asdict(row) for row in rows],
        "folds": list(folds),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _markdown(payload: Mapping[str, object]) -> str:
    lines = [
        "# Binance Metrics Entry Alpha Screen",
        "",
        "- Selection: trailing 6 months only",
        f"- Rules: `{payload['rule_count']}`",
        f"- Round-trip cost: `{DEFAULT_COST}`",
        "",
        "| Test month | Selected | OOS average net | Positive rules |",
        "|---|---|---:|---:|",
    ]
    for fold in payload["folds"]:
        selected = ", ".join(fold["selected_rule_ids"]) or "cash"
        lines.append(
            f"| {fold['test_month']} | {selected} | "
            f"{fold['oos_average_net_return']:.6f} | {fold['oos_positive_rules']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--payload-path", type=Path, required=True)
    parser.add_argument("--summary-path", type=Path, required=True)
    parser.add_argument("--min-train-signals", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    observations = load_observations(args.feature_cache)
    rules = candidate_rules()
    horizons = (5, 15, 30, 60)
    rows = evaluate_rules(observations, rules=rules, horizons=horizons)
    selection = {
        "train_months": 6,
        "top_k": args.top_k,
        "min_train_signals": args.min_train_signals,
        "min_positive_train_months": 4,
    }
    folds = select_walk_forward(
        rows,
        test_months=("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"),
        train_months=6,
        top_k=args.top_k,
        min_train_signals=args.min_train_signals,
        min_positive_train_months=4,
    )
    payload = _result_payload(
        rows,
        folds,
        feature_cache_path=args.feature_cache,
        observations=observations,
        rules=rules,
        horizons=horizons,
        selection=selection,
    )
    args.payload_path.parent.mkdir(parents=True, exist_ok=True)
    args.payload_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    args.summary_path.parent.mkdir(parents=True, exist_ok=True)
    args.summary_path.write_text(_markdown(payload), encoding="utf-8")
    print(args.payload_path)
    print(args.summary_path)


if __name__ == "__main__":
    main()
