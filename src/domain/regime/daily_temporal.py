from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class DailyRegimeEpisode:
    anchor_at: datetime
    feature_start_at: datetime
    outcome_start_at: datetime
    outcome_end_at: datetime

    def __post_init__(self) -> None:
        timestamps = (
            self.anchor_at,
            self.feature_start_at,
            self.outcome_start_at,
            self.outcome_end_at,
        )
        if any(value.tzinfo is not timezone.utc for value in timestamps):
            raise ValueError("daily episode timestamps must use canonical UTC")
        if not _is_midnight_utc(self.anchor_at):
            raise ValueError("daily anchor must be 00:00 UTC")
        if self.feature_start_at != self.anchor_at - timedelta(days=3):
            raise ValueError("daily feature window must be exactly three days")
        if self.outcome_start_at != self.anchor_at:
            raise ValueError("daily outcome must start at the anchor")
        if self.outcome_end_at != self.anchor_at + timedelta(days=1):
            raise ValueError("daily outcome must be exactly one day")


def build_daily_regime_episodes(
    start_at: datetime,
    end_at: datetime,
) -> tuple[DailyRegimeEpisode, ...]:
    if not _is_midnight_utc(start_at) or not _is_midnight_utc(end_at):
        raise ValueError("daily episode bounds must be canonical midnight UTC")
    if end_at <= start_at:
        raise ValueError("daily episode end must be after start")
    if end_at - start_at < timedelta(days=4):
        raise ValueError("daily episode coverage must span at least four days")

    episodes = []
    anchor_at = start_at + timedelta(days=3)
    while anchor_at < end_at:
        episodes.append(
            DailyRegimeEpisode(
                anchor_at=anchor_at,
                feature_start_at=anchor_at - timedelta(days=3),
                outcome_start_at=anchor_at,
                outcome_end_at=anchor_at + timedelta(days=1),
            )
        )
        anchor_at += timedelta(days=1)
    return tuple(episodes)


def _is_midnight_utc(value: datetime) -> bool:
    return (
        value.tzinfo is timezone.utc
        and value.hour == 0
        and value.minute == 0
        and value.second == 0
        and value.microsecond == 0
    )


__all__ = ["DailyRegimeEpisode", "build_daily_regime_episodes"]
