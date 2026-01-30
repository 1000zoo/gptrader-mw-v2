import os
from typing import Dict, Optional

from datetime import datetime, timezone, timedelta

from loguru import logger

from src.binance.ws.constants.enums import KeyEnum
from src.binance.service.position_event.position_event_service import PositionEventService
from src.binance.service.trader.trade_service import TradeService
from src.binance.vo.position_event.default import DefaultPositionEventVo
from src.common.util.date import reg_ymd_now
from src.job.service.job.job_run_service import JobRunService
from src.job.vo.job.default import DefaultJobRunVo
from src.trade.service.trade_fill.trade_fill_service import TradeFillService
from src.ops.service.execution_anomaly.execution_anomaly_service import ExecutionAnomalyService
from src.ops.vo.execution_anomaly.default import DefaultExecutionAnomalyVo

class OrderEventHandler:
    def __init__(self):
        self.tradeService = TradeService()
        self.positionService = PositionEventService()
        self.jobService = JobRunService()
        self.trade_fill_service = TradeFillService()
        self.execution_anomaly_service = ExecutionAnomalyService()
        self.missing_exit_minutes = int(os.getenv("MISSING_EXIT_MINUTES", "120"))
        self.partial_fill_ratio = float(os.getenv("PARTIAL_FILL_THRESHOLD", "0.1"))
        self.slippage_threshold_pct = float(os.getenv("SLIPPAGE_THRESHOLD_PCT", "0.01"))

    @staticmethod
    def _parse_ts(value: Optional[int]) -> Optional[datetime]:
        if value is None:
            return None
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)

    @staticmethod
    def _extract_price(order: Dict) -> Optional[float]:
        for key in ("ap", "L", "p", "avgPrice"):
            if key in order and order[key] is not None:
                try:
                    return float(order[key])
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _extract_qty(order: Dict) -> Optional[float]:
        for key in ("z", "l", "q", "aq"):
            if key in order and order[key] is not None:
                try:
                    return float(order[key])
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _extract_fee(order: Dict) -> Optional[float]:
        value = order.get("n")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(value: Optional[object]) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    async def _record_anomaly(
        self,
        batch_id: Optional[str],
        symbol_id: str,
        anomaly_type: str,
        severity: str,
        trade_fill_id: Optional[int],
        signal_log_id: Optional[int],
        order_id: Optional[str],
        payload: Dict,
    ) -> None:
        await self.execution_anomaly_service.create_execution_anomaly(
            DefaultExecutionAnomalyVo(
                run_id=batch_id,
                symbol_id=symbol_id,
                anomaly_type=anomaly_type,
                severity=severity,
                trade_fill_id=trade_fill_id,
                signal_log_id=signal_log_id,
                order_id=order_id,
                payload=payload,
            )
        )

    async def execute(self, message: Dict):
        logger.info(f"execute:: {message}")
        order = message[KeyEnum.ORDER_INFO.value]
        order_status = order[KeyEnum.ORDER_STATUS.value]
        execution_type = order.get(KeyEnum.EXECUTION_TYPE.value)
        symbol_id = order[KeyEnum.SYMBOL.value]

        job = await self.jobService.get_open_position_job(symbol_id=symbol_id)
        batch_id = job.batch_id
        message["batch_id"] = batch_id

        await self.positionService.add_position_event(message)

        client_order_id = order.get(KeyEnum.CLIENT_ORDER_ID.value)
        trade_fill = None
        if client_order_id:
            trade_fill = await self.trade_fill_service.find_by_entry_order_id(client_order_id)

        if order_status == "FILLED" and client_order_id and job and client_order_id == job.main_order_id:
            fill_price = self._extract_price(order)
            await self.trade_fill_service.update_entry_fill(
                client_order_id,
                entry_price=fill_price,
                entry_qty=self._extract_qty(order),
                entry_fee=self._extract_fee(order),
                entry_ts=self._parse_ts(order.get(KeyEnum.TRANSACTION_TIME.value)),
            )
            if trade_fill and trade_fill.entry_price and fill_price:
                slippage = abs(fill_price - trade_fill.entry_price) / trade_fill.entry_price
                if slippage > self.slippage_threshold_pct:
                    await self._record_anomaly(
                        batch_id=batch_id,
                        symbol_id=symbol_id,
                        anomaly_type="SLIPPAGE",
                        severity="MEDIUM",
                        trade_fill_id=trade_fill.id,
                        signal_log_id=trade_fill.signal_log_id,
                        order_id=client_order_id,
                        payload={"expected": trade_fill.entry_price, "fill": fill_price},
                    )

        if order.get("ot") == "LIQUIDATION" or execution_type == "LIQUIDATION":
            await self._record_anomaly(
                batch_id=batch_id,
                symbol_id=symbol_id,
                anomaly_type="LIQUIDATION",
                severity="HIGH",
                trade_fill_id=trade_fill.id if trade_fill else None,
                signal_log_id=trade_fill.signal_log_id if trade_fill else None,
                order_id=client_order_id,
                payload=order,
            )

        if order_status == "PARTIALLY_FILLED":
            filled_qty = self._extract_qty(order) or 0
            orig_qty = float(order.get("q") or 0)
            if orig_qty > 0 and filled_qty / orig_qty < self.partial_fill_ratio:
                await self._record_anomaly(
                    batch_id=batch_id,
                    symbol_id=symbol_id,
                    anomaly_type="PARTIAL_FILL_EXTREME",
                    severity="LOW",
                    trade_fill_id=trade_fill.id if trade_fill else None,
                    signal_log_id=trade_fill.signal_log_id if trade_fill else None,
                    order_id=client_order_id,
                    payload={"filled_qty": filled_qty, "orig_qty": orig_qty},
                )

        if trade_fill and trade_fill.entry_ts and trade_fill.status == "OPEN":
            elapsed = datetime.now(timezone.utc) - trade_fill.entry_ts
            if elapsed > timedelta(minutes=self.missing_exit_minutes):
                await self._record_anomaly(
                    batch_id=batch_id,
                    symbol_id=symbol_id,
                    anomaly_type="MISSING_EXIT",
                    severity="MEDIUM",
                    trade_fill_id=trade_fill.id,
                    signal_log_id=trade_fill.signal_log_id,
                    order_id=client_order_id,
                    payload={"minutes_open": elapsed.total_seconds() / 60},
                )

    async def algo_execute(self, message: Dict):
        logger.info(f"execute:: {message}")
        order = message[KeyEnum.ORDER_INFO.value]
        order_type = order[KeyEnum.ORDER_TYPE.value]
        algo_status = order[KeyEnum.ORDER_STATUS.value]
        symbol_id = order[KeyEnum.SYMBOL.value]

        job = await self.jobService.get_open_position_job(symbol_id=symbol_id)
        batch_id = job.batch_id

        await self.positionService.add_position_event_vo(DefaultPositionEventVo(
            batch_id=batch_id,
            reg_ymd=reg_ymd_now(),
            symbol_id=symbol_id,
            event_type=message["e"],
            side=order["S"],
            qty=order["q"],
            price=order["tp"],
            order_id=str(order["aid"]),
            position_side=order["ps"],
            order_type=order_type,
            execution_type=algo_status,
            order_status=algo_status,
            client_order_id=order.get("caid"),
        ))

        if algo_status == "FINISHED" and order_type in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET", "STOP_MARKET", "STOP"):
            exit_price = self._extract_price(order)
            exit_qty = self._extract_qty(order)
            if exit_price and exit_qty:
                pnl_usd = self._safe_float(order.get("p"))
                pnl_pct = None
                r_multiple = None
                if job and batch_id:
                    trade_fill = await self.trade_fill_service.find_by_entry_order_id(job.main_order_id)
                    if trade_fill and trade_fill.entry_price:
                        pnl_pct = (exit_price - trade_fill.entry_price) / trade_fill.entry_price
                    if trade_fill and trade_fill.risk_budget_usd and pnl_usd is not None:
                        r_multiple = pnl_usd / float(trade_fill.risk_budget_usd)
                    await self.trade_fill_service.update_exit_fill(
                        entry_order_id=job.main_order_id,
                        exit_order_id=order.get("caid"),
                        exit_price=exit_price,
                        exit_fee=None,
                        exit_ts=self._parse_ts(message.get(KeyEnum.TRANSACTION_TIME.value)),
                        pnl_usd=pnl_usd,
                        pnl_pct=pnl_pct,
                        r_multiple=r_multiple,
                        status="CLOSED",
                    )
                self.execute_close_logic(order)
                if batch_id:
                    await self.jobService.update_job_run(DefaultJobRunVo(
                        batch_id=batch_id, symbol_id=symbol_id, job_type='1600', finished_at=datetime.now(timezone.utc)
                    ))

    async def account_update(self, message: Dict):
        logger.info(f"account_update:: {message}")

    def execute_close_logic(self, order: Dict):
        symbol = order[KeyEnum.SYMBOL.value]
        self.tradeService.cancel_open_orders(symbol)
        logger.info(f"success to close open orders of {symbol}")
