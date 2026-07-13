from decimal import Decimal
import json
from typing import Any

from src.domain.signal import Signal, SignalDirection, SignalReason
from src.domain.strategy import StrategyResult


class LLMResponseParseError(ValueError):
    pass


class ResponseParser:
    def parse(self, *, strategy_name: str, raw_text: str) -> StrategyResult:
        try:
            payload = json.loads(raw_text)
            if not isinstance(payload, dict):
                raise ValueError("response must be a JSON object")

            direction = SignalDirection(str(payload["direction"]).lower())
            confidence = Decimal(str(payload["confidence"]))
            metadata = self._mapping(payload.get("metadata", {}))
            reasons = tuple(
                self._parse_reason(reason)
                for reason in payload.get("reasons", ())
            )
            signal = Signal(
                direction=direction,
                confidence=confidence,
                reasons=reasons,
                metadata=metadata,
            )
            return StrategyResult(name=strategy_name, signal=signal, metadata=metadata)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LLMResponseParseError("failed to parse LLM response") from exc

    def _parse_reason(self, payload: Any) -> SignalReason:
        if not isinstance(payload, dict):
            raise ValueError("reason must be a JSON object")

        return SignalReason(
            code=str(payload["code"]),
            message=str(payload["message"]),
            metadata=self._mapping(payload.get("metadata", {})),
        )

    def _mapping(self, payload: Any) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("metadata must be a JSON object")
        return dict(payload)

