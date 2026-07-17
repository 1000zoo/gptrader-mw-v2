"""Immutable, self-verifying phase timelines and bounded daily market slices."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json

from src.domain.market import MarketSnapshot


_FACTORY_TOKEN = object()


def market_snapshot_hash(market: MarketSnapshot) -> str:
    digest = hashlib.sha256()
    for candle in market.candles:
        payload = (
            candle.opened_at.isoformat(), candle.closed_at.isoformat(),
            str(candle.open_price), str(candle.high_price), str(candle.low_price),
            str(candle.close_price), str(candle.volume),
        )
        digest.update(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


@dataclass(frozen=True, init=False)
class VerifiedPhaseMarketTimeline:
    market: MarketSnapshot
    market_data_hash: str
    opened_times: tuple[datetime, ...]
    _factory_token: object
    _proof: tuple[object, ...]

    def __init__(self, *args, **kwargs) -> None:
        raise TypeError("verified phase timelines must be created with from_market")

    @classmethod
    def from_market(cls, market: MarketSnapshot) -> "VerifiedPhaseMarketTimeline":
        if not isinstance(market, MarketSnapshot):
            raise TypeError("verified phase timeline requires a MarketSnapshot")
        if market.timeframe.duration_seconds != 60:
            raise ValueError("verified phase timeline requires canonical 1m candles")
        if any(left.closed_at != right.opened_at for left, right in zip(
            market.candles, market.candles[1:]
        )):
            raise ValueError("verified phase timeline contains a candle gap or overlap")
        instance = object.__new__(cls)
        object.__setattr__(instance, "market", market)
        object.__setattr__(instance, "market_data_hash", market_snapshot_hash(market))
        object.__setattr__(
            instance, "opened_times", tuple(candle.opened_at for candle in market.candles),
        )
        object.__setattr__(instance, "_factory_token", _FACTORY_TOKEN)
        object.__setattr__(instance, "_proof", (
            _FACTORY_TOKEN, id(instance.market), instance.market_data_hash,
            id(instance.opened_times), len(instance.opened_times),
        ))
        return instance

    def _verify_proof(self) -> None:
        expected = (
            _FACTORY_TOKEN, id(self.market), self.market_data_hash,
            id(self.opened_times), len(self.opened_times),
        )
        if self._factory_token is not _FACTORY_TOKEN or self._proof != expected:
            raise ValueError("verified phase timeline factory proof is invalid")

    def daily_slice(
        self, outcome_start_at: datetime, *, warmup_minutes: int,
    ) -> "VerifiedDailyMarketSlice":
        self._verify_proof()
        if outcome_start_at.tzinfo is not timezone.utc or outcome_start_at.time() != datetime.min.time():
            raise ValueError("verified daily slice outcome must be canonical midnight UTC")
        if not isinstance(warmup_minutes, int) or isinstance(warmup_minutes, bool) or warmup_minutes < 0:
            raise ValueError("verified daily slice warmup must be a nonnegative integer")
        context_start = outcome_start_at - timedelta(minutes=warmup_minutes)
        outcome_end = outcome_start_at + timedelta(days=1)
        left = bisect_left(self.opened_times, context_start)
        right = bisect_left(self.opened_times, outcome_end)
        selected = self.market.candles[left:right]
        expected = warmup_minutes + 24 * 60
        if (
            len(selected) != expected or not selected
            or selected[0].opened_at != context_start
            or selected[-1].closed_at != outcome_end
        ):
            raise ValueError("verified phase timeline cannot form the requested daily slice")
        market = MarketSnapshot(selected)
        instance = object.__new__(VerifiedDailyMarketSlice)
        object.__setattr__(instance, "timeline", self)
        object.__setattr__(instance, "market", market)
        object.__setattr__(instance, "outcome_start_at", outcome_start_at)
        object.__setattr__(instance, "context_start_at", context_start)
        object.__setattr__(instance, "outcome_end_at", outcome_end)
        object.__setattr__(instance, "warmup_minutes", warmup_minutes)
        object.__setattr__(instance, "slice_hash", market_snapshot_hash(market))
        object.__setattr__(instance, "_factory_token", _FACTORY_TOKEN)
        object.__setattr__(instance, "_proof", (
            _FACTORY_TOKEN, id(self), id(market), instance.slice_hash,
            outcome_start_at, context_start, outcome_end, warmup_minutes,
        ))
        return instance


@dataclass(frozen=True, init=False)
class VerifiedDailyMarketSlice:
    timeline: VerifiedPhaseMarketTimeline
    market: MarketSnapshot
    outcome_start_at: datetime
    context_start_at: datetime
    outcome_end_at: datetime
    warmup_minutes: int
    slice_hash: str
    _factory_token: object
    _proof: tuple[object, ...]

    def __init__(self, *args, **kwargs) -> None:
        raise TypeError("verified daily slices must be created by a verified phase timeline")

    def verify(
        self, *, outcome_start_at: datetime, minimum_context_start_at: datetime,
    ) -> MarketSnapshot:
        expected_proof = (
            _FACTORY_TOKEN, id(self.timeline), id(self.market), self.slice_hash,
            self.outcome_start_at, self.context_start_at,
            self.outcome_end_at, self.warmup_minutes,
        )
        if self._factory_token is not _FACTORY_TOKEN or self._proof != expected_proof:
            raise ValueError("verified daily slice factory proof is invalid")
        self.timeline._verify_proof()
        if (
            self.outcome_start_at != outcome_start_at
            or self.outcome_end_at != outcome_start_at + timedelta(days=1)
            or self.context_start_at > minimum_context_start_at
            or self.context_start_at != outcome_start_at - timedelta(minutes=self.warmup_minutes)
        ):
            raise ValueError("verified daily slice bounds do not cover the requested context")
        if market_snapshot_hash(self.market) != self.slice_hash:
            raise ValueError("verified daily slice hash mismatch")
        left = bisect_left(self.timeline.opened_times, self.context_start_at)
        right = bisect_left(self.timeline.opened_times, self.outcome_end_at)
        if self.timeline.market.candles[left:right] != self.market.candles:
            raise ValueError("verified daily slice is not the bound phase source range")
        return self.market


__all__ = [
    "VerifiedDailyMarketSlice", "VerifiedPhaseMarketTimeline", "market_snapshot_hash",
]
