from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OperationalMessage:
    title: str
    body: str
    severity: Severity = Severity.INFO
    source: str = "gptrader"
    occurred_at: datetime | None = None
    metadata: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        title = self.title.strip()
        body = self.body.strip()
        source = self.source.strip()
        if not title:
            raise ValueError("title is required")
        if not body:
            raise ValueError("body is required")
        if not source:
            raise ValueError("source is required")

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "body", body)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "occurred_at", self.occurred_at or _utc_now())
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata or {})),
        )

    def format_text(self) -> str:
        metadata_lines = [
            f"- {key}: {value}" for key, value in sorted((self.metadata or {}).items())
        ]
        metadata_text = "" if not metadata_lines else "\n" + "\n".join(metadata_lines)
        return (
            f"[{self.severity.value.upper()}] {self.title}\n"
            f"{self.body}\n"
            f"source={self.source} occurred_at={self.occurred_at.isoformat()}"
            f"{metadata_text}"
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "title": self.title,
            "body": self.body,
            "severity": self.severity.value,
            "source": self.source,
            "occurred_at": self.occurred_at.isoformat(),
            "metadata": dict(self.metadata or {}),
        }


@dataclass(frozen=True)
class NotificationResult:
    delivered: bool
    provider: str
    destination: str
    error: Exception | None = None

    @property
    def failed(self) -> bool:
        return not self.delivered
