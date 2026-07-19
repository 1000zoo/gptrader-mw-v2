from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.domain.signal import Signal, SignalDirection
from src.domain.strategy import Strategy, StrategyContext
from src.domain.signal_generator.signal_generator import GeneratedSignal


@dataclass(frozen=True)
class CompositeSignalGenerator:
    strategies: Sequence[Strategy]

    def __post_init__(self) -> None:
        strategies = tuple(self.strategies)
        if not strategies:
            raise ValueError("strategies are required")

        object.__setattr__(self, "strategies", strategies)

    def generate(self, context: StrategyContext) -> GeneratedSignal:
        results = tuple(strategy.evaluate(context) for strategy in self.strategies)
        winning_direction = self._winning_direction(results)
        if winning_direction is SignalDirection.WAIT:
            return GeneratedSignal(signal=Signal.wait(), strategy_results=results)

        winning_results = tuple(
            result
            for result in results
            if result.signal.direction is winning_direction
        )
        confidence = sum(
            (result.signal.confidence for result in winning_results),
            Decimal("0"),
        ) / Decimal(len(winning_results))

        return GeneratedSignal(
            signal=Signal(direction=winning_direction, confidence=confidence),
            strategy_results=results,
        )

    def _winning_direction(self, results) -> SignalDirection:
        scores = {
            SignalDirection.LONG: Decimal("0"),
            SignalDirection.SHORT: Decimal("0"),
        }
        for result in results:
            if result.signal.direction in scores:
                scores[result.signal.direction] += result.signal.confidence

        long_score = scores[SignalDirection.LONG]
        short_score = scores[SignalDirection.SHORT]
        if long_score == short_score:
            return SignalDirection.WAIT
        if long_score > short_score:
            return SignalDirection.LONG
        return SignalDirection.SHORT
