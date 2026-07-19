import json
from decimal import Decimal
from typing import Any

from src.domain.ports import SignalLogEntry
from src.domain.signal import Signal, SignalDirection, SignalReason
from src.domain.signal_generator import GeneratedSignal
from src.domain.strategy import StrategyResult


def dumps_signal_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def loads_signal_payload(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def signal_to_payload(signal: Signal) -> dict[str, Any]:
    return {
        "direction": signal.direction.value,
        "confidence": str(signal.confidence),
        "reasons": [
            {
                "code": reason.code,
                "message": reason.message,
                "metadata": dict(reason.metadata),
            }
            for reason in signal.reasons
        ],
        "metadata": dict(signal.metadata),
    }


def signal_from_payload(payload: dict[str, Any]) -> Signal:
    return Signal(
        direction=SignalDirection(payload["direction"]),
        confidence=Decimal(payload["confidence"]),
        reasons=tuple(
            SignalReason(
                code=reason["code"],
                message=reason["message"],
                metadata=reason.get("metadata", {}),
            )
            for reason in payload.get("reasons", ())
        ),
        metadata=payload.get("metadata", {}),
    )


def generated_signal_to_payload(generated_signal: GeneratedSignal) -> dict[str, Any]:
    return {
        "signal": signal_to_payload(generated_signal.signal),
        "strategy_results": [
            {
                "name": result.name,
                "signal": signal_to_payload(result.signal),
                "metadata": dict(result.metadata),
            }
            for result in generated_signal.strategy_results
        ],
        "metadata": dict(generated_signal.metadata),
    }


def generated_signal_from_payload(payload: dict[str, Any]) -> GeneratedSignal:
    return GeneratedSignal(
        signal=signal_from_payload(payload["signal"]),
        strategy_results=tuple(
            StrategyResult(
                name=result["name"],
                signal=signal_from_payload(result["signal"]),
                metadata=result.get("metadata", {}),
            )
            for result in payload.get("strategy_results", ())
        ),
        metadata=payload.get("metadata", {}),
    )


def signal_log_entry_to_payload(entry: SignalLogEntry) -> dict[str, Any]:
    return {
        "signal_id": entry.signal_id,
        "generator_id": entry.generator_id,
        "generated_signal": generated_signal_to_payload(entry.generated_signal),
    }


def signal_log_entry_from_payload(payload: dict[str, Any]) -> SignalLogEntry:
    return SignalLogEntry(
        signal_id=payload["signal_id"],
        generator_id=payload["generator_id"],
        generated_signal=generated_signal_from_payload(payload["generated_signal"]),
    )
