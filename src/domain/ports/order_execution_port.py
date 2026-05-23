from datetime import datetime
from typing import Protocol, runtime_checkable

from src.domain.execution import ExecutionReport, OrderRequest, OrderResult
from src.domain.market import Symbol


@runtime_checkable
class OrderExecutionPort(Protocol):
    def submit_order(self, request: OrderRequest) -> OrderResult:
        ...

    def load_execution_reports(
        self,
        symbol: Symbol,
        since: datetime,
        until: datetime,
    ) -> tuple[ExecutionReport, ...]:
        ...
