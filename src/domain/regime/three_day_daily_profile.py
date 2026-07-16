from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math
from types import MappingProxyType
from typing import Mapping

from src.domain.regime.temporal import UtcInterval


PROFILE_ID = "three-day-daily-k4-v1"
RANDOM_SEED = 20260714
MODEL_TYPE = "gmm"
COVARIANCE_TYPE = "diag"
CLUSTER_COUNT = 4
REGULARIZATION = 1e-6
BOOTSTRAP_BLOCK_DAYS = 7
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_CONFIDENCE = 0.95
MIN_EPISODES = 30
MIN_CALENDAR_MONTHS = 3
MIN_CLOSED_TRADES = 30


@dataclass(frozen=True)
class DailyRiskPolicy:
    minimum_worst_seven_day_return_ratio: Decimal
    minimum_expected_shortfall_10_ratio: Decimal
    maximum_drawdown_ratio: Decimal
    maximum_top_episode_profit_share: Decimal
    maximum_top_five_trade_profit_share: Decimal

    def __post_init__(self) -> None:
        values = (
            self.minimum_worst_seven_day_return_ratio,
            self.minimum_expected_shortfall_10_ratio,
            self.maximum_drawdown_ratio,
            self.maximum_top_episode_profit_share,
            self.maximum_top_five_trade_profit_share,
        )
        if any(not isinstance(value, Decimal) or not value.is_finite() for value in values):
            raise ValueError("risk policy values must be finite Decimals")
        if self.minimum_worst_seven_day_return_ratio > 0:
            raise ValueError("minimum worst seven-day return ratio cannot be positive")
        if self.minimum_expected_shortfall_10_ratio > 0:
            raise ValueError("minimum expected shortfall ratio cannot be positive")
        if any(
            not Decimal(0) <= value <= Decimal(1)
            for value in (
                self.maximum_drawdown_ratio,
                self.maximum_top_episode_profit_share,
                self.maximum_top_five_trade_profit_share,
            )
        ):
            raise ValueError("maximum risk and concentration ratios must be between zero and one")

    def canonical_payload(self) -> dict[str, str]:
        return {
            "minimum_worst_seven_day_return_ratio": str(
                self.minimum_worst_seven_day_return_ratio
            ),
            "minimum_expected_shortfall_10_ratio": str(
                self.minimum_expected_shortfall_10_ratio
            ),
            "maximum_drawdown_ratio": str(self.maximum_drawdown_ratio),
            "maximum_top_episode_profit_share": str(
                self.maximum_top_episode_profit_share
            ),
            "maximum_top_five_trade_profit_share": str(
                self.maximum_top_five_trade_profit_share
            ),
        }


STRICT_RISK_POLICY = DailyRiskPolicy(
    minimum_worst_seven_day_return_ratio=Decimal("-0.03"),
    minimum_expected_shortfall_10_ratio=Decimal("-0.01"),
    maximum_drawdown_ratio=Decimal("0.10"),
    maximum_top_episode_profit_share=Decimal("0.40"),
    maximum_top_five_trade_profit_share=Decimal("0.60"),
)
SENSITIVITY_POLICIES = MappingProxyType(
    {
        "tighter": DailyRiskPolicy(
            Decimal("-0.02"),
            Decimal("-0.0075"),
            Decimal("0.075"),
            Decimal("0.35"),
            Decimal("0.55"),
        ),
        "looser": DailyRiskPolicy(
            Decimal("-0.04"),
            Decimal("-0.015"),
            Decimal("0.125"),
            Decimal("0.45"),
            Decimal("0.65"),
        ),
    }
)


@dataclass(frozen=True)
class ThreeDayDailyWalkForwardFold:
    cluster_fit: UtcInterval
    mapping_fit: UtcInterval
    validation: UtcInterval
    test: UtcInterval

    def __post_init__(self) -> None:
        intervals = (self.cluster_fit, self.mapping_fit, self.validation, self.test)
        if any(not isinstance(interval, UtcInterval) for interval in intervals):
            raise ValueError("fold phases must be UTC intervals")
        if any(
            not _is_midnight_utc(bound)
            for interval in intervals
            for bound in (interval.start_at, interval.end_at)
        ):
            raise ValueError("fold boundaries must be canonical midnight UTC")
        if any(later.start_at < earlier.end_at for earlier, later in zip(intervals, intervals[1:])):
            raise ValueError("fold phases must be non-overlapping and ordered")
        if self.mapping_fit.start_at - self.cluster_fit.end_at < timedelta(days=7):
            raise ValueError("Cluster Fit boundary requires a seven-day purge")
        if any(
            later.start_at - earlier.end_at < timedelta(days=3)
            for earlier, later in (
                (self.mapping_fit, self.validation),
                (self.validation, self.test),
            )
        ):
            raise ValueError("outcome-bearing phases require a three-day purge")

    @classmethod
    def default(cls) -> "ThreeDayDailyWalkForwardFold":
        return cls(
            cluster_fit=UtcInterval(_utc(2021, 1, 1), _utc(2025, 6, 30)),
            mapping_fit=UtcInterval(_utc(2025, 7, 7), _utc(2026, 1, 1)),
            validation=UtcInterval(_utc(2026, 1, 4), _utc(2026, 4, 1)),
            test=UtcInterval(_utc(2026, 4, 4), _utc(2026, 7, 1)),
        )


