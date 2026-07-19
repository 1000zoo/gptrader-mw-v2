from dataclasses import dataclass
from datetime import datetime, timezone

from src.runtime.config import RuntimeSettings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RuntimeDependency:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RuntimeStatus:
    settings: RuntimeSettings
    started_at: datetime
    dependencies: tuple[RuntimeDependency, ...]

    @classmethod
    def local(cls, settings: RuntimeSettings) -> "RuntimeStatus":
        return cls(
            settings=settings,
            started_at=_utc_now(),
            dependencies=(
                RuntimeDependency("exchange", "local", "external exchange disabled"),
                RuntimeDependency("persistence", "local", settings.database_url),
                RuntimeDependency("scheduler", "not_started", "runner not attached"),
                RuntimeDependency("websocket", "not_started", "listener not attached"),
            ),
        )

    def as_health_details(self) -> dict[str, object]:
        return {
            "mode": self.settings.mode.value,
            "live_armed": self.settings.live_armed,
            "symbol": self.settings.symbol,
            "timeframe": self.settings.timeframe,
            "started_at": self.started_at.isoformat(),
            "dependencies": [
                dependency.as_dict() for dependency in self.dependencies
            ],
        }
