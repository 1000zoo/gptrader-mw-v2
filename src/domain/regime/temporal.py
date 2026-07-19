from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class UtcInterval:
    start_at: datetime
    end_at: datetime

    def __post_init__(self) -> None:
        if not _is_canonical_utc(self.start_at) or not _is_canonical_utc(self.end_at):
            raise ValueError("interval timestamps must be UTC")
        if self.end_at <= self.start_at:
            raise ValueError("interval end must be after start")


@dataclass(frozen=True)
class WeeklyEpisode:
    anchor_at: datetime
    feature_start_at: datetime
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class RegimeWalkForwardFold:
    cluster_fit: UtcInterval
    mapping_fit: UtcInterval
    validation: UtcInterval
    test: UtcInterval

    def __post_init__(self) -> None:
        intervals = (self.cluster_fit, self.mapping_fit, self.validation, self.test)
        for earlier, later in zip(intervals, intervals[1:]):
            if later.start_at - earlier.end_at < timedelta(days=7):
                raise ValueError("every fold boundary requires a seven-day purge")


def is_regime_boundary(value: datetime) -> bool:
    return (
        _is_canonical_utc(value)
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
        and value.hour % 4 == 0
    )


def feature_window(anchor_at: datetime) -> tuple[datetime, datetime]:
    if not is_regime_boundary(anchor_at):
        raise ValueError("anchor must be a four-hour UTC boundary")
    return anchor_at - timedelta(days=7), anchor_at


def build_weekly_episodes(start_at: datetime, end_at: datetime) -> list[WeeklyEpisode]:
    if not _is_monday_midnight_utc(start_at) or not _is_monday_midnight_utc(end_at):
        raise ValueError("episode endpoints must be Monday 00:00 UTC")
    if end_at <= start_at:
        raise ValueError("episode end must be after start")

    episode_duration = timedelta(days=7)
    range_duration = end_at - start_at
    if range_duration % episode_duration:
        raise ValueError("episode range must be a multiple of seven days")

    episodes = []
    anchor_at = start_at
    while anchor_at < end_at:
        episodes.append(
            WeeklyEpisode(
                anchor_at=anchor_at,
                feature_start_at=anchor_at - episode_duration,
                start_at=anchor_at,
                end_at=anchor_at + episode_duration,
            )
        )
        anchor_at += episode_duration
    return episodes


def _is_monday_midnight_utc(value: datetime) -> bool:
    return (
        _is_canonical_utc(value)
        and value.weekday() == 0
        and value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
    )


def _is_canonical_utc(value: datetime) -> bool:
    return value.tzinfo is timezone.utc
