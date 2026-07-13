from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping

from src.domain.market import Candle
from src.domain.signal import Signal, SignalDirection, SignalReason
from src.domain.strategy import StrategyContext, StrategyResult


@dataclass(frozen=True)
class SessionVolumeProfile:
    poc: Decimal
    value_area_high: Decimal
    value_area_low: Decimal
    total_volume: Decimal
    volume_by_price: Mapping[Decimal, Decimal]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "volume_by_price",
            MappingProxyType(dict(self.volume_by_price)),
        )


@dataclass(frozen=True)
class SessionVolumeProfileStrategy:
    name: str = "session-volume-profile"
    price_bin_size: Decimal = Decimal("1")
    value_area_ratio: Decimal = Decimal("0.70")
    profile_min_candles: int = 3
    breakout_volume_multiplier: Decimal = Decimal("1.20")
    rejection_wick_ratio: Decimal = Decimal("0.40")

    def __post_init__(self) -> None:
        if self.price_bin_size <= Decimal("0"):
            raise ValueError("price_bin_size must be greater than zero")
        if self.value_area_ratio <= Decimal("0") or self.value_area_ratio > Decimal("1"):
            raise ValueError("value_area_ratio must be within (0, 1]")
        if self.profile_min_candles < 1:
            raise ValueError("profile_min_candles must be greater than zero")
        if self.breakout_volume_multiplier < Decimal("0"):
            raise ValueError("breakout_volume_multiplier must be greater than or equal to zero")
        if self.rejection_wick_ratio < Decimal("0") or self.rejection_wick_ratio > Decimal("1"):
            raise ValueError("rejection_wick_ratio must be between zero and one")

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        candles = context.market.candles
        if len(candles) < self.profile_min_candles:
            return self._wait("insufficient_candles")

        profile = _build_profile(candles, self.price_bin_size, self.value_area_ratio)
        if profile.total_volume == Decimal("0") or not profile.volume_by_price:
            return self._wait("empty_profile", profile)

        latest = context.market.latest_candle
        average_volume = profile.total_volume / Decimal(len(candles))
        volume_confirmed = latest.volume >= average_volume * self.breakout_volume_multiplier

        if latest.low_price < profile.value_area_low and latest.high_price > profile.value_area_high:
            return self._wait("ambiguous_value_area_overlap", profile)

        lower_rejection = (
            latest.low_price < profile.value_area_low
            and latest.close_price >= profile.value_area_low
            and _lower_wick_ratio(latest) >= self.rejection_wick_ratio
        )
        upper_rejection = (
            latest.high_price > profile.value_area_high
            and latest.close_price <= profile.value_area_high
            and _upper_wick_ratio(latest) >= self.rejection_wick_ratio
        )
        upper_breakout = latest.close_price >= profile.value_area_high and volume_confirmed
        lower_breakout = latest.close_price <= profile.value_area_low and volume_confirmed

        signal_count = sum((lower_rejection, upper_rejection, upper_breakout, lower_breakout))
        if signal_count > 1:
            return self._wait("conflicting_profile_signals", profile)

        if lower_rejection:
            return self._directional_result(
                SignalDirection.LONG,
                "lower_rejection",
                "lower_value_rejection",
                "latest candle rejected below value area low",
                profile,
                latest,
                average_volume,
                Decimal("0.45"),
            )
        if upper_rejection:
            return self._directional_result(
                SignalDirection.SHORT,
                "upper_rejection",
                "upper_value_rejection",
                "latest candle rejected above value area high",
                profile,
                latest,
                average_volume,
                Decimal("0.45"),
            )
        if upper_breakout:
            return self._directional_result(
                SignalDirection.LONG,
                "upper_breakout",
                "upper_value_breakout",
                "latest candle closed through value area high with volume confirmation",
                profile,
                latest,
                average_volume,
                Decimal("0.50"),
            )
        if lower_breakout:
            return self._directional_result(
                SignalDirection.SHORT,
                "lower_breakout",
                "lower_value_breakout",
                "latest candle closed through value area low with volume confirmation",
                profile,
                latest,
                average_volume,
                Decimal("0.50"),
            )

        if latest.close_price > profile.value_area_high or latest.close_price < profile.value_area_low:
            return self._wait("unconfirmed_breakout_volume", profile)

        if (
            profile.value_area_low <= latest.close_price <= profile.value_area_high
            and abs(latest.close_price - profile.poc) <= self.price_bin_size
        ):
            return self._wait("balanced_near_poc", profile)

        return self._wait("no_profile_signal", profile)

    def _directional_result(
        self,
        direction: SignalDirection,
        decision_type: str,
        reason_code: str,
        reason_message: str,
        profile: SessionVolumeProfile,
        latest: Candle,
        average_volume: Decimal,
        base_confidence: Decimal,
    ) -> StrategyResult:
        confidence = _confidence(
            base_confidence,
            latest,
            profile,
            self.price_bin_size,
            average_volume,
        )
        return StrategyResult(
            name=self.name,
            signal=Signal(
                direction=direction,
                confidence=confidence,
                reasons=(
                    SignalReason(
                        code=reason_code,
                        message=reason_message,
                        metadata={
                            **self._profile_metadata(profile, decision_type),
                            "upper_wick_ratio": str(_upper_wick_ratio(latest)),
                            "lower_wick_ratio": str(_lower_wick_ratio(latest)),
                            "latest_close": str(latest.close_price),
                            "latest_volume": str(latest.volume),
                        },
                    ),
                ),
            ),
            metadata=self._profile_metadata(profile, decision_type),
        )

    def _wait(
        self,
        reason: str,
        profile: SessionVolumeProfile | None = None,
    ) -> StrategyResult:
        metadata = (
            {"decision_type": "wait"}
            if profile is None
            else self._profile_metadata(profile, "wait")
        )
        return StrategyResult(
            name=self.name,
            signal=Signal.wait(metadata={"reason": reason}),
            metadata=metadata,
        )

    def _profile_metadata(
        self,
        profile: SessionVolumeProfile,
        decision_type: str,
    ) -> dict[str, str]:
        return {
            "price_bin_size": str(self.price_bin_size),
            "value_area_ratio": str(self.value_area_ratio),
            "poc": str(profile.poc),
            "value_area_high": str(profile.value_area_high),
            "value_area_low": str(profile.value_area_low),
            "total_volume": str(profile.total_volume),
            "profile_bin_count": str(len(profile.volume_by_price)),
            "decision_type": decision_type,
        }


