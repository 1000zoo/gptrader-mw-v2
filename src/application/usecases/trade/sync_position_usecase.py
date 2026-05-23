from src.application.usecases.trade.dto import SyncPositionCommand, SyncPositionResult
from src.domain.execution import ExecutionReport, OrderStatus
from src.domain.ports import OrderExecutionPort
from src.domain.position import Position, PositionEvent


class SyncPositionUseCase:
    def __init__(self, order_execution: OrderExecutionPort) -> None:
        self._order_execution = order_execution

    def sync(self, command: SyncPositionCommand) -> SyncPositionResult:
        reports = self._order_execution.load_execution_reports(
            symbol=command.position.symbol,
            since=command.since,
            until=command.until,
        )
        position = command.position
        applied_reports: list[ExecutionReport] = []
        for report in reports:
            position = self._apply_report(position, report)
            applied_reports.append(report)

        return SyncPositionResult(
            position=position,
            applied_reports=tuple(applied_reports),
        )

    def _apply_report(self, position: Position, report: ExecutionReport) -> Position:
        if report.result.status not in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}:
            return position
        if report.result.executed_quantity is None:
            return position

        if report.request.reduce_only:
            return position.apply_event(
                PositionEvent.decrease(
                    quantity=report.result.executed_quantity,
                    price=report.result.average_price,
                )
            )

        return position.apply_event(report.to_position_event())
