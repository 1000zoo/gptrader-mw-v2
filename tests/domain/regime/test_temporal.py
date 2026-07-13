from datetime import datetime, timedelta, timezone

import pytest

from src.domain.regime import (
    RegimeWalkForwardFold,
    UtcInterval,
    build_weekly_episodes,
    feature_window,
    is_regime_boundary,
)


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_four_hour_boundary_is_utc_and_excludes_boundary_observation():
    boundary = datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc)

    assert is_regime_boundary(boundary)
    assert not is_regime_boundary(boundary + timedelta(minutes=1))
    assert feature_window(boundary) == (
        datetime(2026, 3, 30, 12, 0, tzinfo=timezone.utc),
        boundary,
    )


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 4, 6, 12),
        datetime(2026, 4, 6, 13, tzinfo=timezone.utc),
        datetime(2026, 4, 6, 12, 0, 1, tzinfo=timezone.utc),
    ],
)
def test_feature_window_rejects_values_that_are_not_four_hour_utc_boundaries(value):
    with pytest.raises(ValueError, match="four-hour UTC boundary"):
        feature_window(value)


def test_utc_interval_requires_utc_timestamps_and_positive_duration():
    with pytest.raises(ValueError, match="timestamps must be UTC"):
        UtcInterval(datetime(2026, 1, 5), dt("2026-01-12"))

    with pytest.raises(ValueError, match="end must be after start"):
        UtcInterval(dt("2026-01-05"), dt("2026-01-05"))


def test_weekly_mapping_episodes_are_non_overlapping_monday_utc():
    episodes = build_weekly_episodes(
        datetime(2026, 1, 5, tzinfo=timezone.utc),
        datetime(2026, 1, 26, tzinfo=timezone.utc),
    )

    assert [(item.start_at, item.end_at) for item in episodes] == [
        (datetime(2026, 1, 5, tzinfo=timezone.utc), datetime(2026, 1, 12, tzinfo=timezone.utc)),
        (datetime(2026, 1, 12, tzinfo=timezone.utc), datetime(2026, 1, 19, tzinfo=timezone.utc)),
        (datetime(2026, 1, 19, tzinfo=timezone.utc), datetime(2026, 1, 26, tzinfo=timezone.utc)),
    ]
    assert [item.anchor_at for item in episodes] == [item.start_at for item in episodes]
    assert [item.feature_start_at for item in episodes] == [
        item.anchor_at - timedelta(days=7) for item in episodes
    ]


@pytest.mark.parametrize(
    ("start_at", "end_at"),
    [
        (datetime(2026, 1, 5), dt("2026-01-12")),
        (dt("2026-01-06"), dt("2026-01-12")),
        (dt("2026-01-05"), datetime(2026, 1, 12, 1, tzinfo=timezone.utc)),
    ],
)
def test_weekly_mapping_episodes_require_monday_midnight_utc_endpoints(start_at, end_at):
    with pytest.raises(ValueError, match="Monday 00:00 UTC"):
        build_weekly_episodes(start_at, end_at)


def test_weekly_mapping_episodes_reject_an_empty_or_reversed_range():
    with pytest.raises(ValueError, match="end must be after start"):
        build_weekly_episodes(dt("2026-01-05"), dt("2026-01-05"))

    with pytest.raises(ValueError, match="end must be after start"):
        build_weekly_episodes(dt("2026-01-12"), dt("2026-01-05"))


def test_fold_rejects_less_than_seven_day_purge():
    with pytest.raises(ValueError, match="seven-day purge"):
        RegimeWalkForwardFold(
            cluster_fit=UtcInterval(dt("2021-01-01"), dt("2025-07-01")),
            mapping_fit=UtcInterval(dt("2025-07-05"), dt("2026-01-05")),
            validation=UtcInterval(dt("2026-01-12"), dt("2026-03-30")),
            test=UtcInterval(dt("2026-04-06"), dt("2026-07-01")),
        )


def test_fold_accepts_exactly_seven_day_purges():
    fold = RegimeWalkForwardFold(
        cluster_fit=UtcInterval(dt("2021-01-01"), dt("2025-07-01")),
        mapping_fit=UtcInterval(dt("2025-07-08"), dt("2026-01-05")),
        validation=UtcInterval(dt("2026-01-12"), dt("2026-03-30")),
        test=UtcInterval(dt("2026-04-06"), dt("2026-07-01")),
    )

    assert fold.test.start_at == dt("2026-04-06")