def _build_profile(
    candles: tuple[Candle, ...],
    price_bin_size: Decimal,
    value_area_ratio: Decimal,
) -> SessionVolumeProfile:
    if price_bin_size <= Decimal("0"):
        raise ValueError("price_bin_size must be greater than zero")
    if value_area_ratio <= Decimal("0") or value_area_ratio > Decimal("1"):
        raise ValueError("value_area_ratio must be within (0, 1]")

    volume_by_price: dict[Decimal, Decimal] = {}
    for candle in candles:
        bins = _price_bins(candle.low_price, candle.high_price, price_bin_size)
        volume_per_bin = candle.volume / Decimal(len(bins))
        for price_bin in bins:
            volume_by_price[price_bin] = volume_by_price.get(price_bin, Decimal("0")) + volume_per_bin

    if not volume_by_price:
        return SessionVolumeProfile(
            poc=Decimal("0"),
            value_area_high=Decimal("0"),
            value_area_low=Decimal("0"),
            total_volume=Decimal("0"),
            volume_by_price={},
        )

    total_volume = sum(volume_by_price.values(), Decimal("0"))
    poc = min(
        volume_by_price,
        key=lambda price: (-volume_by_price[price], price),
    )
    value_area_low, value_area_high = _value_area_bounds(
        volume_by_price,
        poc,
        total_volume * value_area_ratio,
    )
    return SessionVolumeProfile(
        poc=poc,
        value_area_high=value_area_high,
        value_area_low=value_area_low,
        total_volume=total_volume,
        volume_by_price=volume_by_price,
    )


def _price_bins(low_price: Decimal, high_price: Decimal, price_bin_size: Decimal) -> tuple[Decimal, ...]:
    low_index = int(low_price // price_bin_size)
    high_index = int(high_price // price_bin_size)
    return tuple(Decimal(index) * price_bin_size for index in range(low_index, high_index + 1))


def _value_area_bounds(
    volume_by_price: Mapping[Decimal, Decimal],
    poc: Decimal,
    target_volume: Decimal,
) -> tuple[Decimal, Decimal]:
    prices = sorted(volume_by_price)
    poc_index = prices.index(poc)
    low_index = high_index = poc_index
    cumulative = volume_by_price[poc]

    while cumulative < target_volume and (low_index > 0 or high_index < len(prices) - 1):
        lower_volume = volume_by_price[prices[low_index - 1]] if low_index > 0 else None
        upper_volume = volume_by_price[prices[high_index + 1]] if high_index < len(prices) - 1 else None

        if lower_volume is not None and (
            upper_volume is None or lower_volume >= upper_volume
        ):
            low_index -= 1
            cumulative += volume_by_price[prices[low_index]]
        elif upper_volume is not None:
            high_index += 1
            cumulative += volume_by_price[prices[high_index]]

    return prices[low_index], prices[high_index]


def _upper_wick_ratio(candle: Candle) -> Decimal:
    candle_range = candle.high_price - candle.low_price
    if candle_range == Decimal("0"):
        return Decimal("0")
    body_top = max(candle.open_price, candle.close_price)
    return (candle.high_price - body_top) / candle_range


def _lower_wick_ratio(candle: Candle) -> Decimal:
    candle_range = candle.high_price - candle.low_price
    if candle_range == Decimal("0"):
        return Decimal("0")
    body_bottom = min(candle.open_price, candle.close_price)
    return (body_bottom - candle.low_price) / candle_range


def _confidence(
    base_confidence: Decimal,
    latest: Candle,
    profile: SessionVolumeProfile,
    price_bin_size: Decimal,
    average_volume: Decimal,
) -> Decimal:
    if latest.close_price > profile.value_area_high:
        distance = latest.close_price - profile.value_area_high
    elif latest.close_price < profile.value_area_low:
        distance = profile.value_area_low - latest.close_price
    else:
        distance = min(
            abs(latest.close_price - profile.value_area_high),
            abs(latest.close_price - profile.value_area_low),
        )

    distance_bonus = min(Decimal("0.25"), (distance / price_bin_size) * Decimal("0.05"))
    volume_ratio = Decimal("0") if average_volume == Decimal("0") else latest.volume / average_volume
    volume_bonus = min(Decimal("0.20"), volume_ratio * Decimal("0.05"))
    return min(Decimal("1.00"), max(Decimal("0.10"), base_confidence + distance_bonus + volume_bonus))
