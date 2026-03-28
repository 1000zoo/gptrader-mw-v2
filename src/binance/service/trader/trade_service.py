import os
from typing import Optional

from loguru import logger

from src.binance.api.trader.trade_api import TradeApi
from src.binance.dto.trader.trade_execute_dto import TradeExecuteDto
from src.calibration.calibration_service import CalibrationService
from src.common.config import THRESHOLD
from src.common.exception.external_api_error import ExternalApiError
from src.common.exception.invalid_request_exception import InvalidRequestException
from src.ops.service.kill_switch.kill_switch_service import KillSwitchService
from src.ops.service.system_state.system_state_service import SystemStateService
from src.risk.risk_engine import RiskEngine
from src.signal.service.signal_log.signal_log_service import SignalLogService
from src.trade.service.trade_fill.trade_fill_service import TradeFillService
from src.trade.vo.trade_fill.default import DefaultTradeFillVo


def _normalize_confidence(confidence: Optional[float]) -> Optional[float]:
    if confidence is None:
        return None
    if confidence > 1:
        return confidence / 100
    return confidence


def _normalize_side(side: Optional[str]) -> Optional[str]:
    if not side:
        return None
    side_upper = side.upper()
    if side_upper in {"LONG", "BUY"}:
        return "BUY"
    if side_upper in {"SHORT", "SELL"}:
        return "SELL"
    if side_upper == "NONE":
        return None
    return None