@dataclass(frozen=True)
class ThreeDayDailyResearchProfile:
    profile_id: str = PROFILE_ID
    random_seed: int = RANDOM_SEED
    model_type: str = MODEL_TYPE
    covariance_type: str = COVARIANCE_TYPE
    cluster_count: int = CLUSTER_COUNT
    regularization: float = REGULARIZATION
    feature_window_days: int = 3
    outcome_window_days: int = 1
    bootstrap_block_days: int = BOOTSTRAP_BLOCK_DAYS
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES
    bootstrap_confidence: float = BOOTSTRAP_CONFIDENCE
    minimum_episodes: int = MIN_EPISODES
    minimum_calendar_months: int = MIN_CALENDAR_MONTHS
    minimum_closed_trades: int = MIN_CLOSED_TRADES
    strict_risk_policy: DailyRiskPolicy = STRICT_RISK_POLICY
    sensitivity_policies: Mapping[str, DailyRiskPolicy] = field(
        default_factory=lambda: SENSITIVITY_POLICIES
    )
    fold: ThreeDayDailyWalkForwardFold = field(
        default_factory=ThreeDayDailyWalkForwardFold.default
    )

    def __post_init__(self) -> None:
        if self.profile_id != PROFILE_ID:
            raise ValueError("unsupported research profile id")
        if self.model_type != MODEL_TYPE:
            raise ValueError("research profile requires GMM")
        if self.covariance_type != COVARIANCE_TYPE:
            raise ValueError("research profile requires diagonal covariance")
        if self.cluster_count != CLUSTER_COUNT:
            raise ValueError("research profile requires exactly four clusters")
        if self.feature_window_days != 3:
            raise ValueError("feature window must be exactly three days")
        if self.outcome_window_days != 1:
            raise ValueError("outcome window must be exactly one day")
        if self.random_seed != RANDOM_SEED:
            raise ValueError("research profile random seed is frozen")
        if self.bootstrap_block_days != BOOTSTRAP_BLOCK_DAYS:
            raise ValueError("bootstrap block days are frozen")
        if self.bootstrap_resamples != BOOTSTRAP_RESAMPLES:
            raise ValueError("bootstrap resamples are frozen")
        if self.minimum_episodes != MIN_EPISODES:
            raise ValueError("minimum episodes are frozen")
        if self.minimum_calendar_months != MIN_CALENDAR_MONTHS:
            raise ValueError("minimum calendar months are frozen")
        if self.minimum_closed_trades != MIN_CLOSED_TRADES:
            raise ValueError("minimum closed trades are frozen")
        if (
            not isinstance(self.regularization, (int, float))
            or isinstance(self.regularization, bool)
            or not math.isfinite(self.regularization)
        ):
            raise ValueError("regularization must be finite")
        if self.regularization != REGULARIZATION:
            raise ValueError("regularization is frozen")
        if (
            not isinstance(self.bootstrap_confidence, (int, float))
            or isinstance(self.bootstrap_confidence, bool)
            or not math.isfinite(self.bootstrap_confidence)
        ):
            raise ValueError("bootstrap confidence must be finite")
        if self.bootstrap_confidence != BOOTSTRAP_CONFIDENCE:
            raise ValueError("bootstrap confidence is frozen")
        if self.strict_risk_policy != STRICT_RISK_POLICY:
            raise ValueError("strict risk policy is frozen")
        sensitivity = dict(self.sensitivity_policies)
        if sensitivity != dict(SENSITIVITY_POLICIES):
            raise ValueError("sensitivity policy metadata is frozen")
        if not isinstance(self.fold, ThreeDayDailyWalkForwardFold):
            raise ValueError("research profile requires a three-day daily fold")
        if self.fold != ThreeDayDailyWalkForwardFold.default():
            raise ValueError("research profile must use the normative chronology")
        object.__setattr__(self, "sensitivity_policies", MappingProxyType(sensitivity))

    def canonical_payload(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "random_seed": self.random_seed,
            "model_type": self.model_type,
            "covariance_type": self.covariance_type,
            "cluster_count": self.cluster_count,
            "regularization": _number_text(self.regularization),
            "feature_window_days": self.feature_window_days,
            "outcome_window_days": self.outcome_window_days,
            "bootstrap_block_days": self.bootstrap_block_days,
            "bootstrap_resamples": self.bootstrap_resamples,
            "bootstrap_confidence": _number_text(self.bootstrap_confidence),
            "minimum_episodes": self.minimum_episodes,
            "minimum_calendar_months": self.minimum_calendar_months,
            "minimum_closed_trades": self.minimum_closed_trades,
            "fold": {
                name: _interval_payload(getattr(self.fold, name))
                for name in ("cluster_fit", "mapping_fit", "validation", "test")
            },
        }


def _utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _is_midnight_utc(value: datetime) -> bool:
    return value.tzinfo is timezone.utc and value.time() == datetime.min.time()


def _number_text(value: float) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def _interval_payload(interval: UtcInterval) -> dict[str, str]:
    return {
        "start_at": interval.start_at.isoformat().replace("+00:00", "Z"),
        "end_at": interval.end_at.isoformat().replace("+00:00", "Z"),
    }


__all__ = [
    "BOOTSTRAP_BLOCK_DAYS",
    "BOOTSTRAP_CONFIDENCE",
    "BOOTSTRAP_RESAMPLES",
    "CLUSTER_COUNT",
    "COVARIANCE_TYPE",
    "MIN_CALENDAR_MONTHS",
    "MIN_CLOSED_TRADES",
    "MIN_EPISODES",
    "MODEL_TYPE",
    "PROFILE_ID",
    "RANDOM_SEED",
    "REGULARIZATION",
    "SENSITIVITY_POLICIES",
    "STRICT_RISK_POLICY",
    "DailyRiskPolicy",
    "ThreeDayDailyResearchProfile",
    "ThreeDayDailyWalkForwardFold",
]
