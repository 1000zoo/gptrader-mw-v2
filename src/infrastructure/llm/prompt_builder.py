from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import json
from typing import Any

from src.domain.strategy import StrategyContext


@dataclass(frozen=True)
class PromptMessage:
    role: str
    content: str


class PromptBuilder:
    def build(
        self,
        *,
        strategy_name: str,
        instructions: str,
        context: StrategyContext,
    ) -> tuple[PromptMessage, ...]:
        return (
            PromptMessage(
                role="system",
                content=(
                    f"You are evaluating the {strategy_name.strip()} trading strategy. "
                    f"{instructions.strip()}"
                ),
            ),
            PromptMessage(
                role="user",
                content=json.dumps(
                    self._context_payload(context),
                    sort_keys=True,
                    separators=(",", ": "),
                ),
            ),
        )

    def _context_payload(self, context: StrategyContext) -> dict[str, Any]:
        latest_candle = context.market.latest_candle
        return {
            "symbol": context.market.symbol.pair,
            "timeframe": context.market.timeframe.label,
            "latest_candle": {
                "opened_at": self._serialize(latest_candle.opened_at),
                "closed_at": self._serialize(latest_candle.closed_at),
                "open": self._serialize(latest_candle.open_price),
                "high": self._serialize(latest_candle.high_price),
                "low": self._serialize(latest_candle.low_price),
                "close": self._serialize(latest_candle.close_price),
                "volume": self._serialize(latest_candle.volume),
            },
            "indicators": {
                value.key: {
                    "value": self._serialize(value.value),
                    "measured_at": self._serialize(value.measured_at),
                    "parameters": {
                        key: self._serialize(parameter)
                        for key, parameter in sorted(value.parameters.items())
                    },
                }
                for value in context.indicators.values
            },
            "metadata": self._serialize_mapping(context.metadata),
        }

    def _serialize_mapping(self, value: dict[str, object] | Any) -> dict[str, Any]:
        return {key: self._serialize(item) for key, item in sorted(dict(value).items())}

    def _serialize(self, value: object) -> object:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, int):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return self._serialize_mapping(value)
        if isinstance(value, (list, tuple)):
            return [self._serialize(item) for item in value]
        return value
