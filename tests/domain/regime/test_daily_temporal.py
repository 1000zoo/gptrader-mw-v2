from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.domain.regime.daily_temporal import DailyRegimeEpisode, build_daily_regime_episodes


START = datetime(2024, 7, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_build_daily_regime_episodes_reserves_first_three_days_and_727_outcomes():
    episodes = build_daily_regime_episodes(START, END)

    assert isinstance(episodes, tuple)
    assert len(episodes) == 727
    assert episodes[0] == DailyRegimeEpisode(
        anchor_at=datetime(2024, 7, 4, tzinfo=timezone.utc),
        feature_start_at=START,
        outcome_start_at=datetime(2024, 7, 4, tzinfo=timezone.utc),
        outcome_end_at=datetime(2024, 7, 5, tzinfo=timezone.utc),
    )
    assert episodes[-1] == DailyRegimeEpisode(
        anchor_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        feature_start_at=datetime(2026, 6, 27, tzinfo=timezone.utc),
        outcome_start_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        outcome_end_at=END,
    )


def test_daily_episode_windows_are_adjacent_outcomes_and_two_day_overlapping_features():
    episodes = build_daily_regime_episodes(START, END)

    for earlier, later in zip(episodes, episodes[1:]):
        assert later.anchor_at - earlier.anchor_at == timedelta(days=1)
        assert later.outcome_start_at == earlier.outcome_end_at
        assert later.feature_start_at - earlier.feature_start_at == timedelta(days=1)
        assert earlier.anchor_at - later.feature_start_at == timedelta(days=2)


def test_daily_episode_is_immutable():
    episode = build_daily_regime_episodes(START, END)[0]

    with pytest.raises(FrozenInstanceError):
        episode.anchor_at = END


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"anchor_at": datetime(2024, 7, 4)}, "canonical UTC"),
        (
            {"feature_start_at": datetime(2024, 7, 1, tzinfo=ZoneInfo("Europe/London"))},
            "canonical UTC",
        ),
        ({"anchor_at": datetime(2024, 7, 4, 1, tzinfo=timezone.utc)}, "00:00 UTC"),
        ({"feature_start_at": START + timedelta(days=1)}, "exactly three days"),
        ({"outcome_start_at": datetime(2024, 7, 5, tzinfo=timezone.utc)}, "start at the anchor"),
        ({"outcome_end_at": datetime(2024, 7, 6, tzinfo=timezone.utc)}, "exactly one day"),
    ],
)
def test_daily_episode_rejects_contract_violations(changes, message):
    fields = {
        "anchor_at": datetime(2024, 7, 4, tzinfo=timezone.utc),
        "feature_start_at": START,
        "outcome_start_at": datetime(2024, 7, 4, tzinfo=timezone.utc),
        "outcome_end_at": datetime(2024, 7, 5, tzinfo=timezone.utc),
    }
    fields.update(changes)

    with pytest.raises(ValueError, match=message):
        DailyRegimeEpisode(**fields)


@pytest.mark.parametrize(
    ("start_at", "end_at"),
    [
        (datetime(2024, 7, 1), END),
        (START, datetime(2026, 7, 1)),
        (datetime(2024, 7, 1, 1, tzinfo=timezone.utc), END),
        (START, datetime(2026, 7, 1, 0, 0, 1, tzinfo=timezone.utc)),
        (datetime(2024, 7, 1, tzinfo=ZoneInfo("Europe/London")), END),
    ],
)
def test_build_daily_regime_episodes_requires_canonical_midnight_utc_bounds(start_at, end_at):
    with pytest.raises(ValueError, match="midnight UTC"):
        build_daily_regime_episodes(start_at, end_at)


@pytest.mark.parametrize(
    ("start_at", "end_at", "message"),
    [
        (START, START, "after start"),
        (END, START, "after start"),
        (START, START + timedelta(days=3), "at least four days"),
    ],
)
def test_build_daily_regime_episodes_rejects_unordered_or_insufficient_coverage(
    start_at, end_at, message
):
    with pytest.raises(ValueError, match=message):
        build_daily_regime_episodes(start_at, end_at)
