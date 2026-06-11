from fastapi import FastAPI

from src.interfaces.api import create_app
from src.runtime.config import RuntimeSettings
from src.runtime.local_data import evaluate_local_example_strategy
from src.runtime.status import RuntimeStatus


class LocalRuntime:
    def __init__(self, settings: RuntimeSettings | None = None) -> None:
        self.settings = settings or RuntimeSettings()
        self.status = RuntimeStatus.local(self.settings)

    def health_details(self) -> dict[str, object]:
        return self.status.as_health_details()

    def readiness_details(self) -> dict[str, object]:
        details = self.status.as_health_details()
        details["ready_for"] = "local"
        details["example_strategy"] = evaluate_local_example_strategy(
            self.settings
        ).signal.direction.value
        return details

    def status_details(self) -> dict[str, object]:
        details = self.readiness_details()
        details["runtime"] = "local"
        details["trade_controls"] = "disabled"
        details["live_order_path"] = "disabled"
        return details

    def create_app(self) -> FastAPI:
        return create_app(
            health_provider=self.health_details,
            readiness_provider=self.readiness_details,
            status_provider=self.status_details,
        )


def create_local_runtime(settings: RuntimeSettings | None = None) -> LocalRuntime:
    return LocalRuntime(settings)


def create_local_app(settings: RuntimeSettings | None = None) -> FastAPI:
    return create_local_runtime(settings).create_app()
