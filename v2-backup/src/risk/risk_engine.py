from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List

from loguru import logger

from src.binance.service.trader.account_service import AccountService
from src.binance.vo.trader.account_position_default import DefaultAccountPositionVo
from src.ops.service.execution_anomaly.execution_anomaly_service import ExecutionAnomalyService
from src.trade.service.trade_fill.trade_fill_service import TradeFillService


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() == "true"


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default


def _position_value(
    position: DefaultAccountPositionVo | dict,
    dict_key: str,
    vo_attr: str,
    default: float = 0.0,
) -> float:
    if isinstance(position, dict):
        raw = position.get(dict_key, default)
    else:
        raw = getattr(position, vo_attr, default)
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return default


def _position_symbol(position: DefaultAccountPositionVo | dict) -> str | None:
    if isinstance(position, dict):
        return position.get("symbol")
    return position.symbol
    try:
        return int(value)
    except ValueError:
        return default


@dataclass
class RiskDecision:
    allowed: bool
    reasons: List[str]


class RiskEngine:
    def __init__(self):
        self.enabled = _env_bool("ENABLE_RISK_ENGINE", False)
        self.daily_loss_limit_pct = _env_float("DAILY_LOSS_LIMIT_PCT", 0.0)
        self.weekly_loss_limit_pct = _env_float("WEEKLY_LOSS_LIMIT_PCT", 0.0)
        self.consecutive_loss_limit = _env_int("CONSECUTIVE_LOSS_LIMIT", 0)
        self.cooldown_minutes = _env_int("COOLDOWN_MINUTES", 0)
        self.max_open_positions = _env_int("MAX_OPEN_POSITIONS", 1)
        self.max_exposure_total_pct = _env_float("MAX_EXPOSURE_TOTAL_PCT", 1.0)
        self.max_exposure_per_symbol_pct = _env_float("MAX_EXPOSURE_PER_SYMBOL_PCT", 0.5)
        self.max_leverage = _env_float("MAX_LEVERAGE", 3.0)
        self.vol_shock_enabled = _env_bool("VOL_SHOCK_ENABLED", False)
        self.vol_shock_atr_z = _env_float("VOL_SHOCK_ATR_Z", 3.0)
        self.exec_anomaly_block_enabled = _env_bool("EXEC_ANOMALY_BLOCK_ENABLED", False)
        self.exec_anomaly_rate_threshold = _env_float("KILL_ANOMALY_RATE", 0.2)

        self.account_service = AccountService()
        self.trade_fill_service = TradeFillService()
        self.execution_anomaly_service = ExecutionAnomalyService()

    async def evaluate(self, symbol: str, leverage: float | None = None) -> RiskDecision:
        if not self.enabled:
            return RiskDecision(allowed=True, reasons=[])

        reasons: List[str] = []
        allowed = True

        equity = None
        try:
            equity = float(self.account_service.get_usdt_balance())
        except Exception as exc:  # noqa: BLE001 - allow safe fallback
            logger.warning(f"risk_engine: failed to fetch equity: {exc}")
            reasons.append("equity_unavailable")

        if leverage is not None and leverage > self.max_leverage:
            allowed = False
            reasons.append("max_leverage_exceeded")

        positions = []
        try:
            positions = self.account_service.get_positions()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"risk_engine: failed to fetch positions: {exc}")
            reasons.append("positions_unavailable")

        open_positions = [p for p in positions if abs(_position_value(p, "positionAmt", "position_amt")) > 0]
        if self.max_open_positions > 0 and len(open_positions) >= self.max_open_positions:
            allowed = False
            reasons.append("max_open_positions")

        if equity:
            total_exposure = 0.0
            symbol_exposure = 0.0
            for position in open_positions:
                amt = abs(_position_value(position, "positionAmt", "position_amt"))
                entry_price = _position_value(position, "entryPrice", "entry_price")
                notional = amt * entry_price
                total_exposure += notional
                if _position_symbol(position) == symbol:
                    symbol_exposure += notional
            if total_exposure / equity > self.max_exposure_total_pct:
                allowed = False
                reasons.append("max_total_exposure")
            if symbol_exposure / equity > self.max_exposure_per_symbol_pct:
                allowed = False
                reasons.append("max_symbol_exposure")

        now = datetime.now(timezone.utc)
        if self.daily_loss_limit_pct > 0 and equity:
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
            trades = await self.trade_fill_service.find_closed_trades_since(since)
            pnl = sum(float(t.pnl_usd or 0) for t in trades)
            if pnl < 0 and abs(pnl) / equity > self.daily_loss_limit_pct:
                allowed = False
                reasons.append("daily_loss_limit")

        if self.weekly_loss_limit_pct > 0 and equity:
            since = now - timedelta(days=7)
            trades = await self.trade_fill_service.find_closed_trades_since(since)
            pnl = sum(float(t.pnl_usd or 0) for t in trades)
            if pnl < 0 and abs(pnl) / equity > self.weekly_loss_limit_pct:
                allowed = False
                reasons.append("weekly_loss_limit")

        if self.consecutive_loss_limit > 0:
            trades = await self.trade_fill_service.find_recent_closed_trades(self.consecutive_loss_limit)
            losses = 0
            for trade in trades:
                if (trade.pnl_usd or 0) < 0:
                    losses += 1
                else:
                    break
            if losses >= self.consecutive_loss_limit:
                allowed = False
                reasons.append("consecutive_losses")

        if self.cooldown_minutes > 0:
            trades = await self.trade_fill_service.find_recent_closed_trades(1)
            if trades and trades[0].exit_ts:
                elapsed = now - trades[0].exit_ts
                if elapsed.total_seconds() < self.cooldown_minutes * 60:
                    allowed = False
                    reasons.append("cooldown_active")

        if self.exec_anomaly_block_enabled:
            since = now - timedelta(days=1)
            anomalies = await self.execution_anomaly_service.count_recent_anomalies(since)
            trades = await self.trade_fill_service.find_closed_trades_since(since)
            trade_count = max(1, len(trades))
            if anomalies / trade_count > self.exec_anomaly_rate_threshold:
                allowed = False
                reasons.append("execution_anomaly_rate")

        if self.vol_shock_enabled:
            reasons.append("vol_shock_check_unavailable")

        logger.bind(
            run_id=None,
            symbol=symbol,
            timeframe=None,
            action_id=None,
            job_id=None,
            order_id=None,
            signal_log_id=None,
        ).info(f"risk_engine decision allowed={allowed} reasons={reasons}")

        return RiskDecision(allowed=allowed, reasons=reasons)