class TradeService:
    def __init__(self):
        self.tradeApi = TradeApi()
        self.system_state_service = SystemStateService()
        self.signal_log_service = SignalLogService()
        self.trade_fill_service = TradeFillService()
        self.risk_engine = RiskEngine()
        self.kill_switch_service = KillSwitchService()
        self.calibration_service = CalibrationService()
        self.enable_risk_engine = os.getenv("ENABLE_RISK_ENGINE", "false").lower() == "true"
        self.enable_calibration = os.getenv("ENABLE_CALIBRATION", "false").lower() == "true"
        self.enable_dynamic_threshold = os.getenv("ENABLE_DYNAMIC_THRESHOLD", "false").lower() == "true"
        self.enable_risk_sizing = os.getenv("ENABLE_RISK_SIZING", "false").lower() == "true"
        self.enable_kill_switch = os.getenv("ENABLE_KILL_SWITCH", "false").lower() == "true"
        self.min_trades_per_bucket = int(os.getenv("MIN_TRADES_PER_BUCKET", "30"))
        self.risk_per_trade_pct = float(os.getenv("RISK_PER_TRADE_PCT", "0.003"))
        self.max_notional_pct = float(os.getenv("MAX_NOTIONAL_PCT", "0.3"))
        self.default_sl_atr_mult = float(os.getenv("DEFAULT_SL_ATR_MULT", "1.0"))
        self.default_tp_atr_mult = float(os.getenv("DEFAULT_TP_ATR_MULT", "1.5"))

    async def _check_system_state(self) -> None:
        state = await self.system_state_service.find_latest_state()
        if state and state.trading_enabled is False:
            logger.info("trading disabled by system_state")
            raise InvalidRequestException("Trading is disabled by system_state.")

    async def open_from_analyze(self, dto: TradeExecuteDto):
        await self._check_system_state()
        signal_log_id = dto.signal_log_id
        if not signal_log_id and dto.batch_id:
            latest_signal = await self.signal_log_service.find_latest_by_run_id(dto.batch_id, dto.symbol_id)
            signal_log_id = latest_signal.id if latest_signal else None

        if self.enable_kill_switch:
            allowed = await self.kill_switch_service.evaluate_and_update()
            if not allowed:
                logger.info("kill switch active, blocking trade")
                if signal_log_id:
                    await self.signal_log_service.update_gate_decision(
                        signal_log_id, False, "kill_switch_active"
                    )
                raise InvalidRequestException("Kill switch is active.")
        confidence = _normalize_confidence(dto.confidence)
        if confidence is None:
            logger.info(f"confidence is missing: {dto.symbol_id}")
            raise InvalidRequestException("Confidence is required for trade execution.")

        if self.enable_calibration or self.enable_dynamic_threshold:
            stats = await self.calibration_service.compute_bucket_stats(
                c_interval=dto.c_interval or "default",
                symbol_id=dto.symbol_id,
            )
            calibrated = self.calibration_service.calibrate(confidence, stats)
            dynamic_threshold = None
            if self.enable_dynamic_threshold:
                dynamic_threshold = self.calibration_service.select_dynamic_threshold(
                    stats, self.min_trades_per_bucket
                )
            if signal_log_id:
                await self.signal_log_service.update_calibration_fields(
                    signal_log_id, calibrated, dynamic_threshold
                )
            if self.enable_calibration and calibrated is not None:
                confidence = calibrated
            if self.enable_dynamic_threshold and dynamic_threshold is not None:
                if confidence < dynamic_threshold:
                    raise InvalidRequestException("Confidence below dynamic threshold.")

        if confidence < THRESHOLD:
            logger.info(f"confidence is so low: {dto.symbol_id}, {confidence}")
            raise InvalidRequestException("Confidence is below the execution threshold.")

        side = _normalize_side(dto.side)
        if not side:
            logger.info(f"invalid side: {dto.symbol_id}, {dto.side}")
            raise InvalidRequestException("Trade side is invalid.")
        if dto.regime == "UPTREND" and side != "BUY":
            raise InvalidRequestException("Regime policy blocks short entry in UPTREND.")
        if dto.regime == "DOWNTREND" and side != "SELL":
            raise InvalidRequestException("Regime policy blocks long entry in DOWNTREND.")
        if dto.regime in {"TRANSITION", "UNKNOWN"}:
            raise InvalidRequestException(f"Regime policy blocks entries in {dto.regime}.")

        entry_price = dto.entry_price
        if entry_price is None and self.enable_risk_sizing:
            entry_price = self.tradeApi._get_ticker_price(dto.symbol_id)
        if dto.sl is None and self.enable_risk_sizing and entry_price is not None:
            dto.sl = entry_price - (entry_price * 0.01 * self.default_sl_atr_mult)
        if dto.tp is None and self.enable_risk_sizing and entry_price is not None:
            dto.tp = entry_price + (entry_price * 0.01 * self.default_tp_atr_mult)
        if dto.tp is None or dto.sl is None:
            logger.info(f"tp/sl is missing: {dto.symbol_id}, tp={dto.tp}, sl={dto.sl}")
            raise InvalidRequestException("TP/SL values are required for trade execution.")

        leverage = int(5 + (confidence - THRESHOLD) / (1.0 - THRESHOLD) * (15 - 5))
        percent_of_balance = round(0.2 + (confidence - THRESHOLD) / (1.0 - THRESHOLD) * (0.5 - 0.2), 2)

        leverage_mult = dto.leverage_mult if dto.leverage_mult is not None else 1.0
        size_mult = dto.position_size_mult if dto.position_size_mult is not None else 1.0
        leverage = max(1, int(round(leverage * max(leverage_mult, 0.0))))
        percent_of_balance = max(0.0, percent_of_balance * max(size_mult, 0.0))
        if percent_of_balance <= 0:
            raise InvalidRequestException("Position size is zero after regime policy.")

        risk_budget_usd = None
        if self.enable_risk_sizing:
            balance = float(self.tradeApi.accountApi.get_usdt_balance())
            entry_price = entry_price or self.tradeApi._get_ticker_price(dto.symbol_id)
            stop_distance = abs(entry_price - float(dto.sl))
            if stop_distance <= 0:
                raise InvalidRequestException("Invalid stop distance for risk sizing.")
            risk_budget_usd = balance * self.risk_per_trade_pct
            qty = risk_budget_usd / stop_distance
            notional = qty * entry_price
            max_notional = balance * self.max_notional_pct
            if notional > max_notional:
                notional = max_notional
                qty = notional / entry_price
            symbol_info = self.tradeApi.symbolApi.get_symbol_info(dto.symbol_id)
            if symbol_info:
                min_qty = float(symbol_info[0].get("minQty") or 0)
                if min_qty > 0:
                    min_percent = (min_qty * entry_price) / (balance * leverage)
                    percent_of_balance = max(percent_of_balance, min_percent)
            percent_of_balance = max(
                percent_of_balance, (qty * entry_price) / (balance * leverage)
            )

        if self.enable_risk_engine:
            decision = await self.risk_engine.evaluate(dto.symbol_id, leverage=leverage)
            if signal_log_id:
                await self.signal_log_service.update_gate_decision(
                    signal_log_id, decision.allowed, ",".join(decision.reasons)
                )
            if not decision.allowed:
                raise InvalidRequestException(
                    f"Risk engine rejected trade: {','.join(decision.reasons)}"
                )

        try:
            response = self.tradeApi.open_market_position(
                symbol=dto.symbol_id,
                side=side,
                percent=percent_of_balance,
                leverage=leverage,
                tp=dto.tp,
                sl=dto.sl,
            )
        except ExternalApiError as e:
            logger.error(f"error at `open_from_analyze` {dto.symbol_id}:: {e}")
            raise ExternalApiError("Failed to open market position.") from e
        if not response or response.get("error") or response.get("success") is False:
            raise ExternalApiError("Market position response indicated failure.")

        trade_fill = DefaultTradeFillVo(
            signal_log_id=signal_log_id,
            symbol_id=dto.symbol_id,
            side="LONG" if side == "BUY" else "SHORT",
            entry_order_id=response.get("main_response", {}).get("clientOrderId"),
            entry_price=dto.entry_price,
            entry_ts=None,
            status="OPEN",
            risk_budget_usd=risk_budget_usd,
        )
        await self.trade_fill_service.create_trade_fill(trade_fill)

        logger.bind(
            run_id=dto.batch_id,
            symbol=dto.symbol_id,
            timeframe=dto.c_interval,
            action_id=None,
            job_id=dto.batch_id,
            order_id=trade_fill.entry_order_id,
            signal_log_id=signal_log_id,
        ).info("trade_fill created (OPEN)")
        return response

    def cancel_open_orders(self, symbol: str):
        try:
            response = self.tradeApi.cancel_open_orders(symbol)
        except ExternalApiError as e:
            logger.error(f"error at `service.cancel_all_open_orders`: {e}")
            raise ExternalApiError("Failed to cancel open orders.") from e
        if response is None or response.get("error") or response.get("success") is False:
            raise ExternalApiError("Cancel open orders response indicated failure.")
        return response

