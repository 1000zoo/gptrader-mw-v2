from dataclasses import fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from fastapi import HTTPException


def to_response_payload(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_response_payload(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping | MappingProxyType):
        return {
            str(key): to_response_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple | list):
        return [to_response_payload(item) for item in value]
    return value


def execute_boundary(action) -> dict[str, object]:
    try:
        result = action()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "data": to_response_payload(result)}


def require_dependency(value: Any, name: str) -> Any:
    if value is None:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")
    return value
